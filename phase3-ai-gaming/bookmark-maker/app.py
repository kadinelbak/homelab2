"""Bookmark maker: silhouette or photo (SVG/PNG/JPEG) -> multicolor 3MF + STL bookmark.

Pipeline: rsvg-convert (SVG only) -> Pillow bitmap -> potrace -> OpenSCAD (one render per color part,
run in parallel) -> Python assembles STL/3MF. See geometry.py for the shapes and imaging.py for the bitmaps.
"""
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import geometry
import imaging
import threemf

PORT = int(os.environ.get("BOOKMARK_PORT", "8105"))
DATA_DIR = Path(os.environ.get("BOOKMARK_DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
KEEP_DAYS = float(os.environ.get("BOOKMARK_KEEP_DAYS", "7"))
OPENSCAD_TIMEOUT = int(os.environ.get("BOOKMARK_OPENSCAD_TIMEOUT", "120"))
MAX_UPLOAD = 15 * 1024 * 1024
JOB_RE = re.compile(r"^[0-9a-f]{12}$")
FILE_RE = re.compile(r"^[a-z0-9_]+\.(stl|3mf|svg)$")
CTYPES = {".stl": "model/stl", ".3mf": "model/3mf", ".svg": "image/svg+xml"}
PAGE = Path(__file__).with_name("page.html").read_bytes()
CHOICES = {  # first option is the default
    "style": ("clip", "solid", "corner"),
    "bottom": ("round", "point", "swallowtail", "square", "taper"),
    "mode": ("silhouette", "photo"),
    "text_mode": ("raised", "engraved"),
    "font": tuple(geometry.FONTS),
    "pattern": ("none", "honeycomb", "diamonds", "stars", "dots"),
    "photo_fit": ("cover", "contain"),
}

# name: (default, min, max), all mm except threshold/flags/levels
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
    "art_raise": (0.6, 0.0, 2.0),  # silhouette height above the body, 0 = flat
    "border": (1.5, 0.0, 4.0),  # sticker outline around the silhouette
    "corner_r": (2.0, 0.0, 6.0),
    "text_size": (0.0, 0.0, 20.0),  # letter height, 0 = auto-fit
    "text_height": (0.6, 0.2, 2.0),
    "hole": (0.0, 0.0, 1.0),
    "hole_d": (4.0, 3.0, 6.0),
    "cell": (6.0, 4.0, 12.0),
    "peek": (0.0, 0.0, 1.0),
    "peek_split": (0.7, 0.3, 0.9),
    "corner_leg": (55.0, 30.0, 100.0),
    "levels": (3.0, 2.0, 4.0),
    "auto_level": (1.0, 0.0, 1.0),
}


def parse_params(query):
    params = {}
    for name, (default, lo, hi) in PARAMS.items():
        try:
            value = float(query.get(name, [default])[0])
        except ValueError:
            value = default
        params[name] = min(max(value, lo), hi) if value == value else default
    params["levels"] = int(round(params["levels"]))
    for name, options in CHOICES.items():
        value = query.get(name, [options[0]])[0]
        params[name] = value if value in options else options[0]
    for name in ("text1", "text2"):
        params[name] = geometry.clean_text(query.get(name, [""])[0])
    params["colors"] = [c if re.fullmatch(r"[0-9a-fA-F]{6}", c) else "" for c in
                        query.get("colors", [""])[0].lstrip("#").replace("#", "").split(",")][:12]
    return params


def openscad(job_dir, scad_name, out_name):
    proc = subprocess.run(
        ["openscad", "-o", out_name, scad_name],
        cwd=job_dir, capture_output=True, text=True, timeout=OPENSCAD_TIMEOUT,
    )
    if proc.returncode != 0 or not (job_dir / out_name).exists():
        raise RuntimeError("OpenSCAD failed: " + proc.stderr.strip()[-800:])


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def build_plan(params, img, job_dir):
    lines = [t for t in (params["text1"], params["text2"]) if t]
    if params["mode"] == "photo":
        gray, _ = imaging.photo_gray(img, params["width"], params["length"], params["photo_fit"], params["auto_level"])
        levels = []
        for mask in imaging.level_masks(gray, params["levels"]):
            polys, _ = imaging.trace(mask, job_dir, f"level{len(levels) + 1}", turdsize=6, seg=3)
            if polys:
                levels.append(polys)
        if not levels:
            raise ValueError("The photo has no contrast to build levels from. Try a different photo or auto-level.")
        return geometry.plan_photo(params, levels, gray.size, lines)
    mask = imaging.silhouette_mask(img, params["threshold"], params["invert"])
    polys, _ = imaging.trace(mask, job_dir, "art")
    if not polys:
        raise ValueError("No silhouette found. Try moving the threshold slider or toggling invert.")
    if params["style"] == "corner":
        return geometry.plan_corner(params, polys, lines)
    return geometry.plan_standard(params, polys, lines)


def assemble(job_id, job_dir, parts_meta, colors, title="Bookmark"):
    """Write the combined STL and the 3MF from the per-part STLs on disk."""
    parts = []
    for i, meta in enumerate(parts_meta):
        color = colors[i] if i < len(colors) and colors[i] else meta["color"].lstrip("#")
        meta["color"] = "#" + color.lower()
        parts.append({"name": meta["name"], "color": meta["color"], "extruder": meta["extruder"],
                      "verts": threemf.read_stl(job_dir / meta["file"])})
    threemf.write_3mf(job_dir / "bookmark.3mf", parts, title)
    return parts


def make_bookmark(data, params):
    started = time.time()
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    plan = build_plan(params, imaging.load_image(data, job_dir), job_dir)

    # one OpenSCAD render per piece, in parallel
    (job_dir / "common.scad").write_text(plan["common"])
    for name, text in plan["files"].items():
        (job_dir / name).write_text(text)
    art = [n for n in plan["files"] if n == "art.scad"]
    jobs = [("outline", f"include <common.scad>\n{''.join(f'include <{n}>' + chr(10) for n in art)}{plan['outline']}\n", "svg")]
    for part in plan["parts"]:
        for stem, code, includes in part["pieces"]:
            jobs.append((stem, "include <common.scad>\n" + "".join(f"include <{n}>\n" for n in includes) + code + "\n", "stl"))
    for stem, text, _ in jobs:
        (job_dir / f"{stem}.scad").write_text(text)
    with ThreadPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 4)) as pool:
        for fut in [pool.submit(openscad, job_dir, f"{stem}.scad", f"{stem}.{ext}") for stem, _, ext in jobs]:
            fut.result()

    warnings = [{"message": m} for m in plan["warnings"]]
    parts_meta, all_verts = [], []
    for part in plan["parts"]:
        verts = []
        for stem, _, _ in part["pieces"]:
            verts += threemf.read_stl(job_dir / f"{stem}.stl")
        if not verts:
            warnings.append({"message": f"Part {part['name']} came out empty and was skipped."})
            continue
        fname = f"part_{slug(part['name'])}.stl"
        threemf.write_stl(job_dir / fname, verts)
        all_verts += verts
        parts_meta.append({"name": part["name"], "file": fname, "color": part["color"], "extruder": len(parts_meta) + 1,
                           "z0": round(part["z0"], 3), "z1": round(part["z1"], 3)})
    if not parts_meta:
        raise RuntimeError("OpenSCAD produced no geometry.")
    for part in plan["parts"]:
        for stem, _, _ in part["pieces"]:
            (job_dir / f"{stem}.stl").unlink(missing_ok=True)
    threemf.write_stl(job_dir / "bookmark.stl", all_verts)
    assemble(job_id, job_dir, parts_meta, params["colors"])

    if plan["loose"]:
        body_pts, pieces, border = plan["loose"]
        count, suggest = imaging.loose_check(body_pts, pieces, border, geometry.PPM)
        if count > 1:
            msg = f"{count - 1} piece(s) of the silhouette are not connected to the body and would print loose."
            msg += (f" An outline of {suggest} mm connects everything." if suggest is not None
                    else " Even a 4 mm outline cannot connect them; remove stray parts or raise the overlap.")
            warnings.append({"message": msg, "suggested_border": suggest, "kind": "loose"})

    result = {
        "id": job_id,
        "preview": f"/jobs/{job_id}/outline.svg",
        "stl": f"/jobs/{job_id}/bookmark.stl",
        "threemf": f"/jobs/{job_id}/bookmark.3mf",
        "parts": [{**m, "url": f"/jobs/{job_id}/{m['file']}"} for m in parts_meta],
        "print_card": plan["card"],
        "warnings": warnings,
        "seconds": round(time.time() - started, 1),
        "params": params,
        "layout": plan["layout"],
    }
    (job_dir / "job.json").write_text(json.dumps(result, indent=2))
    return result


