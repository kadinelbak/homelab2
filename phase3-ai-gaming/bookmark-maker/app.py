"""Bookmark maker: silhouette (SVG/PNG/JPEG) -> flat clip bookmark STL.

Pipeline: rsvg-convert (SVG only) -> Pillow threshold -> potrace (SVG) -> OpenSCAD -> STL.
The silhouette sits on top of a flat bookmark body and overhangs its sides; the body is
either a paperclip-style clip (U-shaped slot leaving a springy center tongue) or solid.
"""
import io
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageOps

PORT = int(os.environ.get("BOOKMARK_PORT", "8105"))
DATA_DIR = Path(os.environ.get("BOOKMARK_DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
KEEP_DAYS = float(os.environ.get("BOOKMARK_KEEP_DAYS", "7"))
OPENSCAD_TIMEOUT = int(os.environ.get("BOOKMARK_OPENSCAD_TIMEOUT", "120"))
MAX_UPLOAD = 15 * 1024 * 1024
MAX_TRACE_PX = 1200
PAD_PX = 4
JOB_RE = re.compile(r"^[0-9a-f]{12}$")
CHOICES = {"style": ("clip", "solid"), "bottom": ("round", "point")}

# name: (default, min, max), all mm except threshold/invert
PARAMS = {
    "width": (24.0, 12.0, 60.0),  # bookmark body width
    "length": (110.0, 40.0, 250.0),  # bookmark body length, below the art
    "thickness": (1.5, 0.8, 4.0),
    "art_width": (50.0, 15.0, 120.0),  # max silhouette width (may overhang the body)
    "art_height": (60.0, 10.0, 150.0),  # max silhouette height
    "overlap": (6.0, 0.0, 40.0),  # how far the silhouette sinks into the top of the body
    "rail": (3.0, 1.5, 8.0),  # clip: width of the outer frame
    "gap": (3.0, 1.0, 6.0),  # clip: width of the U-shaped slot
    "threshold": (128.0, 1.0, 254.0),
    "invert": (0.0, 0.0, 1.0),
}


def parse_params(query):
    params = {}
    for name, (default, lo, hi) in PARAMS.items():
        try:
            value = float(query.get(name, [default])[0])
        except ValueError:
            value = default
        params[name] = min(max(value, lo), hi)
    for name, options in CHOICES.items():
        value = query.get(name, [options[0]])[0]
        params[name] = value if value in options else options[0]
    return params


def load_image(data, job_dir):
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or b"<svg" in head:
        src = job_dir / "upload.svg"
        src.write_bytes(data)
        png = job_dir / "upload.png"
        subprocess.run(
            ["rsvg-convert", "--width", str(MAX_TRACE_PX), "--keep-aspect-ratio", "-o", str(png), str(src)],
            check=True, capture_output=True, timeout=60,
        )
        data = png.read_bytes()
    return ImageOps.exif_transpose(Image.open(io.BytesIO(data)))


def silhouette_bitmap(img, threshold, invert):
    """Return a 1-bit image where art is black, cropped to the art and padded."""
    img = img.convert("RGBA")
    white = Image.new("RGBA", img.size, (255, 255, 255, 255))
    gray = Image.alpha_composite(white, img).convert("L")
    gray.thumbnail((MAX_TRACE_PX, MAX_TRACE_PX))
    art = gray.point(lambda p: 255 if (p < threshold) != bool(invert) else 0)
    box = art.getbbox()
    if not box:
        raise ValueError("No silhouette found. Try moving the threshold slider or toggling invert.")
    # potrace traces black pixels; pad so shapes touching the edge still close.
    return ImageOps.expand(ImageOps.invert(art.crop(box)), border=PAD_PX, fill=255).convert("1")


def trace(bitmap, job_dir):
    pbm = job_dir / "art.pbm"
    bitmap.save(pbm)
    subprocess.run(
        ["potrace", str(pbm), "-s", "--turdsize", "8", "--alphamax", "1", "-o", str(job_dir / "art.svg")],
        check=True, capture_output=True, timeout=60,
    )


def layout(params, art_w_px, art_h_px):
    scale = min(params["art_width"] / art_w_px, params["art_height"] / art_h_px)
    art_w, art_h = art_w_px * scale, art_h_px * scale
    overlap = min(params["overlap"], art_h * 0.8)
    return {
        "art_w": round(art_w, 3),
        "art_h": round(art_h, 3),
        "art_cy": round(params["length"] - overlap + art_h / 2, 3),
        "total_w": round(max(art_w, params["width"]), 1),
        "total_h": round(params["length"] - overlap + art_h, 1),
    }


def bookmark_scad(params, lay, three_d=True):
    p = {**params, **lay}
    w, length = p["width"], p["length"]
    if p["style"] == "clip" and w - 2 * (p["rail"] + p["gap"]) < 3:
        raise ValueError("Body is too narrow for the clip. Widen it or reduce the rail/gap.")
    # Clip slot stops below the silhouette so the top of the body stays solid.
    slot_top = length - p["overlap"] - p["rail"]
    if p["bottom"] == "round":
        outline = f"hull() {{ translate([0, {w / 2}]) circle(d={w}); translate([-{w / 2}, {w / 2}]) square([{w}, top - {w / 2}]); }}"
    else:
        outline = f"polygon([[-{w / 2}, top], [{w / 2}, top], [{w / 2}, {w * 0.9}], [0, 0], [-{w / 2}, {w * 0.9}]]);"
    clip = (
        f"""difference() {{
      intersection() {{ offset(delta=-{p['rail']}) outline({length}); translate([-{w}, -1]) square([{2 * w}, {slot_top + 1}]); }}
      offset(delta=-{p['rail'] + p['gap']}) outline({length + 100});
    }}"""
        if p["style"] == "clip" else ""
    )
    shape = f"""union() {{
  difference() {{ outline({length}); {clip} }}
  translate([0, {p['art_cy']}]) resize([{p['art_w']}, {p['art_h']}]) import("art.svg", center=true);
}}"""
    body = f"linear_extrude({p['thickness']}) {shape}" if three_d else shape
    return f"""// generated by bookmark-maker
$fn = 64;
module outline(top) {{ {outline} }}
{body}
"""


def openscad(job_dir, scad_name, out_name):
    proc = subprocess.run(
        ["openscad", "-o", out_name, scad_name],
        cwd=job_dir, capture_output=True, text=True, timeout=OPENSCAD_TIMEOUT,
    )
    if proc.returncode != 0 or not (job_dir / out_name).exists():
        raise RuntimeError("OpenSCAD failed: " + proc.stderr.strip()[-800:])


def make_bookmark(data, params):
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    bitmap = silhouette_bitmap(load_image(data, job_dir), params["threshold"], params["invert"])
    trace(bitmap, job_dir)
    lay = layout(params, bitmap.width - 2 * PAD_PX, bitmap.height - 2 * PAD_PX)
    started = time.time()
    (job_dir / "outline.scad").write_text(bookmark_scad(params, lay, three_d=False))
    openscad(job_dir, "outline.scad", "outline.svg")
    (job_dir / "bookmark.scad").write_text(bookmark_scad(params, lay))
    openscad(job_dir, "bookmark.scad", "bookmark.stl")
    result = {
        "id": job_id,
        "preview": f"/jobs/{job_id}/outline.svg",
        "stl": f"/jobs/{job_id}/bookmark.stl",
        "seconds": round(time.time() - started, 1),
        "params": params,
        "layout": lay,
    }
    (job_dir / "job.json").write_text(json.dumps(result, indent=2))
    return result


def cleanup_old_jobs():
    if not JOBS_DIR.exists():
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    for job in JOBS_DIR.iterdir():
        if job.is_dir() and job.stat().st_mtime < cutoff:
            shutil.rmtree(job, ignore_errors=True)


def number_field(name, label, step):
    return f'<div><label for="{name}">{label}</label><input id="{name}" type="number" value="{PARAMS[name][0]:g}" step="{step}"></div>'


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bookmark Maker</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#dcdad5;--accent:#2f6f5e}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--card:#202023;--fg:#ececee;--muted:#9a9aa0;--line:#38383d;--accent:#6cc3a8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px;display:grid;gap:20px;grid-template-columns:minmax(0,1fr) 300px}
@media (max-width:760px){main{grid-template-columns:1fr}}
h1{grid-column:1/-1;margin:0;font-size:22px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
label{display:block;margin:10px 0 4px;color:var(--muted);font-size:13px}
input[type=number],select{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.check{display:flex;gap:8px;align-items:center;margin-top:12px;color:var(--fg)}
input[type=range]{width:100%}
button,a.btn{display:inline-block;margin-top:14px;padding:9px 14px;border:0;border-radius:6px;background:var(--accent);color:#fff;font-weight:600;text-decoration:none;cursor:pointer}
button:disabled{opacity:.5}#msg{color:var(--muted);margin-top:10px;min-height:1.4em}
#preview{display:flex;justify-content:center;align-items:center;min-height:440px}
#preview img{max-height:600px;max-width:100%;background:#fff;border-radius:6px;padding:8px}
</style></head><body><main>
<h1>Bookmark Maker</h1>
<section><div id="preview"><p style="color:var(--muted)">Upload a silhouette (SVG, PNG or JPEG) to start.</p></div></section>
<section>
<label for="file">Silhouette</label><input id="file" type="file" accept=".svg,image/svg+xml,image/png,image/jpeg">
<div class="row"><div><label for="style">Body</label><select id="style"><option value="clip">Paperclip</option><option value="solid">Solid</option></select></div>
<div><label for="bottom">Bottom</label><select id="bottom"><option value="round">Round</option><option value="point">Point</option></select></div></div>
<div class="row">FIELDS_BODY</div>
<div class="row">FIELDS_ART</div>
<div class="row">FIELDS_CLIP</div>
<label for="threshold">Threshold <span id="tv">128</span></label><input id="threshold" type="range" min="1" max="254" value="128">
<label class="check"><input id="invert" type="checkbox"> Invert (light silhouette on dark background)</label>
<button id="go" disabled>Make bookmark</button>
<div id="msg"></div><div id="dl"></div>
</section></main>
<script>
const $=id=>document.getElementById(id);
const fields=["style","bottom","width","length","thickness","art_width","art_height","overlap","rail","gap","threshold"];
$("threshold").oninput=()=>$("tv").textContent=$("threshold").value;
$("file").onchange=()=>{$("go").disabled=!$("file").files.length;};
$("go").onclick=async()=>{
  const q=new URLSearchParams();fields.forEach(f=>q.set(f,$(f).value));q.set("invert",$("invert").checked?1:0);
  $("go").disabled=true;$("msg").textContent="Tracing and building...";$("dl").innerHTML="";
  try{
    const res=await fetch("/api/make?"+q,{method:"POST",body:$("file").files[0]});
    const r=await res.json();if(!res.ok)throw new Error(r.error||res.statusText);
    $("preview").innerHTML=`<img alt="Bookmark outline" src="${r.preview}">`;
    $("msg").textContent=`Done in ${r.seconds}s. Bookmark ${r.layout.total_w} x ${r.layout.total_h} mm.`;
    const name=($("file").files[0].name.replace(/\\.[^.]+$/,"")||"bookmark")+"-bookmark.stl";
    $("dl").innerHTML=`<a class="btn" href="${r.stl}" download="${name}">Download STL</a>`;
  }catch(e){$("msg").textContent=e.message;}
  $("go").disabled=false;
};
</script></body></html>
""".replace("FIELDS_BODY", number_field("width", "Body width mm", 1) + number_field("length", "Body length mm", 5)) \
   .replace("FIELDS_ART", number_field("art_width", "Art width mm", 1) + number_field("art_height", "Max art height mm", 1)) \
   .replace("FIELDS_CLIP", number_field("thickness", "Thickness mm", 0.1) + number_field("overlap", "Art overlap mm", 1)
            + number_field("rail", "Clip rail mm", 0.5) + number_field("gap", "Clip gap mm", 0.5))


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.send(200, PAGE.encode(), "text/html; charset=utf-8")
        if path == "/health":
            ok = all(shutil.which(tool) for tool in ("openscad", "potrace", "rsvg-convert"))
            return self.send_json(200 if ok else 503, {"ok": ok})
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "jobs" and JOB_RE.match(parts[1]):
            ctypes = {
                "outline.svg": "image/svg+xml",
                "art.svg": "image/svg+xml",
                "bookmark.stl": "model/stl",
                "bookmark.scad": "text/plain",
            }
            target = JOBS_DIR / parts[1] / parts[2]
            if parts[2] in ctypes and target.is_file():
                return self.send(200, target.read_bytes(), ctypes[parts[2]])
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/make":
            return self.send_json(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= MAX_UPLOAD:
            return self.send_json(400, {"error": "Upload an SVG, PNG or JPEG up to 15 MB."})
        data = self.rfile.read(size)
        cleanup_old_jobs()
        try:
            result = make_bookmark(data, parse_params(parse_qs(url.query)))
        except (ValueError, OSError) as exc:
            return self.send_json(400, {"error": str(exc)})
        except (RuntimeError, subprocess.SubprocessError) as exc:
            return self.send_json(500, {"error": str(exc)})
        self.send_json(200, result)

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


def main():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"bookmark-maker listening on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
