from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg.types.json import Jsonb

from .db import connect, migrate, owner
from .ocr import parse_label

UPLOAD_DIR = Path(os.environ.get("HEALTH_N1_UPLOAD_DIR", "/health/uploads"))
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="N-of-1 Health Logger", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.on_event("startup")
def startup() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    migrate()

def local_now(subject: dict[str, Any]) -> datetime:
    return datetime.now(ZoneInfo(subject["timezone"]))

def optional_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None

def optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None

def render(request: Request, name: str, **context: Any):
    context.setdefault("metabase_dashboard_url", metabase_experiment_dashboard_url())
    return templates.TemplateResponse(request, name, context)


def metabase_experiment_dashboard_url() -> str | None:
    """Return the user-facing dashboard URL without exposing any credentials."""
    configured = os.environ.get("HEALTH_METABASE_EXPERIMENT_DASHBOARD_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    domain = os.environ.get("DOMAIN", "").strip()
    if not domain:
        return None
    port = os.environ.get("HEALTH_METABASE_HOST_PORT", "13000")
    return f"http://{domain}:{port}/dashboard/2-health-overview"

@app.get("/sync")
def sync_help(request: Request):
    return render(request, "sync.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def today(request: Request):
    with connect() as conn:
        subject = owner(conn)
        now = local_now(subject); current_day = now.date()
        checkin = conn.execute("SELECT * FROM daily_checkins WHERE subject_id=%s AND checkin_date=%s", (subject["id"], current_day)).fetchone()
        due = conn.execute("SELECT * FROM intervention_templates WHERE subject_id=%s AND is_active AND active_from<=%s AND (active_until IS NULL OR active_until>=%s) ORDER BY name", (subject["id"], current_day, current_day)).fetchall()
        completed = conn.execute("SELECT template_id FROM intervention_events WHERE subject_id=%s AND occurred_at IS NOT NULL AND (occurred_at AT TIME ZONE %s)::date=%s AND adherence='completed'", (subject["id"], subject["timezone"], current_day)).fetchall()
        completed_ids = {row["template_id"] for row in completed}
        nutrition = conn.execute("SELECT * FROM n1_daily_nutrition WHERE subject_id=%s AND day=%s", (subject["id"], current_day)).fetchone()
    return render(request, "today.html", subject=subject, now=now, checkin=checkin, due=due, completed_ids=completed_ids, nutrition=nutrition)

@app.post("/checkins")
def save_checkin(
    request: Request, checkin_date: str = Form(...), weight_kg: str = Form(""), energy: str = Form(""), mood: str = Form(""), stress: str = Form(""), sleep_quality: str = Form(""), notes: str = Form("")
):
    with connect() as conn:
        subject = owner(conn)
        conn.execute("""INSERT INTO daily_checkins (subject_id,checkin_date,weight_kg,energy,mood,stress,sleep_quality,notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (subject_id,checkin_date) DO UPDATE SET
        weight_kg=EXCLUDED.weight_kg,energy=EXCLUDED.energy,mood=EXCLUDED.mood,stress=EXCLUDED.stress,sleep_quality=EXCLUDED.sleep_quality,notes=EXCLUDED.notes,updated_at=now()""",
        (subject["id"], date.fromisoformat(checkin_date), optional_float(weight_kg), int(energy) if energy else None, int(mood) if mood else None, int(stress) if stress else None, int(sleep_quality) if sleep_quality else None, notes or None))
        conn.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/templates/{template_id}/complete")
def complete_template(template_id: int):
    with connect() as conn:
        subject = owner(conn)
        item = conn.execute("SELECT * FROM intervention_templates WHERE id=%s AND subject_id=%s", (template_id, subject["id"])).fetchone()
        if not item: raise HTTPException(404)
        conn.execute("INSERT INTO intervention_events (subject_id,template_id,experiment_id,condition_id,name,occurred_at,dose,unit,adherence) VALUES (%s,%s,%s,%s,%s,now(),%s,%s,'completed')", (subject["id"], item["id"], item["experiment_id"], item["condition_id"], item["name"], item["dose"], item["unit"]))
        conn.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/experiments")
def experiments(request: Request):
    with connect() as conn:
        subject = owner(conn)
        rows = conn.execute("SELECT e.*, COALESCE(json_agg(c ORDER BY c.id) FILTER (WHERE c.id IS NOT NULL),'[]') AS conditions FROM experiments e LEFT JOIN experiment_conditions c ON c.experiment_id=e.id WHERE e.subject_id=%s GROUP BY e.id ORDER BY e.created_at DESC", (subject["id"],)).fetchall()
        templates_rows = conn.execute("SELECT t.*, e.name AS experiment_name FROM intervention_templates t LEFT JOIN experiments e ON e.id=t.experiment_id WHERE t.subject_id=%s ORDER BY t.is_active DESC,t.name", (subject["id"],)).fetchall()
    return render(
        request,
        "experiments.html",
        experiments=rows,
        templates=templates_rows,
        metabase_dashboard_url=metabase_experiment_dashboard_url(),
    )

@app.post("/experiments")
def create_experiment(name: str = Form(...), hypothesis: str = Form(""), primary_outcome: str = Form(""), starts_on: str = Form(""), ends_on: str = Form(""), status: str = Form("draft"), initial_condition: str = Form("Baseline")):
    with connect() as conn:
        subject = owner(conn)
        experiment = conn.execute("INSERT INTO experiments (subject_id,name,hypothesis,primary_outcome,starts_on,ends_on,status) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id", (subject["id"],name,hypothesis or None,primary_outcome or None,optional_date(starts_on),optional_date(ends_on),status)).fetchone()
        conn.execute("INSERT INTO experiment_conditions (experiment_id,name,kind,starts_on,ends_on) VALUES (%s,%s,'baseline',%s,%s)", (experiment["id"],initial_condition,optional_date(starts_on),optional_date(ends_on)))
        conn.commit()
    return RedirectResponse("/experiments", status_code=303)

@app.post("/experiments/{experiment_id}/conditions")
def create_condition(experiment_id: int, name: str = Form(...), kind: str = Form("intervention"), starts_on: str = Form(""), ends_on: str = Form(""), notes: str = Form("")):
    with connect() as conn:
        subject = owner(conn)
        if not conn.execute("SELECT 1 FROM experiments WHERE id=%s AND subject_id=%s", (experiment_id, subject["id"])).fetchone():
            raise HTTPException(404)
        conn.execute("INSERT INTO experiment_conditions (experiment_id,name,kind,starts_on,ends_on,notes) VALUES (%s,%s,%s,%s,%s,%s)", (experiment_id,name,kind,optional_date(starts_on),optional_date(ends_on),notes or None))
        conn.commit()
    return RedirectResponse("/experiments", status_code=303)

@app.post("/experiments/{experiment_id}/archive")
def archive_experiment(experiment_id: int):
    with connect() as conn:
        subject = owner(conn)
        conn.execute("UPDATE experiments SET status='archived' WHERE id=%s AND subject_id=%s", (experiment_id, subject["id"]))
        conn.commit()
    return RedirectResponse("/experiments", status_code=303)

@app.post("/templates")
def create_template(name: str = Form(...), dose: str = Form(""), unit: str = Form(""), scheduled_times: str = Form(""), active_from: str = Form(""), active_until: str = Form(""), experiment_id: str = Form(""), notes: str = Form("")):
    times = [time.strip() for time in scheduled_times.split(",") if time.strip()]
    with connect() as conn:
        subject = owner(conn)
        conn.execute("INSERT INTO intervention_templates (subject_id,experiment_id,name,dose,unit,scheduled_times,active_from,active_until,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (subject["id"],int(experiment_id) if experiment_id else None,name,dose or None,unit or None,times,optional_date(active_from) or local_now(subject).date(),optional_date(active_until),notes or None))
        conn.commit()
    return RedirectResponse("/experiments", status_code=303)

@app.post("/templates/{template_id}/archive")
def archive_template(template_id: int):
    with connect() as conn:
        subject = owner(conn); conn.execute("UPDATE intervention_templates SET is_active=false WHERE id=%s AND subject_id=%s", (template_id,subject["id"])); conn.commit()
    return RedirectResponse("/experiments", status_code=303)

@app.get("/events/new")
def event_form(request: Request):
    with connect() as conn:
        subject=owner(conn); experiments=conn.execute("SELECT id,name FROM experiments WHERE subject_id=%s AND status!='archived' ORDER BY created_at DESC",(subject["id"],)).fetchall()
    return render(request,"event.html",experiments=experiments)

@app.post("/events")
def create_event(name: str=Form(...), occurred_at: str=Form(...), dose: str=Form(""), unit: str=Form(""), adherence: str=Form("completed"), experiment_id: str=Form(""), notes: str=Form("")):
    with connect() as conn:
        subject=owner(conn)
        moment=datetime.fromisoformat(occurred_at).replace(tzinfo=ZoneInfo(subject["timezone"])).astimezone(timezone.utc)
        conn.execute("INSERT INTO intervention_events (subject_id,experiment_id,name,occurred_at,dose,unit,adherence,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",(subject["id"],int(experiment_id) if experiment_id else None,name,moment,dose or None,unit or None,adherence,notes or None)); conn.commit()
    return RedirectResponse("/",status_code=303)

CONTEXT_CATEGORIES = (("illness", "Illness"), ("travel", "Travel"), ("alcohol", "Alcohol"), ("injury", "Injury"), ("medication", "Medication change"), ("stress", "High stress"), ("other", "Other"))

@app.get("/contexts")
def contexts(request: Request):
    with connect() as conn:
        subject = owner(conn)
        rows = conn.execute("SELECT * FROM context_events WHERE subject_id=%s ORDER BY starts_at DESC LIMIT 100", (subject["id"],)).fetchall()
    return render(request, "contexts.html", contexts=rows, categories=CONTEXT_CATEGORIES, now=local_now(subject))

@app.post("/contexts")
def create_context(category: str=Form(...), label: str=Form(...), starts_at: str=Form(...), ends_at: str=Form(""), notes: str=Form("")):
    allowed = {value for value, _ in CONTEXT_CATEGORIES}
    if category not in allowed:
        raise HTTPException(422, "Unknown context category")
    with connect() as conn:
        subject = owner(conn)
        zone = ZoneInfo(subject["timezone"])
        start = datetime.fromisoformat(starts_at).replace(tzinfo=zone).astimezone(timezone.utc)
        end = datetime.fromisoformat(ends_at).replace(tzinfo=zone).astimezone(timezone.utc) if ends_at else None
        if end and end < start:
            raise HTTPException(422, "End must be after start")
        conn.execute("INSERT INTO context_events (subject_id,category,label,starts_at,ends_at,notes) VALUES (%s,%s,%s,%s,%s,%s)", (subject["id"], category, label, start, end, notes or None))
        conn.commit()
    return RedirectResponse("/contexts", status_code=303)

@app.get("/food")
def food(request: Request):
    with connect() as conn:
        subject=owner(conn); local=local_now(subject); meals=conn.execute("SELECT m.*, COALESCE(sum(f.calories) FILTER (WHERE f.is_confirmed),0) AS calories FROM meal_entries m LEFT JOIN food_items f ON f.meal_id=m.id WHERE m.subject_id=%s AND (m.eaten_at AT TIME ZONE %s)::date=%s GROUP BY m.id ORDER BY m.eaten_at DESC",(subject["id"],subject["timezone"],local.date())).fetchall()
    return render(request,"food.html",now=local,meals=meals)

@app.post("/food/labels")
async def upload_label(label: UploadFile=File(...)):
    suffix=Path(label.filename or "label.jpg").suffix.lower()
    if suffix not in {".jpg",".jpeg",".png",".webp"}: raise HTTPException(400,"Upload a JPG, PNG, or WEBP label image")
    filename=f"{uuid4().hex}{suffix}"; destination=UPLOAD_DIR/filename
    destination.write_bytes(await label.read())
    try: text,draft,confidence=parse_label(destination)
    except Exception:
        destination.unlink(missing_ok=True); raise HTTPException(400,"Could not read that image")
    with connect() as conn:
        subject=owner(conn); image=conn.execute("INSERT INTO food_label_images (subject_id,storage_path,original_filename,ocr_text,parsed_draft,confidence) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",(subject["id"],filename,label.filename or filename,text,Jsonb(draft),confidence)).fetchone(); conn.commit()
    return RedirectResponse(f"/food/labels/{image['id']}/review",status_code=303)

@app.get("/food/labels/{image_id}/review")
def review_label(request: Request,image_id:int):
    with connect() as conn:
        subject=owner(conn); image=conn.execute("SELECT * FROM food_label_images WHERE id=%s AND subject_id=%s",(image_id,subject["id"])).fetchone()
    if not image: raise HTTPException(404)
    return render(request,"label_review.html",image=image,now=datetime.now())

@app.post("/food/items")
def save_food_item(image_id:str=Form(""),name:str=Form(...),eaten_at:str=Form(...),meal_name:str=Form("Meal"),serving_count:str=Form("1"),scale_weight_g:str=Form(""),label_serving_g:str=Form(""),calories:str=Form("0"),protein_g:str=Form("0"),carbohydrates_g:str=Form("0"),fat_g:str=Form("0")):
    with connect() as conn:
        subject=owner(conn); moment=datetime.fromisoformat(eaten_at).replace(tzinfo=ZoneInfo(subject["timezone"])).astimezone(timezone.utc)
        scale_weight = optional_float(scale_weight_g)
        label_weight = optional_float(label_serving_g)
        multiplier = (scale_weight / label_weight) if scale_weight and label_weight else float(serving_count or 1)
        meal=conn.execute("INSERT INTO meal_entries (subject_id,eaten_at,meal_name) VALUES (%s,%s,%s) RETURNING id",(subject["id"],moment,meal_name)).fetchone()
        conn.execute("INSERT INTO food_items (meal_id,label_image_id,name,serving_count,scale_weight_g,calories,protein_g,carbohydrates_g,fat_g,is_confirmed) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",(meal["id"],int(image_id) if image_id else None,name,multiplier,scale_weight,float(calories or 0)*multiplier,float(protein_g or 0)*multiplier,float(carbohydrates_g or 0)*multiplier,float(fat_g or 0)*multiplier)); conn.commit()
    return RedirectResponse("/food",status_code=303)

@app.get("/uploads/{filename}")
def upload_file(filename:str):
    path=UPLOAD_DIR/Path(filename).name
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path)

@app.get("/api/v1/today")
def api_today():
    with connect() as conn:
        subject=owner(conn); now=local_now(subject); nutrition=conn.execute("SELECT * FROM n1_daily_nutrition WHERE subject_id=%s AND day=%s",(subject["id"],now.date())).fetchone()
    return {"date":str(now.date()),"nutrition":nutrition or {}}

@app.post("/api/v1/checkins")
async def api_checkin(request: Request):
    payload=await request.json()
    with connect() as conn:
        subject=owner(conn); checked=date.fromisoformat(payload.get("checkin_date") or str(local_now(subject).date()))
        conn.execute("INSERT INTO daily_checkins(subject_id,checkin_date,weight_kg,energy,mood,stress,sleep_quality,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(subject_id,checkin_date) DO UPDATE SET weight_kg=EXCLUDED.weight_kg,energy=EXCLUDED.energy,mood=EXCLUDED.mood,stress=EXCLUDED.stress,sleep_quality=EXCLUDED.sleep_quality,notes=EXCLUDED.notes,updated_at=now()",(subject["id"],checked,payload.get("weight_kg"),payload.get("energy"),payload.get("mood"),payload.get("stress"),payload.get("sleep_quality"),payload.get("notes"))); conn.commit()
    return {"ok":True}