def recolor(job_id, colors):
    """Rebuild the 3MF of an existing job with new display colors."""
    job_dir = JOBS_DIR / job_id
    info = json.loads((job_dir / "job.json").read_text())
    parts_meta = [{k: m[k] for k in ("name", "file", "color", "extruder")} for m in info["parts"]]
    assemble(job_id, job_dir, parts_meta, colors)
    for meta, old in zip(parts_meta, info["parts"]):
        old["color"] = meta["color"]
    (job_dir / "job.json").write_text(json.dumps(info, indent=2))


def cleanup_old_jobs():
    if not JOBS_DIR.exists():
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    for job in JOBS_DIR.iterdir():
        if job.is_dir() and job.stat().st_mtime < cutoff:
            shutil.rmtree(job, ignore_errors=True)


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
        url = urlparse(self.path)
        path = url.path
        if path == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if path == "/health":
            ok = all(shutil.which(tool) for tool in ("openscad", "potrace", "rsvg-convert"))
            return self.send_json(200 if ok else 503, {"ok": ok})
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "jobs" and JOB_RE.match(parts[1]) and FILE_RE.match(parts[2]):
            target = JOBS_DIR / parts[1] / parts[2]
            if parts[2] == "bookmark.3mf" and "colors" in parse_qs(url.query) and (JOBS_DIR / parts[1] / "job.json").is_file():
                colors = parse_params(parse_qs(url.query))["colors"]
                recolor(parts[1], colors)
            if target.is_file():
                return self.send(200, target.read_bytes(), CTYPES[target.suffix])
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
