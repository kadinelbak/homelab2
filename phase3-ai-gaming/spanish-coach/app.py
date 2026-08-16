import base64
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


APP_NAME = "spanish-coach"
TARGET_LANGUAGE = "Spanish"
DEFAULT_DATABASE_URL = "sqlite:////data/spanish_coach.sqlite3"

DATABASE_URL = os.environ.get("SPANISH_COACH_DATABASE_URL", DEFAULT_DATABASE_URL)
TOKEN = os.environ.get("SPANISH_COACH_TOKEN", "")
LLM_MODEL = os.environ.get("SPANISH_COACH_LLM_MODEL") or os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-3.1-70b-instruct")
LLM_BASE_URL = (os.environ.get("SPANISH_COACH_LLM_BASE_URL") or os.environ.get("JARVIS_FAST_LLM_BASE_URL", "")).rstrip("/")
LLM_API_KEY = os.environ.get("SPANISH_COACH_LLM_API_KEY") or os.environ.get("JARVIS_FAST_LLM_API_KEY", "")
TTS_URL = os.environ.get("SPANISH_COACH_TTS_URL", "http://tts-worker:8101").rstrip("/")
TTS_TOKEN = os.environ.get("SPANISH_COACH_TTS_TOKEN") or os.environ.get("JARVIS_TTS_TOKEN", "")
TTS_VOICE = os.environ.get("SPANISH_COACH_TTS_VOICE") or os.environ.get("JARVIS_TTS_VOICE", "default")
WHISPER_URL = os.environ.get("SPANISH_COACH_WHISPER_URL", "http://whisper-worker:8099").rstrip("/")
WHISPER_TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_language: Mapped[str] = mapped_column(String(32), default="spanish", index=True)
    user_text: Mapped[str] = mapped_column(Text)
    tutor_text: Mapped[str] = mapped_column(Text)
    corrections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    extracted_vocab: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class VocabCard(Base):
    __tablename__ = "vocab_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_language: Mapped[str] = mapped_column(String(32), default="spanish", index=True)
    spanish: Mapped[str] = mapped_column(String(240), index=True)
    english: Mapped[str] = mapped_column(String(240))
    example_sentence: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    difficulty: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    review_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_language: Mapped[str] = mapped_column(String(32), default="spanish", index=True)
    title: Mapped[str] = mapped_column(String(240))
    level: Mapped[str] = mapped_column(String(32), default="beginner")
    topic: Mapped[str] = mapped_column(String(240), default="")
    spanish_text: Mapped[str] = mapped_column(Text)
    english_text: Mapped[str] = mapped_column(Text)
    vocabulary: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    listening_plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


def init_db() -> None:
    if DATABASE_URL.startswith("sqlite"):
        path = DATABASE_URL.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Spanish Coach", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def get_db():
    with SessionLocal() as db:
        yield db


def token_configured() -> bool:
    return bool(TOKEN and not TOKEN.startswith("CHANGE_ME"))


def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not token_configured():
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_json_object(raw: str, fallback: dict[str, Any]) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return fallback
    return fallback


def tutor_prompt(message: str) -> list[dict[str, str]]:
    system = (
        "You are a private Spanish learning coach. The learner's target language is Spanish. "
        "Respond as compact JSON with keys: reply, corrections, next_phrase, vocab. "
        "Keep the tone warm and practical. Use Spanish first, then brief English support. "
        "corrections is an array of objects with original, corrected, explanation. "
        "vocab is an array of objects with spanish, english, example_sentence, tags."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": message}]


def story_prompt(req: "StoryCreate") -> list[dict[str, str]]:
    system = (
        "You generate short Spanish learning stories. The target language is Spanish. "
        "Return compact JSON only with keys title, spanish_text, english_text, vocabulary, questions. "
        "vocabulary is an array of objects with spanish, english, example_sentence, tags. "
        "Write natural beginner-friendly Spanish, not a grammar lecture."
    )
    user = (
        f"Level: {req.level}. Topic: {req.topic or 'daily life'}. Length: {req.length}. "
        f"Tense focus: {req.tense or 'present and practical past'}. "
        f"Required vocab focus: {req.vocab_focus or 'common useful words'}."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def call_llm(messages: list[dict[str, str]]) -> str:
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("llm_not_configured")
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": 0.35}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


def fallback_tutor(message: str) -> dict[str, Any]:
    return {
        "reply": "Vamos a practicar. Dime una frase sencilla en espanol y la mejoramos juntos. In English: say one simple sentence and I will help you polish it.",
        "corrections": [],
        "next_phrase": "Quiero aprender espanol todos los dias.",
        "vocab": [
            {
                "spanish": "aprender",
                "english": "to learn",
                "example_sentence": "Quiero aprender espanol.",
                "tags": ["starter"],
            }
        ],
        "source": "fallback",
        "input": message,
    }


def fallback_story(req: "StoryCreate") -> dict[str, Any]:
    topic = req.topic or "un cafe pequeno"
    return {
        "title": f"Una historia sobre {topic}",
        "spanish_text": "Ana entra en un cafe pequeno. Pide agua y pan. Despues habla con un amigo y sonrie.",
        "english_text": "Ana enters a small cafe. She asks for water and bread. Then she talks with a friend and smiles.",
        "vocabulary": [
            {"spanish": "cafe", "english": "cafe", "example_sentence": "Ana entra en un cafe.", "tags": ["story"]},
            {"spanish": "pide", "english": "asks for", "example_sentence": "Ana pide agua.", "tags": ["story"]},
        ],
        "questions": ["Que pide Ana?", "Con quien habla Ana?"],
        "source": "fallback",
    }


def clean_vocab(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for item in items or []:
        spanish = str(item.get("spanish") or "").strip()
        english = str(item.get("english") or "").strip()
        if not spanish or not english:
            continue
        key = spanish.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        cleaned.append(
            {
                "spanish": spanish,
                "english": english,
                "example_sentence": str(item.get("example_sentence") or ""),
                "tags": [str(tag) for tag in tags[:6]],
            }
        )
    return cleaned


def listening_plan(spanish_text: str, english_text: str) -> dict[str, Any]:
    spanish_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", spanish_text) if s.strip()]
    english_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", english_text) if s.strip()]
    paired = []
    for index, spanish in enumerate(spanish_sentences):
        english = english_sentences[index] if index < len(english_sentences) else ""
        paired.append({"spanish": spanish, "english": english, "sequence": [spanish, english, spanish]})
    return {
        "sentence_loop": paired,
        "full_loop": [spanish_text, english_text, spanish_text],
        "shadowing": [{"spanish": sentence, "pause_seconds": 3} for sentence in spanish_sentences],
    }


def schedule_review(card: VocabCard, rating: str) -> None:
    rating = rating.lower()
    quality = {"again": 1, "hard": 3, "good": 4, "easy": 5}.get(rating)
    if quality is None:
        raise HTTPException(status_code=400, detail="rating must be again, hard, good, or easy")
    previous = {"interval_days": card.interval_days, "difficulty": card.difficulty, "repetitions": card.repetitions}
    if quality < 3:
        card.repetitions = 0
        card.interval_days = 1
        card.lapses += 1
    else:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval_days = 1
        elif card.repetitions == 2:
            card.interval_days = 3 if rating == "hard" else 6
        else:
            multiplier = card.difficulty + (0.3 if rating == "easy" else -0.15 if rating == "hard" else 0)
            card.interval_days = max(1, round(card.interval_days * multiplier))
    card.difficulty = max(1.3, card.difficulty + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    card.due_at = now_utc() + timedelta(days=card.interval_days)
    card.updated_at = now_utc()
    history = list(card.review_history or [])
    history.append({"at": now_utc().isoformat(), "rating": rating, "before": previous, "after": {"interval_days": card.interval_days, "difficulty": card.difficulty, "repetitions": card.repetitions}})
    card.review_history = history


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    save_vocab: bool = True


class VocabCreate(BaseModel):
    spanish: str
    english: str
    example_sentence: str = ""
    tags: list[str] = []


class ReviewRequest(BaseModel):
    rating: str


class TTSRequest(BaseModel):
    text: str | None = None
    segments: list[str] | None = None
    voice: str | None = None
    format: str = "ogg"


class StoryCreate(BaseModel):
    level: str = "beginner"
    topic: str = ""
    length: str = "short"
    tense: str = ""
    vocab_focus: str = ""
    save_vocab: bool = True


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
async def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    checks: dict[str, Any] = {"app": True, "llm_configured": bool(LLM_BASE_URL and LLM_API_KEY)}
    try:
        db.execute(text("select 1"))
        checks["database"] = True
    except Exception as exc:
        checks["database"] = str(exc)
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in {"tts": TTS_URL, "whisper": WHISPER_URL}.items():
            try:
                response = await client.get(f"{url}/health")
                checks[name] = response.status_code < 500
            except Exception as exc:
                checks[name] = str(exc)
    return {"ok": checks.get("database") is True, "service": APP_NAME, "checks": checks}


@app.post("/api/chat", dependencies=[Depends(require_auth)])
async def chat(req: ChatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        raw = await call_llm(tutor_prompt(req.message))
        data = parse_json_object(raw, fallback_tutor(req.message))
    except Exception:
        data = fallback_tutor(req.message)
    vocab = clean_vocab(data.get("vocab"))
    session = PracticeSession(user_text=req.message, tutor_text=str(data.get("reply") or ""), corrections=data.get("corrections") or [], extracted_vocab=vocab)
    db.add(session)
    if req.save_vocab:
        upsert_vocab(db, vocab)
    db.commit()
    return {"id": session.id, "reply": session.tutor_text, "corrections": session.corrections, "next_phrase": data.get("next_phrase", ""), "vocab": vocab}


def upsert_vocab(db: Session, vocab: list[dict[str, Any]]) -> None:
    for item in vocab:
        existing = db.scalar(select(VocabCard).where(VocabCard.spanish.ilike(item["spanish"])))
        if existing:
            tags = sorted(set((existing.tags or []) + item.get("tags", [])))
            existing.tags = tags
            if item.get("example_sentence") and not existing.example_sentence:
                existing.example_sentence = item["example_sentence"]
            existing.updated_at = now_utc()
            continue
        db.add(VocabCard(spanish=item["spanish"], english=item["english"], example_sentence=item.get("example_sentence", ""), tags=item.get("tags", [])))


@app.post("/api/audio/transcribe", dependencies=[Depends(require_auth)])
async def transcribe(file: UploadFile = File(...)) -> dict[str, Any]:
    headers = {}
    if WHISPER_TOKEN and not WHISPER_TOKEN.startswith("CHANGE_ME"):
        headers["Authorization"] = f"Bearer {WHISPER_TOKEN}"
    content = await file.read()
    files = {"file": (file.filename or "audio.webm", content, file.content_type or "application/octet-stream")}
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{WHISPER_URL}/transcribe", headers=headers, files=files, data={"language": "es"})
        response.raise_for_status()
    return response.json()


@app.post("/api/tts", dependencies=[Depends(require_auth)])
async def tts(req: TTSRequest) -> Response:
    segments = req.segments or ([req.text] if req.text else [])
    text_value = "\n\n".join(segment.strip() for segment in segments if segment and segment.strip())
    if not text_value:
        raise HTTPException(status_code=400, detail="text or segments required")
    headers = {}
    if TTS_TOKEN and not TTS_TOKEN.startswith("CHANGE_ME"):
        headers["Authorization"] = f"Bearer {TTS_TOKEN}"
    payload = {"text": text_value, "voice": req.voice or TTS_VOICE, "format": req.format, "max_chars": 0}
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(f"{TTS_URL}/tts/synthesize", headers=headers, json=payload)
        response.raise_for_status()
    return Response(content=response.content, media_type=response.headers.get("content-type", "audio/ogg"))


@app.get("/api/vocab/due", dependencies=[Depends(require_auth)])
def due_vocab(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    cards = db.scalars(select(VocabCard).where(VocabCard.due_at <= now_utc()).order_by(VocabCard.due_at).limit(100)).all()
    return [card_dict(card) for card in cards]


@app.post("/api/vocab", dependencies=[Depends(require_auth)])
def create_vocab(req: VocabCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    item = {"spanish": req.spanish, "english": req.english, "example_sentence": req.example_sentence, "tags": req.tags}
    vocab = clean_vocab([item])
    if not vocab:
        raise HTTPException(status_code=400, detail="spanish and english are required")
    upsert_vocab(db, vocab)
    db.commit()
    card = db.scalar(select(VocabCard).where(VocabCard.spanish.ilike(vocab[0]["spanish"])))
    return card_dict(card)


@app.post("/api/vocab/{card_id}/review", dependencies=[Depends(require_auth)])
def review_vocab(card_id: str, req: ReviewRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    card = db.get(VocabCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    schedule_review(card, req.rating)
    db.commit()
    return card_dict(card)


@app.post("/api/stories", dependencies=[Depends(require_auth)])
async def create_story(req: StoryCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        raw = await call_llm(story_prompt(req))
        data = parse_json_object(raw, fallback_story(req))
    except Exception:
        data = fallback_story(req)
    vocab = clean_vocab(data.get("vocabulary"))
    story = Story(
        title=str(data.get("title") or "Spanish Story"),
        level=req.level,
        topic=req.topic,
        spanish_text=str(data.get("spanish_text") or ""),
        english_text=str(data.get("english_text") or ""),
        vocabulary=vocab,
        questions=[str(q) for q in (data.get("questions") or [])],
        listening_plan=listening_plan(str(data.get("spanish_text") or ""), str(data.get("english_text") or "")),
    )
    db.add(story)
    if req.save_vocab:
        upsert_vocab(db, vocab)
    db.commit()
    return story_dict(story)


@app.get("/api/stories", dependencies=[Depends(require_auth)])
def list_stories(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    stories = db.scalars(select(Story).order_by(Story.created_at.desc()).limit(50)).all()
    return [story_dict(story, include_text=False) for story in stories]


@app.get("/api/stories/{story_id}", dependencies=[Depends(require_auth)])
def get_story(story_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    return story_dict(story)


@app.get("/api/sessions", dependencies=[Depends(require_auth)])
def list_sessions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    sessions = db.scalars(select(PracticeSession).order_by(PracticeSession.created_at.desc()).limit(50)).all()
    return [
        {
            "id": item.id,
            "user_text": item.user_text,
            "tutor_text": item.tutor_text,
            "corrections": item.corrections,
            "extracted_vocab": item.extracted_vocab,
            "created_at": item.created_at.isoformat(),
        }
        for item in sessions
    ]


def card_dict(card: VocabCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "target_language": card.target_language,
        "spanish": card.spanish,
        "english": card.english,
        "example_sentence": card.example_sentence,
        "tags": card.tags or [],
        "difficulty": card.difficulty,
        "interval_days": card.interval_days,
        "repetitions": card.repetitions,
        "lapses": card.lapses,
        "due_at": card.due_at.isoformat(),
    }


def story_dict(story: Story, include_text: bool = True) -> dict[str, Any]:
    data = {
        "id": story.id,
        "target_language": story.target_language,
        "title": story.title,
        "level": story.level,
        "topic": story.topic,
        "vocabulary": story.vocabulary or [],
        "questions": story.questions or [],
        "created_at": story.created_at.isoformat(),
    }
    if include_text:
        data.update({"spanish_text": story.spanish_text, "english_text": story.english_text, "listening_plan": story.listening_plan or {}})
    return data


@app.get("/api/audio/story/{story_id}", dependencies=[Depends(require_auth)])
def story_audio_payload(story_id: str, mode: str = "sentence_loop", db: Session = Depends(get_db)) -> dict[str, Any]:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    plan = story.listening_plan or listening_plan(story.spanish_text, story.english_text)
    if mode == "full_loop":
        segments = plan["full_loop"]
    elif mode == "shadowing":
        segments = [item["spanish"] for item in plan["shadowing"]]
    else:
        segments = [segment for item in plan["sentence_loop"] for segment in item["sequence"] if segment]
    return {"story_id": story.id, "mode": mode, "segments": segments}
