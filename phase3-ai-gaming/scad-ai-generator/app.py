#!/usr/bin/env python3
import base64
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

HOST = os.environ.get("SCAD_AI_HOST", "0.0.0.0")
PORT = int(os.environ.get("SCAD_AI_PORT", "8102"))
DATA_DIR = Path(os.environ.get("SCAD_AI_DATA_DIR", "/data"))
LIBRARY_DIR = DATA_DIR / "library" / "approved"
RESEARCH_DIR = DATA_DIR / "library" / "research"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("SCAD_AI_MODEL", "llama3.1:latest")
OLLAMA_FALLBACK_MODEL = os.environ.get("SCAD_AI_OLLAMA_FALLBACK_MODEL", "llama3.1:latest")
PROMPT_MODEL = os.environ.get("SCAD_AI_PROMPT_MODEL", os.environ.get("JARVIS_DEEP_LLM_MODEL", "nemotron-3-super-120b-a12b"))
ITERATION_MODEL = os.environ.get("SCAD_AI_ITERATION_MODEL", os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-3.1-70b-instruct"))
VISION_MODEL = os.environ.get("SCAD_AI_VISION_MODEL", os.environ.get("JARVIS_VISION_LLM_MODEL", "gemma-4-31b-it"))
VISION_ENABLED = os.environ.get("SCAD_AI_VISION_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
MODEL_OPTIONS = [
    item.strip()
    for item in os.environ.get("SCAD_AI_MODEL_OPTIONS", "gemma-3-27b-it,gemma-4-31b-it,medgemma-27b-it").split(",")
    if item.strip()
]
PROMPT_BASE_URL = os.environ.get("SCAD_AI_PROMPT_BASE_URL", os.environ.get("JARVIS_DEEP_LLM_BASE_URL", "")).rstrip("/")
PROMPT_API_KEY = os.environ.get("SCAD_AI_PROMPT_API_KEY", os.environ.get("JARVIS_DEEP_LLM_API_KEY", ""))
ITERATION_BASE_URL = os.environ.get("SCAD_AI_ITERATION_BASE_URL", os.environ.get("JARVIS_FAST_LLM_BASE_URL", "")).rstrip("/")
ITERATION_API_KEY = os.environ.get("SCAD_AI_ITERATION_API_KEY", os.environ.get("JARVIS_FAST_LLM_API_KEY", ""))
JARVIS_CORE_URL = os.environ.get("JARVIS_CORE_URL", "").rstrip("/")
JARVIS_CORE_TOKEN = os.environ.get("JARVIS_CORE_TOKEN", "")
MAX_ITERATIONS = int(os.environ.get("SCAD_AI_MAX_ITERATIONS", "25"))
OPENSCAD_TIMEOUT = int(os.environ.get("SCAD_AI_OPENSCAD_TIMEOUT", "90"))
OLLAMA_TIMEOUT = int(os.environ.get("SCAD_AI_OLLAMA_TIMEOUT", "180"))
LLM_TIMEOUT = int(os.environ.get("SCAD_AI_LLM_TIMEOUT", os.environ.get("JARVIS_LLM_TIMEOUT_SECONDS", "180")))
CAMERA = os.environ.get("SCAD_AI_CAMERA", "0,0,0,55,0,35,140")
IMG_SIZE = os.environ.get("SCAD_AI_IMG_SIZE", "900,700")
TOKEN = os.environ.get("SCAD_AI_TOKEN", "")

SCAD_BLOCK_RE = re.compile(r"```(?:openscad|scad)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
UNSAFE_RE = re.compile(r"\b(?:include|use|import)\s*[<(]", re.IGNORECASE)
CRITICAL_OPENSCAD_WARNING_RE = re.compile(
    r"(unknown variable|undefined operation|undef|Unable to convert|Mixing 2D and 3D|Ignoring 2D child)",
    re.IGNORECASE,
)


def configured_token():
    if not TOKEN or TOKEN.startswith("CHANGE_ME"):
        return ""
    return TOKEN


def extract_scad(text):
    match = SCAD_BLOCK_RE.search(text or "")
    scad = match.group(1) if match else text or ""
    scad = scad.strip()
    if scad.lower().startswith("openscad"):
        scad = scad.splitlines()[1:]
        scad = "\n".join(scad).strip()
    return scad


def validate_scad(scad):
    if not scad.strip():
        return "SCAD content is empty."
    if len(scad.encode("utf-8")) > 250_000:
        return "SCAD content is too large."
    if UNSAFE_RE.search(scad):
        return "include, use, and import statements are disabled for preview safety."
    return ""


def now_id(prefix):
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def write_json(handler, status, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length > 512 * 1024:
        raise ValueError("request_too_large")
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def authorized(handler):
    token = configured_token()
    if not token:
        return True
    return handler.headers.get("Authorization", "") == f"Bearer {token}"


def run_openscad(scad_path, output_path, render_png=False):
    cmd = ["openscad", "-o", str(output_path), str(scad_path)]
    if render_png:
        cmd = [
            "xvfb-run",
            "-a",
            "openscad",
            "-o",
            str(output_path),
            "--autocenter",
            "--viewall",
            "--camera",
            CAMERA,
            "--projection",
            "ortho",
            "--imgsize",
            IMG_SIZE,
            str(scad_path),
        ]
    started = time.time()
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=OPENSCAD_TIMEOUT,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "stderr": proc.stderr.strip()[-4000:],
        "stdout": proc.stdout.strip()[-1000:],
    }


def run_step_export(cadquery_path):
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(cadquery_path)],
            cwd=str(cadquery_path.parent),
            text=True,
            capture_output=True,
            timeout=OPENSCAD_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "ok": False,
            "returncode": -1,
            "seconds": round(time.time() - started, 2),
            "stderr": str(exc),
            "stdout": "",
        }
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "stderr": proc.stderr.strip()[-4000:],
        "stdout": proc.stdout.strip()[-1000:],
    }


def triangle_metrics(vertices):
    if not vertices:
        return {}
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    triangles = [vertices[i : i + 3] for i in range(0, len(vertices) - 2, 3)]
    area = 0.0
    volume = 0.0
    for a, b, c in triangles:
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        area += 0.5 * (cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) ** 0.5
        volume += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
    bbox_min = [min(xs), min(ys), min(zs)]
    bbox_max = [max(xs), max(ys), max(zs)]
    dims = [bbox_max[i] - bbox_min[i] for i in range(3)]
    return {
        "units": "mm",
        "triangle_count": len(triangles),
        "bbox_min_mm": [round(v, 3) for v in bbox_min],
        "bbox_max_mm": [round(v, 3) for v in bbox_max],
        "dimensions_mm": {"x": round(dims[0], 3), "y": round(dims[1], 3), "z": round(dims[2], 3)},
        "dimensions_in": {"x": round(dims[0] / 25.4, 3), "y": round(dims[1] / 25.4, 3), "z": round(dims[2] / 25.4, 3)},
        "surface_area_mm2": round(area, 3),
        "volume_mm3": round(abs(volume), 3),
    }


def stl_metrics(stl_path):
    data = Path(stl_path).read_bytes()
    vertices = []
    if len(data) >= 84:
        tri_count = struct.unpack("<I", data[80:84])[0]
        expected = 84 + tri_count * 50
        if expected == len(data):
            offset = 84
            for _ in range(tri_count):
                offset += 12
                for _ in range(3):
                    vertices.append(struct.unpack("<fff", data[offset : offset + 12]))
                    offset += 12
                offset += 2
            return triangle_metrics(vertices)
    text = data.decode("utf-8", errors="ignore")
    for match in re.finditer(r"\bvertex\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)", text):
        try:
            vertices.append(tuple(float(match.group(i)) for i in range(1, 4)))
        except ValueError:
            continue
    return triangle_metrics(vertices)


def basic_engineering_checks(scad, result, source=""):
    metrics = result.get("metrics") or {}
    dims = metrics.get("dimensions_mm") or {}
    scad_lower = (scad or "").lower()
    source_lower = (source or "").lower()
    checks = []
    def add(name, ok, message):
        checks.append({"name": name, "ok": bool(ok), "message": message})

    add("Bounding box dimensions", bool(dims), f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} mm" if dims else "No STL metrics available.")
    add("Manifold/export success", bool(result.get("ok") and result.get("export", {}).get("ok")), "STL export completed." if result.get("ok") else result.get("error", "Export failed."))
    hole_mentions = len(re.findall(r"\bcylinder\s*\(\s*r\s*=\s*hole_r|\bhole_r\b|hole_diameter", scad_lower))
    add("Hole feature hints", hole_mentions > 0, f"{hole_mentions} hole-related SCAD hints found." if hole_mentions else "No obvious hole parameters found.")
    thickness_values = [float(item) for item in re.findall(r"(?:thickness|wall)\s*=\s*([0-9]+(?:\.[0-9]+)?)", scad_lower)]
    min_wall = min(thickness_values) if thickness_values else None
    add("Minimum wall thickness", min_wall is None or min_wall >= 2.0, f"Minimum detected wall/thickness is {min_wall} mm." if min_wall is not None else "No explicit wall thickness parameter found.")
    if "l-bracket" in source_lower or is_l_bracket_prompt(scad_lower):
        perpendicular = "rotate([-90" in scad_lower or "rotate([90" in scad_lower or "rotate([0, 90" in scad_lower
        two_face_holes = "countersunk_hole_z" in scad_lower and "countersunk_hole_y" in scad_lower
        add("L-bracket perpendicular faces", perpendicular, "Rotation for perpendicular flange detected." if perpendicular else "No clear perpendicular flange rotation detected.")
        add("L-bracket holes on both faces", two_face_holes, "Separate horizontal and vertical hole modules detected." if two_face_holes else "Could not confirm holes on both faces.")
    if "u-bracket" in source_lower or "u bracket" in source_lower or "u bracket channel" in scad_lower:
        has_base = "cube([width, depth, wall])" in scad_lower or "base" in scad_lower
        has_side_walls = scad_lower.count("cube([wall, depth, height])") >= 1 and "width - wall" in scad_lower
        add("U-bracket base and side walls", has_base and has_side_walls, "Base and paired side wall pattern detected." if has_base and has_side_walls else "Could not confirm U-channel base plus two side walls.")
    if "spacer" in source_lower or "standoff" in source_lower or "spacer bushing" in scad_lower or "hex electronics standoff" in scad_lower:
        through_hole = "difference()" in scad_lower and "height + 2" in scad_lower and "hole_r" in scad_lower
        add("Spacer/standoff through-hole", through_hole, "Central through-hole pattern detected." if through_hole else "Could not confirm a through-hole through the spacer body.")
    if "mounting plate" in source_lower or "flat rounded mounting plate" in scad_lower:
        flat_plate = bool(dims and dims.get("z", 999) <= max(8, min(dims.get("x", 0), dims.get("y", 0)) * 0.35))
        add("Flat plate proportions", flat_plate, "Thin rectangular plate proportions detected." if flat_plate else "Bounding box does not look like a thin plate.")
    hole_diams = [float(item) for item in re.findall(r"(?:hole_diameter|hole_d)\s*=\s*([0-9]+(?:\.[0-9]+)?)", scad_lower)]
    if hole_diams:
        add("Hole diameter range", all(1.0 <= value <= 20.0 for value in hole_diams), f"Detected hole diameter(s): {', '.join(str(value) for value in hole_diams)} mm.")
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def render_artifacts(scad, work_dir, render_preview=True, cadquery_source=""):
    scad_error = validate_scad(scad)
    work_dir.mkdir(parents=True, exist_ok=True)
    scad_path = work_dir / "model.scad"
    png_path = work_dir / "preview.png"
    stl_path = work_dir / "model.stl"
    csg_path = work_dir / "model.csg"
    three_mf_path = work_dir / "model.3mf"
    cadquery_path = work_dir / "model.py"
    step_path = work_dir / "model.step"
    scad_path.write_text(scad, encoding="utf-8")
    if cadquery_source:
        cadquery_path.write_text(cadquery_source, encoding="utf-8")
    if scad_error:
        return {
            "ok": False,
            "error": scad_error,
            "scad": artifact_url(scad_path),
            "cadquery": artifact_url(cadquery_path) if cadquery_path.exists() else "",
        }
    def fail_on_critical_warning(step, label):
        if step["ok"] and CRITICAL_OPENSCAD_WARNING_RE.search(step.get("stderr", "")):
            step["ok"] = False
            step["stderr"] = f"Critical OpenSCAD warning treated as failed {label}:\n" + step.get("stderr", "")
        return step

    csg = fail_on_critical_warning(run_openscad(scad_path, csg_path), "compile")
    png = run_openscad(scad_path, png_path, render_png=True) if csg["ok"] and render_preview else {"ok": True, "skipped": True}
    png = fail_on_critical_warning(png, "render")
    stl = run_openscad(scad_path, stl_path) if csg["ok"] and png["ok"] and render_preview else {"ok": True, "skipped": True}
    stl = fail_on_critical_warning(stl, "export")
    three_mf = run_openscad(scad_path, three_mf_path) if csg["ok"] and png["ok"] and render_preview else {"ok": True, "skipped": True}
    three_mf = fail_on_critical_warning(three_mf, "3mf export")
    step = run_step_export(cadquery_path) if cadquery_path.exists() and csg["ok"] and render_preview else {"ok": None, "skipped": True}
    ok = csg["ok"] and png["ok"] and stl["ok"] and three_mf["ok"]
    metrics = {}
    metrics_path = work_dir / "metrics.json"
    if ok and stl_path.exists():
        metrics = stl_metrics(stl_path)
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    result = {
        "ok": ok,
        "compile": csg,
        "render": png,
        "export": stl,
        "export_3mf": three_mf,
        "export_step": step,
        "metrics": metrics,
        "metrics_url": artifact_url(metrics_path) if metrics_path.exists() else "",
        "scad": artifact_url(scad_path),
        "cadquery": artifact_url(cadquery_path) if cadquery_path.exists() else "",
        "step": artifact_url(step_path) if step_path.exists() else "",
        "csg": artifact_url(csg_path) if csg_path.exists() else "",
        "three_mf": artifact_url(three_mf_path) if three_mf_path.exists() else "",
        "preview": artifact_url(png_path) if png_path.exists() else "",
        "stl": artifact_url(stl_path) if stl_path.exists() else "",
        "error": "" if ok else (csg.get("stderr") or png.get("stderr") or stl.get("stderr") or three_mf.get("stderr") or "OpenSCAD failed"),
    }
    checks = basic_engineering_checks(scad, result)
    checks_path = work_dir / "engineering_checks.json"
    try:
        checks_path.write_text(json.dumps(checks, indent=2), encoding="utf-8")
        result["engineering_checks"] = checks
        result["engineering_checks_url"] = artifact_url(checks_path)
    except OSError:
        result["engineering_checks"] = checks
    return result


def data_dir_writable():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def artifact_url(path):
    try:
        rel = path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        return ""
    return "/artifacts/" + "/".join(rel.parts)


def artifact_path_from_url(url, allowed_suffixes):
    parsed = urlparse(str(url or ""))
    path = parsed.path
    if not path.startswith("/artifacts/"):
        return None
    rel = unquote(path[len("/artifacts/") :])
    target = (DATA_DIR / rel).resolve()
    if not str(target).startswith(str(DATA_DIR.resolve())) or not target.is_file():
        return None
    if target.suffix.lower() not in allowed_suffixes:
        return None
    return target


def version_manifest_path_for_artifact(url):
    target = artifact_path_from_url(url, {".scad", ".stl", ".step", ".3mf", ".png", ".json", ".py", ".csg"})
    if not target:
        return None
    manifest = target.parent / "version.json"
    return manifest if manifest.exists() else None


def read_version_manifest(url):
    manifest = version_manifest_path_for_artifact(url)
    if not manifest:
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_project_title(scad_url, title):
    title = (title or "").strip()[:120]
    if not title:
        raise ValueError("missing_title")
    manifest = version_manifest_path_for_artifact(scad_url)
    if manifest:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["title"] = title
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    scad_path = artifact_path_from_url(scad_url, {".scad"})
    if not scad_path:
        raise ValueError("invalid_scad_url")
    library_json = scad_path.parent / "library.json"
    if library_json.exists():
        data = json.loads(library_json.read_text(encoding="utf-8"))
        data["title"] = title
        library_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    raise ValueError("metadata_not_found")


def archive_project(scad_url):
    scad_path = artifact_path_from_url(scad_url, {".scad"})
    if not scad_path:
        raise ValueError("invalid_scad_url")
    project_dir = scad_path.parent
    deleted_root = DATA_DIR / "deleted"
    deleted_root.mkdir(parents=True, exist_ok=True)
    target = deleted_root / f"{now_id('deleted')}-{project_dir.name}"
    shutil.move(str(project_dir), str(target))
    return {"deleted_path": str(target), "title": project_dir.name}


def write_version_manifest(work_dir, title, kind, result, source="", parent_scad="", request="", notes=""):
    parent = read_version_manifest(parent_scad) if parent_scad else {}
    root_scad = parent.get("root_scad") or parent.get("scad") or parent_scad or result.get("scad", "")
    manifest = {
        "version_id": work_dir.name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        "title": title,
        "parent_scad": parent_scad,
        "root_scad": root_scad,
        "source": source,
        "request": request,
        "notes": notes,
        "ok": bool(result.get("ok")),
        "metrics": result.get("metrics") or {},
        "engineering_checks": result.get("engineering_checks") or {},
        "engineering_checks_url": result.get("engineering_checks_url", ""),
        "scad": result.get("scad", ""),
        "stl": result.get("stl", ""),
        "step": result.get("step", ""),
        "cadquery": result.get("cadquery", ""),
        "three_mf": result.get("three_mf", ""),
        "preview": result.get("preview", ""),
        "metrics_url": result.get("metrics_url", ""),
    }
    try:
        (work_dir / "version.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        pass
    result["version"] = manifest
    return manifest


def synthetic_manifest_for_scad(scad_url, title="Existing version"):
    scad_path = artifact_path_from_url(scad_url, {".scad"})
    if not scad_path:
        return {}
    work_dir = scad_path.parent
    def maybe(name):
        path = work_dir / name
        return artifact_url(path) if path.exists() else ""
    metrics = {}
    metrics_path = work_dir / "metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metrics = {}
    return {
        "version_id": work_dir.name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(work_dir.stat().st_mtime)),
        "kind": "existing",
        "title": title,
        "parent_scad": "",
        "root_scad": scad_url,
        "source": "existing-artifact",
        "request": "",
        "notes": "",
        "ok": True,
        "metrics": metrics,
        "scad": scad_url,
        "stl": maybe("model.stl"),
        "step": maybe("model.step"),
        "cadquery": maybe("model.py"),
        "three_mf": maybe("model.3mf"),
        "preview": maybe("preview.png"),
        "metrics_url": maybe("metrics.json"),
        "engineering_checks": {},
        "engineering_checks_url": maybe("engineering_checks.json"),
    }


def version_manifests_for_root(scad_url):
    current = read_version_manifest(scad_url)
    root_scad = current.get("root_scad") or current.get("scad") or scad_url
    manifests = []
    roots = [
        DATA_DIR / "runs",
        DATA_DIR / "revisions",
    ]
    for root in roots:
        if not root.exists():
            continue
        try:
            candidates = root.glob("*/iteration-*/version.json") if root.name == "runs" else root.glob("*/version.json")
            for manifest_path in candidates:
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if manifest.get("root_scad") == root_scad or manifest.get("scad") == root_scad:
                    manifests.append(manifest)
        except OSError:
            continue
    if root_scad and not any(item.get("scad") == root_scad for item in manifests):
        synthetic = synthetic_manifest_for_scad(root_scad, "Original")
        if synthetic:
            manifests.insert(0, synthetic)
    manifests.sort(key=lambda item: item.get("created_at", ""))
    return manifests, root_scad


def all_version_manifests():
    manifests = []
    for root in (DATA_DIR / "runs", DATA_DIR / "revisions", DATA_DIR / "previews"):
        if not root.exists():
            continue
        patterns = ["*/iteration-*/version.json", "*/version.json"] if root.name == "runs" else ["*/version.json"]
        for pattern in patterns:
            for path in root.glob(pattern):
                try:
                    manifests.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
    manifests.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return manifests


def artifact_matches_query(item, query="", component_type="", fastener="", source=""):
    haystack = " ".join(str(item.get(key, "")) for key in ("title", "source", "request", "notes", "kind", "library_id", "template_id", "component_type", "family", "fastener"))
    if query and query.lower() not in haystack.lower():
        return False
    if component_type and component_type.lower() not in haystack.lower():
        return False
    if fastener and fastener.lower() not in haystack.lower():
        return False
    if source and source.lower() not in haystack.lower():
        return False
    return True


def project_library(query="", component_type="", fastener="", source="", limit=80):
    approved = [
        {**item, "bucket": "approved_templates"}
        for item in read_library_items()
        if artifact_matches_query(item, query, component_type, fastener, source)
    ]
    versions = all_version_manifests()
    generated = [
        {**item, "bucket": "generated_projects"}
        for item in versions
        if item.get("kind") == "iteration" and artifact_matches_query(item, query, component_type, fastener, source)
    ]
    revisions = [
        {**item, "bucket": "revisions"}
        for item in versions
        if item.get("kind") == "revision" and artifact_matches_query(item, query, component_type, fastener, source)
    ]
    research = review_queue_items(query=query, source=source)
    return {
        "approved_templates": approved[:limit],
        "generated_projects": generated[:limit],
        "revisions": revisions[:limit],
        "imported_researched_templates": research[:limit],
    }


def next_revision_title(parent_scad, fallback_title="Revision"):
    versions, _ = version_manifests_for_root(parent_scad)
    revision_count = sum(1 for item in versions if item.get("kind") == "revision")
    return f"Revision {revision_count + 1}"


def words(text):
    return {word for word in re.findall(r"[a-z0-9]{3,}", (text or "").lower())}


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:48] or "approved-model"


FASTENER_VARIANTS = {
    "m3": {"label": "M3", "hole_r": 1.7},
    "m4": {"label": "M4", "hole_r": 2.25},
    "m5": {"label": "M5", "hole_r": 2.75},
}

SIZE_VARIANTS = {
    "compact": {"label": "Compact", "scale": 0.8},
    "standard": {"label": "Standard", "scale": 1.0},
    "heavy": {"label": "Heavy duty", "scale": 1.25},
}

TEMPLATE_FAMILIES = [
    {
        "family": "l-bracket",
        "component_type": "brackets",
        "generator": "l-bracket",
        "title": "L bracket",
        "description": "Two perpendicular flanges, two clearance holes per face, optional internal gussets.",
        "tags": "l bracket angle bracket corner bracket flange 90 degree mounting",
    },
    {
        "family": "u-bracket",
        "component_type": "brackets",
        "generator": "u-bracket",
        "title": "U bracket channel",
        "description": "U-shaped mounting channel with side holes and a flat base.",
        "tags": "u bracket channel saddle mount fork bracket side holes clevis",
    },
    {
        "family": "flat-mounting-plate",
        "component_type": "plates",
        "generator": "flat-mounting-plate",
        "title": "Flat mounting plate",
        "description": "Rectangular plate with rounded corners and configurable screw holes.",
        "tags": "mounting plate adapter plate flat bracket panel holes",
    },
    {
        "family": "spacer-bushing",
        "component_type": "spacers",
        "generator": "spacer-bushing",
        "title": "Spacer bushing",
        "description": "Cylindrical spacer with central through-hole and optional chamfers.",
        "tags": "spacer bushing washer sleeve round cylinder through hole",
    },
    {
        "family": "hex-standoff",
        "component_type": "spacers",
        "generator": "hex-standoff",
        "title": "Hex standoff",
        "description": "Hexagonal electronics standoff with axial screw clearance.",
        "tags": "standoff pcb electronics spacer hex screw post",
    },
    {
        "family": "cable-clip",
        "component_type": "clips-clamps",
        "generator": "cable-clip",
        "title": "Cable clip with screw tab",
        "description": "Open cable saddle clip with screw tab, rounded strap, and printable clearances.",
        "tags": "cable clip wire clamp hose clip screw tab mount holder",
    },
]


def build_builtin_templates():
    items = []
    for family in TEMPLATE_FAMILIES:
        for size_key, size in SIZE_VARIANTS.items():
            for fastener_key, fastener in FASTENER_VARIANTS.items():
                template_id = f"{family['family']}-{size_key}-{fastener_key}"
                items.append(
                    {
                        "template_id": template_id,
                        "component_type": family["component_type"],
                        "family": family["family"],
                        "generator": family["generator"],
                        "variant": size_key,
                        "variant_label": size["label"],
                        "scale": size["scale"],
                        "fastener": fastener_key,
                        "hole_r": fastener["hole_r"],
                        "title": f"{size['label']} {family['title']} - {fastener['label']}",
                        "description": family["description"],
                        "tags": f"{family['tags']} {fastener_key} {fastener['label']} {size_key} {size['label']}",
                        "license": "local-generated-template",
                    }
                )
    return items


BUILTIN_TEMPLATES = build_builtin_templates()


def builtin_template_items():
    return [
        {
            "library_id": item["template_id"],
            "template_id": item["template_id"],
            "kind": "builtin_template",
            "approved_at": "builtin",
            "score": 0,
            "source": "builtin-parametric-template",
            **item,
        }
        for item in BUILTIN_TEMPLATES
    ]


def read_library_items():
    items = []
    if not LIBRARY_DIR.exists():
        return items
    for path in LIBRARY_DIR.glob("*/library.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(item)
    items.sort(key=lambda item: item.get("approved_at", ""), reverse=True)
    return items


def score_library_item(item, query):
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("title", "description", "tags", "source", "license", "notes", "template_id", "component_type", "family", "fastener", "variant")
    )
    query_words = words(query)
    if not query_words:
        return 0
    hay_words = words(haystack)
    score = len(query_words & hay_words)
    if query.lower() in haystack.lower():
        score += 4
    return score


def search_builtin_templates(query, limit=8):
    scored = []
    for item in builtin_template_items():
        score = score_library_item(item, query)
        if score > 0:
            candidate = dict(item)
            candidate["score"] = score + 2
            scored.append(candidate)
    scored.sort(key=lambda item: item.get("score", 0), reverse=True)
    return scored[:limit]


def search_library(query, limit=8):
    scored = []
    for item in read_library_items():
        score = score_library_item(item, query)
        if score > 0:
            candidate = dict(item)
            candidate["score"] = score
            scored.append(candidate)
    scored.sort(key=lambda item: (item.get("score", 0), item.get("approved_at", "")), reverse=True)
    return scored[:limit]


def search_all_templates(query, limit=12):
    results = search_library(query, limit=limit) + search_builtin_templates(query, limit=limit)
    results.sort(key=lambda item: (item.get("score", 0), item.get("approved_at", "")), reverse=True)
    return results[:limit]


def grouped_builtin_templates():
    grouped = {}
    for item in builtin_template_items():
        component_type = item.get("component_type") or "misc"
        grouped.setdefault(component_type, []).append(item)
    for items in grouped.values():
        items.sort(key=lambda item: (item.get("family", ""), item.get("variant", ""), item.get("fastener", "")))
    return dict(sorted(grouped.items()))


def save_approved_version(scad_url, title, notes="", tags="", source_url="", license_name=""):
    manifest = read_version_manifest(scad_url)
    scad_path = artifact_path_from_url(scad_url, {".scad"})
    if not scad_path:
        raise ValueError("invalid_scad_url")
    title = (title or manifest.get("title") or scad_path.parent.name).strip()[:120]
    digest = hashlib.sha256((scad_url + title + str(time.time())).encode("utf-8")).hexdigest()[:10]
    item_dir = LIBRARY_DIR / f"{slugify(title)}-{digest}"
    item_dir.mkdir(parents=True, exist_ok=True)
    artifact_keys = ["scad", "stl", "step", "cadquery", "three_mf", "preview", "metrics_url"]
    copied = {}
    source_data = manifest or {"scad": scad_url}
    for key in artifact_keys:
        url = source_data.get(key) or (scad_url if key == "scad" else "")
        src = artifact_path_from_url(url, {".scad", ".stl", ".step", ".stp", ".py", ".3mf", ".png", ".json"})
        if not src:
            continue
        dst = item_dir / src.name
        try:
            shutil.copy2(src, dst)
            copied[key] = artifact_url(dst)
        except OSError:
            continue
    item = {
        "library_id": item_dir.name,
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title": title,
        "description": notes[:1000],
        "notes": notes[:3000],
        "tags": tags[:500],
        "source_url": source_url[:500],
        "license": license_name[:120],
        "origin_version": manifest,
        "metrics": source_data.get("metrics") or {},
        **copied,
    }
    (item_dir / "library.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    return item


def github_scad_research(query, limit=8):
    def gh_get(url):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "homelab-scad-ai-generator",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8"))

    search = quote(f"{query} OpenSCAD scad filename:.scad")
    url = f"https://api.github.com/search/code?q={search}&per_page={min(limit, 10)}"
    source = "github-code-search"
    try:
        data = gh_get(url)
        raw_items = data.get("items", [])[:limit]
    except urllib.error.HTTPError:
        repo_search = quote(f"{query} openscad scad")
        data = gh_get(f"https://api.github.com/search/repositories?q={repo_search}&per_page={min(limit, 10)}")
        source = "github-repository-search"
        raw_items = data.get("items", [])[:limit]
    candidates = []
    for item in raw_items:
        if source == "github-code-search":
            repo = item.get("repository") or {}
            candidates.append(
                {
                    "name": item.get("name", ""),
                    "path": item.get("path", ""),
                    "html_url": item.get("html_url", ""),
                    "repository": repo.get("full_name", ""),
                    "repository_url": repo.get("html_url", ""),
                    "license": "unknown",
                    "source": source,
                    "note": "Review license and compile/render before approving.",
                }
            )
        else:
            license_info = item.get("license") or {}
            candidates.append(
                {
                    "name": item.get("name", ""),
                    "path": "",
                    "html_url": item.get("html_url", ""),
                    "repository": item.get("full_name", ""),
                    "repository_url": item.get("html_url", ""),
                    "license": license_info.get("spdx_id") or "unknown",
                    "source": source,
                    "note": "Repository-level candidate. Inspect files for SCAD source before adapting.",
                }
            )
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    research_path = RESEARCH_DIR / f"{now_id('research')}.json"
    research_path.write_text(json.dumps({"query": query, "source": source, "candidates": candidates}, indent=2), encoding="utf-8")
    return candidates, artifact_url(research_path)


def review_queue_items(query="", source="", limit=120):
    items = []
    if not RESEARCH_DIR.exists():
        return items
    for path in RESEARCH_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for index, candidate in enumerate(data.get("candidates", []), start=1):
            item = {
                "review_id": f"{path.stem}-{index}",
                "bucket": "imported_researched_templates",
                "query": data.get("query", ""),
                "research_file": artifact_url(path),
                "compile_status": "not_imported",
                "preview_status": "not_rendered",
                "license": candidate.get("license", "unknown"),
                **candidate,
            }
            haystack = " ".join(str(item.get(key, "")) for key in ("name", "path", "repository", "html_url", "license", "query", "source"))
            if query and query.lower() not in haystack.lower():
                continue
            if source and source.lower() not in haystack.lower():
                continue
            items.append(item)
    return items[:limit]


def bundle_for_artifact(scad_url):
    manifest = read_version_manifest(scad_url) or synthetic_manifest_for_scad(scad_url, "Bundle")
    scad_path = artifact_path_from_url(scad_url, {".scad"})
    if not scad_path:
        return None
    bundle_path = scad_path.parent / "bundle.zip"
    keys = ["scad", "stl", "step", "cadquery", "three_mf", "preview", "metrics_url", "engineering_checks_url"]
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for key in keys:
            url = manifest.get(key) or (scad_url if key == "scad" else "")
            path = artifact_path_from_url(url, {".scad", ".stl", ".step", ".stp", ".py", ".3mf", ".png", ".json", ".csg"})
            if path and path.exists():
                zf.write(path, path.name)
    return bundle_path


def openai_chat(base_url, api_key, model, messages, temperature):
    url = base_url
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"
        if not url.endswith("/v1/chat/completions") and "/v1/" not in url:
            url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def jarvis_core_generate(profile, prompt, system, temperature, max_tokens, images=None, model=None):
    headers = {"Content-Type": "application/json"}
    if JARVIS_CORE_TOKEN:
        headers["Authorization"] = f"Bearer {JARVIS_CORE_TOKEN}"
    body = {
        "profile": profile,
        "model": model,
        "purpose": "scad_ai_generation",
        "prompt": prompt,
        "system": system,
        "images": images or [],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"{JARVIS_CORE_URL}/api/v1/models/generate",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")[:1000]
        raise RuntimeError(f"Jarvis Core model call failed: HTTP {exc.code} {detail}") from exc
    return data.get("content", ""), data.get("model", profile)


def image_data_uri(path):
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def jarvis_core_profiles():
    if not JARVIS_CORE_URL or not JARVIS_CORE_TOKEN:
        return {}
    headers = {"Authorization": f"Bearer {JARVIS_CORE_TOKEN}"}
    req = urllib.request.Request(f"{JARVIS_CORE_URL}/api/v1/models/health", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return (json.loads(res.read().decode("utf-8")).get("profiles") or {})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}


def jarvis_profile_ready(profile):
    status = jarvis_core_profiles().get(profile) or {}
    return bool(status.get("configured"))


def ollama_complete(model, prompt, temperature):
    body = {
        "model": model,
        "stream": False,
        "options": {"temperature": temperature},
        "prompt": prompt,
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data.get("response", "")


def model_complete(role, model, prompt, temperature):
    if JARVIS_CORE_URL and JARVIS_CORE_TOKEN:
        profile = "deep" if role == "prompt" else "fast"
        if jarvis_profile_ready(profile):
            system = "You are an expert OpenSCAD CAD assistant. Follow the user's output format exactly."
            max_tokens = 1200 if role == "prompt" else 3800
            text, actual_model = jarvis_core_generate(profile, prompt, system, temperature, max_tokens, model=model)
            return text, f"jarvis-core:{profile}:{actual_model}"
    if role == "prompt" and PROMPT_BASE_URL:
        text = openai_chat(PROMPT_BASE_URL, PROMPT_API_KEY, model, [{"role": "user", "content": prompt}], temperature)
        return text, "openai-compatible"
    if role == "iteration" and ITERATION_BASE_URL:
        text = openai_chat(ITERATION_BASE_URL, ITERATION_API_KEY, model, [{"role": "user", "content": prompt}], temperature)
        return text, "openai-compatible"
    ollama_model = model if ":" in model else OLLAMA_FALLBACK_MODEL
    return ollama_complete(ollama_model, prompt, temperature), f"ollama:{ollama_model}"


def refine_prompt(user_prompt, model, temperature):
    prompt = f"""You are a senior mechanical CAD prompt engineer for OpenSCAD.
Rewrite the user's rough idea into a precise generation brief that will produce useful parametric OpenSCAD iterations.

Keep it concise but complete. Include:
- intended object and use case
- key geometric features
- named parameters that should appear near the top of the SCAD file
- printability constraints
- variation strategy for multiple iterations
- preview expectations

User idea:
{user_prompt}
"""
    text, source = model_complete("prompt", model, prompt, min(temperature, 0.7))
    return text.strip(), source


def generate_scad(model, refined_prompt, iteration, total_iterations, temperature):
    system = (
        "You write valid OpenSCAD only. Return a single fenced scad code block. "
        "Do not use include, use, import, file IO, external assets, or explanations. "
        "Make the model parametric with named variables near the top. "
        "Use only built-in OpenSCAD primitives and modules. Produce printable solid geometry. "
        "For brackets and fixtures, preserve functional relationships: dimensions, perpendicular faces, hole placement, wall thickness, and printability matter more than decoration. "
        "For an L bracket, model two flat rectangular legs meeting at a clean 90 degree inside corner. "
        "If gussets or ribs are requested, place them as small triangular webs inside the internal corner only; they must not sit on top of the horizontal leg like fins, and they must not block screw holes. "
        "If the brief does not require gussets, do not add them."
    )
    prompt = (
        f"{system}\n\nRefined CAD brief:\n{refined_prompt}\n\n"
        f"Create iteration {iteration} of {total_iterations}. Make it meaningfully distinct but faithful to the brief."
    )
    text, source = model_complete("iteration", model, prompt, temperature)
    return extract_scad(text), source


def repair_scad(model, refined_prompt, broken_scad, error, temperature):
    prompt = f"""Repair this OpenSCAD so it compiles and still matches the CAD brief.
Return one fenced scad code block only. Do not explain.

CAD brief:
{refined_prompt}

OpenSCAD error:
{error}

Broken SCAD:
```scad
{broken_scad}
```
"""
    text, source = model_complete("iteration", model, prompt, min(temperature, 0.45))
    return extract_scad(text), source


def requested_number(text, terms):
    text = text or ""
    term_pattern = "|".join(re.escape(term) for term in terms)
    patterns = [
        rf"(?:{term_pattern})[^\d]{{0,32}}(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?",
        rf"(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?[^\n]{{0,32}}(?:{term_pattern})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def replace_scad_assignment(scad, name, value):
    formatted = f"{value:g}"
    pattern = rf"(^\s*{re.escape(name)}\s*=\s*)[-+]?\d+(?:\.\d+)?(\s*;)"
    return re.sub(pattern, rf"\g<1>{formatted}\2", scad, count=1, flags=re.MULTILINE)


def deterministic_revision_scad(current_scad, request, notes):
    revised = current_scad
    context = f"{request}\n{notes}"
    if not re.search(r"^\s*bracket_width\s*=", current_scad, re.MULTILINE):
        return revised, "deterministic:no_parametric_l_bracket_match"

    width = requested_number(context, ["bracket_width", "bracket width", "width", "wide"])
    if width:
        revised = replace_scad_assignment(revised, "bracket_width", width)

    thickness = requested_number(context, ["thickness", "thick", "wall"])
    if thickness:
        revised = replace_scad_assignment(revised, "thickness", thickness)

    diameter = requested_number(context, ["hole diameter", "hole", "m4", "m5"])
    if re.search(r"\bm4\b", context, re.IGNORECASE):
        diameter = diameter or 5.2
    elif re.search(r"\bm5\b", context, re.IGNORECASE):
        diameter = diameter or 5.8
    if diameter:
        revised = replace_scad_assignment(revised, "hole_r", diameter / 2)

    if re.search(r"\b2\s*(?:in|inch|inches)\b", context, re.IGNORECASE):
        revised = replace_scad_assignment(revised, "leg_len", 50.8)
    else:
        leg_mm = requested_number(context, ["leg_len", "leg length", "flange length", "flange"])
        if leg_mm:
            revised = replace_scad_assignment(revised, "leg_len", leg_mm)

    return revised, "deterministic:parametric_l_bracket_revision"


def revise_scad(model, title, current_scad, request, notes, selection, measurement):
    prompt = f"""Revise this OpenSCAD model according to the review context.
Return one fenced scad code block only. Do not explain.

Preserve parametric variables near the top. Preserve the intended object unless the request explicitly changes it.
For engineering parts, keep functional dimensions, hole placement, wall thickness, printability, and clean solid geometry consistent.
If this is an L bracket, keep two perpendicular flat flanges with holes on the intended faces unless the request says otherwise.

Iteration:
{title}

Revision request:
{request or "Apply the review notes below."}

Selected surface context:
{selection or "none"}

Measurement:
{measurement or "none"}

Review notes:
{notes or "none"}

Current SCAD:
```scad
{current_scad}
```
"""
    text, source = model_complete("iteration", model, prompt, 0.35)
    return extract_scad(text), source


def parse_json_object(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = extract_scad(text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


def vision_critique(refined_prompt, result, vision_model):
    preview = result.get("preview") or ""
    if not preview:
        return {}, "no_preview"
    preview_path = DATA_DIR / unquote(preview.removeprefix("/artifacts/"))
    if not preview_path.exists():
        return {}, "preview_missing"
    prompt = f"""You are a CAD visual verification critic.
Inspect the rendered OpenSCAD preview against the CAD brief.
Return JSON only with these keys:
pass: boolean
is_l_bracket: boolean
holes_visible: boolean
horizontal_face_hole_count: integer
vertical_face_hole_count: integer
has_weird_top_fins: boolean
gussets_inside_corner: boolean
preview_cropped: boolean
issues: array of short strings
repair_instruction: short instruction for fixing the SCAD if pass is false

CAD brief:
{refined_prompt}
"""
    system = "You inspect CAD preview images and return strict JSON. Be critical about geometry, placement, and visible functional features. For L brackets, do not pass unless both perpendicular faces have the requested mounting holes."
    text, actual_model = jarvis_core_generate(
        "vision",
        prompt,
        system,
        temperature=0.1,
        max_tokens=700,
        images=[image_data_uri(preview_path)],
        model=vision_model,
    )
    return parse_json_object(text), f"jarvis-core:vision:{actual_model}"


def is_l_bracket_prompt(prompt):
    lowered = (prompt or "").lower()
    return "bracket" in lowered and (
        "l bracket" in lowered
        or "l-bracket" in lowered
        or "l shaped" in lowered
        or "l-shaped" in lowered
        or "angle bracket" in lowered
        or " l " in f" {lowered} "
    )


def screw_clearance_radius(prompt):
    lowered = (prompt or "").lower()
    if "m5" in lowered:
        return 2.75
    if "m4" in lowered:
        return 2.25
    if "m2.5" in lowered or "m2 " in f" {lowered} ":
        return 1.35
    return 1.7


def builtin_template_by_id(template_id):
    return next((item for item in BUILTIN_TEMPLATES if item.get("template_id") == template_id), {})


def selected_builtin_template(prompt):
    lowered = (prompt or "").lower()
    fastener = "m5" if "m5" in lowered else "m4" if "m4" in lowered else "m3" if "m3" in lowered else "m4"
    size = "heavy" if any(term in lowered for term in ("heavy", "heavy duty", "strong", "reinforced", "thick")) else "compact" if any(term in lowered for term in ("small", "compact", "low profile", "thin")) else "standard"
    def template_for(family):
        return f"{family}-{size}-{fastener}"
    if any(term in lowered for term in ("u bracket", "u-bracket", "u shaped", "u-shaped", "channel bracket")):
        return template_for("u-bracket")
    if is_l_bracket_prompt(prompt):
        return template_for("l-bracket")
    if any(term in lowered for term in ("cable clip", "wire clip", "wire clamp", "hose clip")):
        return template_for("cable-clip")
    if any(term in lowered for term in ("standoff", "pcb spacer", "electronics spacer")):
        return template_for("hex-standoff" if "hex" in lowered or "pcb" in lowered or "electronics" in lowered else "spacer-bushing")
    if any(term in lowered for term in ("spacer", "bushing", "washer", "sleeve")):
        return template_for("spacer-bushing")
    if any(term in lowered for term in ("mounting plate", "adapter plate", "flat plate")):
        return template_for("flat-mounting-plate")
    matches = search_builtin_templates(prompt, limit=1)
    return matches[0].get("template_id", "") if matches and matches[0].get("score", 0) >= 3 else ""


def num_param(params, key, default, min_value=None, max_value=None):
    try:
        value = float((params or {}).get(key, default))
    except (TypeError, ValueError):
        value = float(default)
    if min_value is not None:
        value = max(float(min_value), value)
    if max_value is not None:
        value = min(float(max_value), value)
    return round(value, 3)


def flat_mounting_plate_scad(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 20) / 2
    length = num_param(parameters, "length_mm", (60 + iteration * 5) * scale, 10, 500)
    width = num_param(parameters, "width_mm", (32 + iteration * 2) * scale, 8, 500)
    thickness = num_param(parameters, "thickness_mm", 4 * max(0.9, scale), 1, 80)
    corner_r = num_param(parameters, "fillet_radius_mm", 3, 0.1, min(length, width) / 2 - 0.1)
    return f"""// Built-in parametric template: flat rounded mounting plate
plate_len = {length};
plate_width = {width};
thickness = {thickness};
hole_r = {hole_r};
corner_r = {corner_r};
$fn = 64;

module rounded_plate() {{
  hull() {{
    for (x = [corner_r, plate_len - corner_r])
      for (y = [corner_r, plate_width - corner_r])
        translate([x, y, 0]) cylinder(r = corner_r, h = thickness);
  }}
}}

difference() {{
  rounded_plate();
  for (x = [plate_len * 0.25, plate_len * 0.75])
    for (y = [plate_width * 0.5])
      translate([x, y, -1]) cylinder(r = hole_r, h = thickness + 2);
}}
"""


def spacer_bushing_scad(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    outer_r = num_param(parameters, "outer_diameter_mm", max(hole_r + 3.0, (5.5 + iteration) * scale) * 2, hole_r * 2 + 2, 120) / 2
    height = num_param(parameters, "height_mm", (8 + iteration * 2) * scale, 1, 200)
    return f"""// Built-in parametric template: cylindrical spacer bushing
outer_r = {outer_r};
hole_r = {hole_r};
height = {height};
chamfer = 0.7;
$fn = 96;

difference() {{
  union() {{
    cylinder(r = outer_r, h = height);
    translate([0, 0, height - chamfer]) cylinder(r1 = outer_r, r2 = outer_r - chamfer, h = chamfer);
    cylinder(r1 = outer_r - chamfer, r2 = outer_r, h = chamfer);
  }}
  translate([0, 0, -1]) cylinder(r = hole_r, h = height + 2);
}}
"""


def hex_standoff_scad(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    across_flats = num_param(parameters, "width_mm", (7 + iteration) * scale, hole_r * 2 + 2, 80)
    height = num_param(parameters, "height_mm", (10 + iteration * 2) * scale, 1, 200)
    radius = across_flats / 1.732
    return f"""// Built-in parametric template: hex electronics standoff
body_r = {radius};
hole_r = {hole_r};
height = {height};
$fn = 6;

difference() {{
  cylinder(r = body_r, h = height);
  translate([0, 0, -1]) cylinder(r = hole_r, h = height + 2, $fn = 48);
}}
"""


def cable_clip_scad(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    cable_r = num_param(parameters, "outer_diameter_mm", (5 + iteration) * scale * 2, 2, 80) / 2
    tab_len = num_param(parameters, "length_mm", 28 * scale, 10, 300)
    tab_width = num_param(parameters, "width_mm", cable_r * 2 + 8 * scale, cable_r * 2 + 2, 200)
    thickness = num_param(parameters, "thickness_mm", 3 * max(0.9, scale), 1, 40)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 20) / 2
    return f"""// Built-in parametric template: screw-down cable clip
cable_r = {cable_r};
tab_len = {tab_len};
tab_width = {tab_width};
thickness = {thickness};
hole_r = {hole_r};
$fn = 64;

difference() {{
  union() {{
    cube([tab_len, tab_width, thickness]);
    translate([tab_len, tab_width / 2, thickness])
      rotate([0, 90, 0])
        difference() {{
          cylinder(r = cable_r + thickness, h = tab_width * 0.8, center = true);
          cylinder(r = cable_r, h = tab_width + 2, center = true);
          translate([-cable_r - thickness - 1, -tab_width, -tab_width])
            cube([cable_r + thickness + 1, tab_width * 2, tab_width * 2]);
        }}
  }}
  translate([tab_len * 0.38, tab_width / 2, -1]) cylinder(r = hole_r, h = thickness + 2);
}}
"""


def u_bracket_scad(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    width = num_param(parameters, "width_mm", (28 + iteration * 2) * scale, 8, 300)
    depth = num_param(parameters, "length_mm", 36 * scale, 8, 300)
    wall = num_param(parameters, "thickness_mm", 4 * max(0.9, scale), 1, 80)
    height = num_param(parameters, "height_mm", (28 + iteration * 3) * scale, wall + 2, 300)
    return f"""// Built-in parametric template: U bracket channel
width = {width};
depth = {depth};
wall = {wall};
height = {height};
hole_r = {hole_r};
$fn = 64;

difference() {{
  union() {{
    cube([width, depth, wall]);
    cube([wall, depth, height]);
    translate([width - wall, 0, 0]) cube([wall, depth, height]);
  }}
  for (x = [wall / 2, width - wall / 2])
    for (z = [height * 0.45])
      translate([x, depth / 2, z]) rotate([0, 90, 0]) cylinder(r = hole_r, h = wall + 2, center = true);
  translate([width / 2, depth / 2, -1]) cylinder(r = hole_r, h = wall + 2);
}}
"""


def builtin_template_scad(template_id, prompt, iteration, parameters=None):
    template = builtin_template_by_id(template_id)
    generator = template.get("generator") or template_id
    prompt_with_variant = " ".join(
        item
        for item in (
            prompt,
            str(template.get("fastener", "")),
            "heavy duty" if template.get("variant") == "heavy" else "compact" if template.get("variant") == "compact" else "",
        )
        if item
    )
    if generator == "l-bracket":
        return fallback_scad(prompt_with_variant, iteration, parameters)
    if generator == "flat-mounting-plate":
        return flat_mounting_plate_scad(prompt_with_variant, iteration, template, parameters)
    if generator == "spacer-bushing":
        return spacer_bushing_scad(prompt_with_variant, iteration, template, parameters)
    if generator == "hex-standoff":
        return hex_standoff_scad(prompt_with_variant, iteration, template, parameters)
    if generator == "cable-clip":
        return cable_clip_scad(prompt_with_variant, iteration, template, parameters)
    if generator == "u-bracket":
        return u_bracket_scad(prompt_with_variant, iteration, template, parameters)
    return ""


def trusted_scad(prompt, iteration, parameters=None):
    template_id = selected_builtin_template(prompt)
    if template_id:
        return builtin_template_scad(template_id, prompt, iteration, parameters)
    return ""


def cadquery_flat_mounting_plate(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    length = num_param(parameters, "length_mm", (60 + iteration * 5) * scale, 10, 500)
    width = num_param(parameters, "width_mm", (32 + iteration * 2) * scale, 8, 500)
    thickness = num_param(parameters, "thickness_mm", 4 * max(0.9, scale), 1, 80)
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 20) / 2
    corner_r = num_param(parameters, "fillet_radius_mm", 3, 0.1, min(length, width) / 2 - 0.1)
    return f'''"""Parametric CadQuery source for a flat mounting plate STEP export."""
import cadquery as cq

length = {length}
width = {width}
thickness = {thickness}
hole_r = {hole_r}
corner_r = {corner_r}

part = cq.Workplane("XY").box(length, width, thickness, centered=(False, False, False))
try:
    part = part.edges("|Z").fillet(corner_r)
except Exception:
    pass

for x in [length * 0.25, length * 0.75]:
    cutter = cq.Workplane().add(
        cq.Solid.makeCylinder(hole_r, thickness + 2, cq.Vector(x, width / 2, -1), cq.Vector(0, 0, 1))
    )
    part = part.cut(cutter)

cq.exporters.export(part, "model.step")
'''


def cadquery_spacer_bushing(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    outer_r = num_param(parameters, "outer_diameter_mm", max(hole_r + 3.0, (5.5 + iteration) * scale) * 2, hole_r * 2 + 2, 120) / 2
    height = num_param(parameters, "height_mm", (8 + iteration * 2) * scale, 1, 200)
    return f'''"""Parametric CadQuery source for a spacer bushing STEP export."""
import cadquery as cq

outer_r = {outer_r}
hole_r = {hole_r}
height = {height}

part = cq.Workplane("XY").circle(outer_r).extrude(height)
part = part.cut(cq.Workplane().add(
    cq.Solid.makeCylinder(hole_r, height + 2, cq.Vector(0, 0, -1), cq.Vector(0, 0, 1))
))
try:
    part = part.faces(">Z or <Z").edges().chamfer(0.5)
except Exception:
    pass

cq.exporters.export(part, "model.step")
'''


def cadquery_hex_standoff(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    across_flats = num_param(parameters, "width_mm", (7 + iteration) * scale, hole_r * 2 + 2, 80)
    height = num_param(parameters, "height_mm", (10 + iteration * 2) * scale, 1, 200)
    body_r = across_flats / 1.732
    return f'''"""Parametric CadQuery source for a hex standoff STEP export."""
import cadquery as cq

body_r = {body_r}
hole_r = {hole_r}
height = {height}

part = cq.Workplane("XY").polygon(6, body_r * 2).extrude(height)
part = part.cut(cq.Workplane().add(
    cq.Solid.makeCylinder(hole_r, height + 2, cq.Vector(0, 0, -1), cq.Vector(0, 0, 1))
))

cq.exporters.export(part, "model.step")
'''


def cadquery_cable_clip(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    cable_r = num_param(parameters, "outer_diameter_mm", (5 + iteration) * scale * 2, 2, 80) / 2
    tab_len = num_param(parameters, "length_mm", 28 * scale, 10, 300)
    tab_width = num_param(parameters, "width_mm", cable_r * 2 + 8 * scale, cable_r * 2 + 2, 200)
    thickness = num_param(parameters, "thickness_mm", 3 * max(0.9, scale), 1, 40)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 20) / 2
    return f'''"""Parametric CadQuery source for a screw-down cable clip STEP export."""
import cadquery as cq

cable_r = {cable_r}
tab_len = {tab_len}
tab_width = {tab_width}
thickness = {thickness}
hole_r = {hole_r}

tab = cq.Workplane("XY").box(tab_len, tab_width, thickness, centered=(False, False, False))
arch = cq.Workplane("YZ").circle(cable_r + thickness).extrude(tab_width * 0.8).translate((tab_len, tab_width * 0.1, thickness))
slot = cq.Workplane("YZ").circle(cable_r).extrude(tab_width + 2).translate((tab_len, -1, thickness))
part = tab.union(arch).cut(slot)
part = part.cut(cq.Workplane().add(
    cq.Solid.makeCylinder(hole_r, thickness + 2, cq.Vector(tab_len * 0.38, tab_width / 2, -1), cq.Vector(0, 0, 1))
))

cq.exporters.export(part, "model.step")
'''


def cadquery_u_bracket(prompt, iteration, template=None, parameters=None):
    template = template or {}
    scale = float(template.get("scale") or 1.0)
    default_hole_r = float(template.get("hole_r") or screw_clearance_radius(prompt))
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    width = num_param(parameters, "width_mm", (28 + iteration * 2) * scale, 8, 300)
    depth = num_param(parameters, "length_mm", 36 * scale, 8, 300)
    wall = num_param(parameters, "thickness_mm", 4 * max(0.9, scale), 1, 80)
    height = num_param(parameters, "height_mm", (28 + iteration * 3) * scale, wall + 2, 300)
    return f'''"""Parametric CadQuery source for a U bracket STEP export."""
import cadquery as cq

width = {width}
depth = {depth}
wall = {wall}
height = {height}
hole_r = {hole_r}

base = cq.Workplane("XY").box(width, depth, wall, centered=(False, False, False))
left = cq.Workplane("XY").box(wall, depth, height, centered=(False, False, False))
right = cq.Workplane("XY").box(wall, depth, height, centered=(False, False, False)).translate((width - wall, 0, 0))
part = base.union(left).union(right)

for x in [wall / 2, width - wall / 2]:
    cutter = cq.Workplane().add(
        cq.Solid.makeCylinder(hole_r, wall + 2, cq.Vector(x - 1, depth / 2, height * 0.45), cq.Vector(1, 0, 0))
    )
    part = part.cut(cutter)
part = part.cut(cq.Workplane().add(
    cq.Solid.makeCylinder(hole_r, wall + 2, cq.Vector(width / 2, depth / 2, -1), cq.Vector(0, 0, 1))
))

cq.exporters.export(part, "model.step")
'''


def cadquery_l_bracket(prompt, iteration, parameters=None):
    if not is_l_bracket_prompt(prompt):
        return ""
    params = l_bracket_params(prompt, iteration, parameters)
    return f'''"""Parametric CadQuery source for the trusted L-bracket STEP export."""
import cadquery as cq

leg_len = {params["leg"]}
bracket_width = {params["bracket_width"]}
thickness = {params["thickness"]}
hole_r = {params["hole_r"]}

horizontal = cq.Workplane("XY").box(bracket_width, leg_len, thickness, centered=(False, False, False))
vertical = (
    cq.Workplane("XY")
    .box(bracket_width, thickness, leg_len, centered=(False, False, False))
    .translate((0, leg_len - thickness, thickness - leg_len))
)
part = horizontal.union(vertical)

for offset in [leg_len * 0.32, leg_len * 0.72]:
    top_hole = cq.Workplane().add(
        cq.Solid.makeCylinder(hole_r, thickness + 2, cq.Vector(bracket_width / 2, offset, -1), cq.Vector(0, 0, 1))
    )
    vertical_hole = cq.Workplane().add(
        cq.Solid.makeCylinder(hole_r, thickness + 2, cq.Vector(bracket_width / 2, leg_len - thickness - 1, thickness - offset), cq.Vector(0, 1, 0))
    )
    part = part.cut(top_hole).cut(vertical_hole)

cq.exporters.export(part, "model.step")
'''


def builtin_template_cadquery(template_id, prompt, iteration, parameters=None):
    template = builtin_template_by_id(template_id)
    generator = template.get("generator") or template_id
    prompt_with_variant = " ".join(
        item
        for item in (
            prompt,
            str(template.get("fastener", "")),
            "heavy duty" if template.get("variant") == "heavy" else "compact" if template.get("variant") == "compact" else "",
        )
        if item
    )
    if generator == "l-bracket":
        return cadquery_l_bracket(prompt_with_variant, iteration, parameters)
    if generator == "flat-mounting-plate":
        return cadquery_flat_mounting_plate(prompt_with_variant, iteration, template, parameters)
    if generator == "spacer-bushing":
        return cadquery_spacer_bushing(prompt_with_variant, iteration, template, parameters)
    if generator == "hex-standoff":
        return cadquery_hex_standoff(prompt_with_variant, iteration, template, parameters)
    if generator == "cable-clip":
        return cadquery_cable_clip(prompt_with_variant, iteration, template, parameters)
    if generator == "u-bracket":
        return cadquery_u_bracket(prompt_with_variant, iteration, template, parameters)
    return ""


def trusted_cadquery(prompt, iteration, parameters=None):
    template_id = selected_builtin_template(prompt)
    if template_id:
        return builtin_template_cadquery(template_id, prompt, iteration, parameters)
    return ""


def l_bracket_params(prompt, iteration, parameters=None):
    lowered = (prompt or "").lower()
    default_hole_r = 2.6 if "m5" not in lowered else 2.8
    leg = num_param(parameters, "length_mm", 50.8, 12, 500)
    bracket_width = num_param(parameters, "width_mm", 24 + iteration * 2, 8, 250)
    thickness = num_param(parameters, "thickness_mm", 4.5 + (iteration % 3) * 0.5, 1.5, 80)
    hole_r = num_param(parameters, "hole_diameter_mm", default_hole_r * 2, 1, 30) / 2
    return {
        "leg": leg,
        "bracket_width": bracket_width,
        "thickness": thickness,
        "gusset": num_param(parameters, "gusset_mm", min(18 + iteration * 2, leg * 0.45), 1, leg * 0.75),
        "rib_thickness": num_param(parameters, "rib_thickness_mm", 3.2, 1, 30),
        "hole_r": hole_r,
        "wants_gussets": any(term in lowered for term in ("gusset", "rib", "reinforced", "reinforcement", "heavy duty")),
        "rejects_gussets": any(term in lowered for term in ("no gusset", "no rib", "without gusset", "without rib", "do not add gusset", "do not add rib")),
    }


def fallback_scad(prompt, iteration, parameters=None):
    if is_l_bracket_prompt(prompt):
        params = l_bracket_params(prompt, iteration, parameters)
        leg = params["leg"]
        bracket_width = params["bracket_width"]
        thickness = params["thickness"]
        gusset = params["gusset"]
        rib_thickness = params["rib_thickness"]
        hole_r = params["hole_r"]
        wants_gussets = params["wants_gussets"]
        rejects_gussets = params["rejects_gussets"]
        include_gussets = wants_gussets and not rejects_gussets
        gusset_module = f"""
module triangular_gusset(x) {{
  x0 = x - rib_thickness / 2;
  x1 = x + rib_thickness / 2;
  corner_y = leg_len - thickness;
  polyhedron(
    points = [
      [x0, corner_y, 0],
      [x0, corner_y - gusset_size, 0],
      [x0, corner_y, -gusset_size],
      [x1, corner_y, 0],
      [x1, corner_y - gusset_size, 0],
      [x1, corner_y, -gusset_size]
    ],
    faces = [
      [0, 1, 2], [3, 5, 4],
      [0, 3, 4, 1], [0, 2, 5, 3],
      [1, 4, 5, 2]
    ]
  );
}}
""" if include_gussets else ""
        gusset_union = """
    // Compact triangular gussets inside the underside of the angle.
    for (x = [bracket_width * 0.28, bracket_width * 0.72])
      triangular_gusset(x);
""" if include_gussets else ""
        return f"""// Fallback parametric OpenSCAD concept: printable 2 inch angle bracket
leg_len = {leg};
bracket_width = {bracket_width};
thickness = {thickness};
gusset_size = {gusset};
rib_thickness = {rib_thickness};
hole_r = {hole_r};
corner_r = 2;
$fn = 64;

module rounded_box(size, r = corner_r) {{
  hull() {{
    for (x = [r, size[0] - r])
      for (y = [r, size[1] - r])
        translate([x, y, 0]) cylinder(r = r, h = size[2]);
  }}
}}

module countersunk_hole_z(x, y) {{
  translate([x, y, -1]) cylinder(r = hole_r, h = thickness + 2);
  translate([x, y, thickness - 1.2]) cylinder(r1 = hole_r * 2.0, r2 = hole_r, h = 2.0);
}}

module countersunk_hole_y(x, z) {{
  translate([x, leg_len - thickness - 1, z]) rotate([-90, 0, 0]) cylinder(r = hole_r, h = thickness + 2);
  translate([x, leg_len - thickness - 0.8, z]) rotate([-90, 0, 0]) cylinder(r1 = hole_r * 2.0, r2 = hole_r, h = 2.0);
}}
{gusset_module}

difference() {{
  union() {{
    // 2 inch horizontal leg.
    rounded_box([bracket_width, leg_len, thickness]);

    // 2 inch vertical leg, overlapped into the horizontal plate so this is one solid body.
    translate([0, leg_len - thickness, thickness])
      rotate([-90, 0, 0])
        rounded_box([bracket_width, leg_len, thickness]);
{gusset_union}
  }}

  for (offset = [leg_len * 0.32, leg_len * 0.72]) {{
    countersunk_hole_z(bracket_width / 2, offset);
    countersunk_hole_y(bracket_width / 2, thickness - offset);
  }}
}}
"""
    label = re.sub(r"[^A-Za-z0-9 _-]", "", prompt or "SCAD concept")[:32]
    width = 42 + iteration * 3
    depth = 28 + iteration * 2
    height = 12 + iteration
    return f"""// Fallback parametric OpenSCAD concept: {label}
width = {width};
depth = {depth};
height = {height};
corner_r = 4;
hole_r = 3;
$fn = 48;

difference() {{
  hull() {{
    for (x = [-width / 2 + corner_r, width / 2 - corner_r])
      for (y = [-depth / 2 + corner_r, depth / 2 - corner_r])
        translate([x, y, 0]) cylinder(r = corner_r, h = height);
  }}
  translate([0, 0, -1]) cylinder(r = hole_r, h = height + 2);
  translate([0, 0, height * 0.45])
    cube([width * 0.72, depth * 0.52, height], center = true);
}}
"""


def page():
    def model_options(selected):
        options = list(dict.fromkeys([selected, *MODEL_OPTIONS]))
        return "".join(
            f'<option value="{html.escape(model)}"{" selected" if model == selected else ""}>{html.escape(model)}</option>'
            for model in options
            if model
        )

    auth_panel = "" if not configured_token() else """
      <section class="panel">
        <label for="token">Access token</label>
        <input id="token" type="password" autocomplete="current-password" placeholder="Paste SCAD AI token">
      </section>
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SCAD AI Generator</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #101418;
      --panel: #171d22;
      --panel2: #20282f;
      --line: #34414b;
      --text: #f4f7f8;
      --muted: #aeb8bf;
      --accent: #72e0b7;
      --danger: #fb7185;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(1280px, calc(100vw - 28px)); margin: 0 auto; padding: 18px 0 36px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 12px; }}
    h1 {{ font-size: 22px; margin: 0; letter-spacing: 0; }}
    .status {{ color: var(--muted); font-size: 14px; }}
    .app-tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }}
    .app-tab {{ width: auto; border-color: transparent; background: transparent; color: var(--muted); padding: 8px 11px; }}
    .app-tab.active {{ border-color: rgba(114, 224, 183, .75); background: #132720; color: var(--accent); }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .app-grid {{ display: grid; grid-template-columns: minmax(0, 720px); gap: 12px; align-items: start; }}
    .panel {{ border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 14px; margin-bottom: 14px; }}
    details.panel summary {{ cursor: pointer; color: var(--muted); font-weight: 700; }}
    label {{ display: block; color: var(--muted); font-size: 13px; margin-bottom: 6px; }}
    textarea, input, select {{ width: 100%; border: 1px solid var(--line); border-radius: 6px; background: #0b1013; color: var(--text); padding: 10px 12px; font: inherit; }}
    textarea {{ min-height: 120px; resize: vertical; }}
    textarea.brief {{ min-height: 125px; }}
    textarea.code-editor {{ min-height: 165px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .grid.three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    button, a.button {{ border: 1px solid var(--line); border-radius: 6px; background: var(--panel2); color: var(--text); padding: 10px 12px; cursor: pointer; font-weight: 700; text-decoration: none; }}
    button.primary {{ border-color: rgba(114, 224, 183, .85); }}
    button:disabled {{ opacity: .55; cursor: wait; }}
    pre {{ margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #d8e2e5; font-size: 13px; line-height: 1.45; }}
    .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: hidden; position: relative; }}
    .card.deleting {{ opacity: .35; transform: scale(.985); pointer-events: none; transition: opacity .12s ease, transform .12s ease; }}
    .card-delete {{ position: absolute; top: 7px; left: 7px; z-index: 3; width: 28px; height: 28px; display: grid; place-items: center; padding: 0; opacity: 0; border-color: rgba(251, 113, 133, .75); color: #fecdd3; background: rgba(50, 18, 25, .9); }}
    .card:hover .card-delete {{ opacity: 1; }}
    .delete-confirm {{ position: absolute; inset: 8px 8px auto 8px; z-index: 6; display: none; align-items: center; gap: 6px; padding: 7px; border: 1px solid rgba(251, 113, 133, .75); border-radius: 7px; background: rgba(35, 14, 20, .96); box-shadow: 0 10px 30px rgba(0,0,0,.35); }}
    .card.confirming-delete .delete-confirm {{ display: flex; }}
    .delete-confirm span {{ color: #fecdd3; font-size: 12px; font-weight: 700; margin-right: auto; }}
    .delete-confirm button {{ width: auto; padding: 4px 7px; font-size: 12px; }}
    .card-head {{ display: flex; align-items: start; justify-content: space-between; gap: 8px; margin-bottom: 8px; }}
    .editable-title {{ cursor: text; border-radius: 4px; padding: 2px 3px; margin-left: -3px; }}
    .editable-title:hover {{ background: rgba(114, 224, 183, .1); color: #b9ffe5; }}
    .preview-link {{ display: block; cursor: zoom-in; background: #050708; }}
    .card img {{ width: 100%; aspect-ratio: 4 / 3; object-fit: contain; background: #050708; display: block; }}
    .card .body {{ padding: 10px; }}
    .card h2 {{ margin: 0; font-size: 15px; letter-spacing: 0; }}
    .action-wrap {{ position: relative; opacity: 0; transition: opacity .12s ease; flex: 0 0 auto; }}
    .card:hover .action-wrap {{ opacity: 1; }}
    .action-menu-button {{ width: 30px; height: 28px; padding: 0; display: grid; place-items: center; }}
    .project-actions {{ position: absolute; top: 32px; right: 0; z-index: 5; display: none; min-width: 160px; padding: 6px; border: 1px solid var(--line); border-radius: 7px; background: #0d1418; box-shadow: 0 10px 30px rgba(0,0,0,.35); }}
    .action-wrap.open .project-actions, .action-wrap:hover .project-actions {{ display: grid; gap: 5px; }}
    .project-actions a {{ border: 1px solid rgba(114, 224, 183, .4); border-radius: 5px; color: var(--accent); font-size: 12px; padding: 5px 7px; text-decoration: none; white-space: nowrap; }}
    .project-actions a:hover {{ border-color: rgba(114, 224, 183, .9); color: #b9ffe5; }}
    .links {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .links a {{ border: 1px solid rgba(114, 224, 183, .5); border-radius: 6px; color: var(--accent); font-size: 13px; padding: 5px 8px; text-decoration: none; }}
    .catalog-controls {{ display: grid; grid-template-columns: minmax(0, 1fr) 160px; gap: 8px; margin-bottom: 10px; }}
    .type-tabs {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
    .type-tab {{ width: auto; padding: 7px 10px; font-size: 12px; color: var(--muted); transition: background .12s ease, border-color .12s ease, color .12s ease, box-shadow .12s ease; }}
    .type-tab.active {{ border-color: rgba(114, 224, 183, 1); color: #06110d; background: var(--accent); box-shadow: 0 0 0 2px rgba(114, 224, 183, .18); }}
    .type-tab.interested {{ border-color: rgba(114, 224, 183, .85); color: #b9ffe5; background: #19342a; }}
    .catalog-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; max-height: calc(100vh - 250px); overflow: auto; padding-right: 3px; }}
    .template-card {{ border: 1px solid var(--line); border-radius: 8px; background: #11181d; padding: 10px; display: grid; gap: 7px; }}
    .template-card.selected {{ border-color: rgba(114, 224, 183, .9); box-shadow: 0 0 0 2px rgba(114, 224, 183, .12); }}
    .template-card h3 {{ margin: 0; font-size: 14px; letter-spacing: 0; }}
    .template-meta {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .chip {{ border: 1px solid #40505a; border-radius: 999px; padding: 2px 6px; color: #b7c8ce; font-size: 11px; }}
    .template-card p {{ margin: 0; color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .template-actions {{ display: flex; gap: 6px; align-items: center; }}
    .template-actions button {{ width: auto; padding: 6px 9px; font-size: 12px; }}
    .catalog-summary {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .param-summary {{ color: #b9ffe5; font-size: 12px; margin-top: 8px; }}
    .param-field.hidden {{ display: none; }}
    .results-empty {{ border: 1px dashed var(--line); border-radius: 8px; min-height: 220px; display: grid; place-items: center; color: var(--muted); background: #11181d; }}
    .results-wrap.hidden {{ display: none; }}
    .debug-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }}
    .error {{ color: var(--danger); }}
    .lightbox {{ position: fixed; inset: 0; z-index: 20; display: none; align-items: center; justify-content: center; background: rgba(0, 0, 0, .82); padding: 18px; }}
    .lightbox.open {{ display: flex; }}
    .lightbox-inner {{ width: min(1280px, calc(100vw - 24px)); max-height: calc(100vh - 24px); border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: auto; }}
    .lightbox-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--line); }}
    .icon-close {{ width: 34px; height: 34px; flex: 0 0 34px; display: inline-grid; place-items: center; padding: 0; border-radius: 6px; font-size: 20px; line-height: 1; }}
    .lightbox img {{ width: 100%; height: auto; display: block; background: #050708; }}
    .lightbox iframe {{ width: 100%; height: min(84vh, 860px); border: 0; display: none; background: #050708; }}
    @media (max-width: 860px) {{ .app-grid, .grid, .debug-grid, .catalog-controls {{ grid-template-columns: 1fr; }} header {{ align-items: flex-start; flex-direction: column; }} button {{ width: 100%; }} .app-tab, .type-tab, .template-actions button, .lightbox-head .icon-close {{ width: auto; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>SCAD AI Generator</h1>
      <span class="status">Template-driven CAD iteration</span>
    </header>
    <nav class="app-tabs" aria-label="Workspace">
      <button class="app-tab active" type="button" data-tab="browse">Browse</button>
      <button class="app-tab" type="button" data-tab="generate">Generate</button>
      <button class="app-tab" type="button" data-tab="library">Library</button>
      <button class="app-tab" type="button" data-tab="review">Review</button>
      <button class="app-tab" type="button" data-tab="editor">Editor</button>
      <button class="app-tab" type="button" data-tab="results">Results</button>
    </nav>
    {auth_panel}
    <section class="tab-panel active" id="tab-browse">
      <section class="panel">
        <label>Template browser</label>
        <div class="catalog-controls">
          <input id="templateSearch" type="search" placeholder="Search brackets, spacers, clips, plates...">
          <select id="templateFastener">
            <option value="">All fasteners</option>
            <option value="m3">M3</option>
            <option value="m4">M4</option>
            <option value="m5">M5</option>
          </select>
        </div>
        <div class="type-tabs" id="templateTypes"></div>
        <div class="catalog-summary" id="templateSummary">Loading templates...</div>
        <div class="catalog-grid" id="templateCatalog"></div>
      </section>
    </section>
    <section class="tab-panel" id="tab-generate">
      <div class="app-grid">
        <section class="panel">
          <label for="prompt">CAD brief</label>
          <textarea id="prompt" class="brief" placeholder="Parametric wall-mounted headphone hook with countersunk screw holes, rounded edges, and print-friendly chamfers"></textarea>
          <div class="grid" style="margin-top: 10px;">
            <div><label for="iterations">Iterations</label><input id="iterations" type="number" min="1" max="{MAX_ITERATIONS}" value="1"></div>
            <div><label for="cacheMode">Library</label><select id="cacheMode"><option value="cache-first">Use approved cache first</option><option value="ai-first">AI/templates first</option></select></div>
          </div>
          <details class="param-panel" id="paramPanel" open style="margin-top: 10px;">
            <summary>Template parameters</summary>
            <input id="selectedTemplateId" type="hidden">
            <div class="param-summary" id="paramSummary">Choose a template to show focused controls.</div>
            <div class="grid three" style="margin-top: 10px;">
              <div class="param-field" data-param="length"><label for="paramLength">Length / flange mm</label><input id="paramLength" type="number" min="1" step="0.1" placeholder="50.8"></div>
              <div class="param-field" data-param="width"><label for="paramWidth">Width mm</label><input id="paramWidth" type="number" min="1" step="0.1" placeholder="24"></div>
              <div class="param-field" data-param="height"><label for="paramHeight">Height mm</label><input id="paramHeight" type="number" min="1" step="0.1" placeholder="30"></div>
              <div class="param-field" data-param="thickness"><label for="paramThickness">Thickness mm</label><input id="paramThickness" type="number" min="0.5" step="0.1" placeholder="4"></div>
              <div class="param-field" data-param="hole"><label for="paramHoleDiameter">Hole dia mm</label><input id="paramHoleDiameter" type="number" min="0.5" step="0.1" placeholder="4.5"></div>
              <div class="param-field" data-param="fillet"><label for="paramFillet">Fillet mm</label><input id="paramFillet" type="number" min="0" step="0.1" placeholder="2"></div>
            </div>
          </details>
          <details style="margin-top: 10px;">
            <summary>Advanced generation settings</summary>
            <div class="grid" style="margin-top: 10px;">
              <div><label for="temperature">Temperature</label><input id="temperature" type="number" min="0" max="2" step="0.1" value="0.8"></div>
              <div><label for="pipelineMode">Pipeline</label><select id="pipelineMode"><option value="refine">Refine prompt first</option><option value="direct">Direct iteration</option></select></div>
              <div><label for="previewView">Preview export</label><select id="previewView"><option value="render">Render PNG + STL</option><option value="compile">Compile only</option></select></div>
            </div>
            <div class="grid three" style="margin-top: 10px;">
              <div><label for="promptModel">Prompt model</label><select id="promptModel">{model_options(PROMPT_MODEL)}</select></div>
              <div><label for="iterationModel">Iteration model</label><select id="iterationModel">{model_options(ITERATION_MODEL)}</select></div>
              <div><label for="visionModel">Vision model</label><select id="visionModel">{model_options(VISION_MODEL)}</select></div>
            </div>
          </details>
          <div class="row" style="margin-top: 12px;">
            <button class="primary" id="generate">Generate Iterations</button>
            <select id="toolAction" style="flex: 1 1 190px; width: auto;">
              <option value="search-library">Search approved library</option>
              <option value="research-scad">Research public SCAD</option>
              <option value="preview-editor">Preview editor SCAD</option>
              <option value="load-sample">Load sample SCAD</option>
            </select>
            <button id="runTool" type="button">Run</button>
          </div>
        </section>
        <section class="panel">
          <label>Selected template / research</label>
          <pre id="libraryResults">Choose a template from Browse or run a library/research action.</pre>
        </section>
      </div>
    </section>
    <section class="tab-panel" id="tab-library">
      <section class="panel">
        <label>Persistent project library</label>
        <div class="catalog-controls">
          <input id="projectSearch" type="search" placeholder="Search projects, templates, revisions, source...">
          <select id="projectFastener">
            <option value="">All fasteners</option>
            <option value="m3">M3</option>
            <option value="m4">M4</option>
            <option value="m5">M5</option>
          </select>
        </div>
        <div class="row">
          <button id="refreshProjects" type="button">Refresh Library</button>
          <button id="openLatest" type="button">Open Latest Result</button>
        </div>
        <div class="catalog-summary" id="projectSummary" style="margin-top: 12px;">Library not loaded yet.</div>
        <div class="gallery" id="projectLibrary"></div>
      </section>
    </section>
    <section class="tab-panel" id="tab-review">
      <section class="panel">
        <label>Template review queue</label>
        <div class="catalog-controls">
          <input id="reviewSearch" type="search" placeholder="Search imported/researched candidates...">
          <select id="reviewSource">
            <option value="">All sources</option>
            <option value="github">GitHub</option>
          </select>
        </div>
        <button id="refreshReview" type="button">Refresh Review Queue</button>
        <pre id="reviewQueue" style="margin-top: 12px;">Review queue not loaded yet.</pre>
      </section>
    </section>
    <section class="tab-panel" id="tab-editor">
      <section class="panel">
        <label for="scad">SCAD editor</label>
        <textarea id="scad" class="code-editor" spellcheck="false" placeholder="Paste or edit OpenSCAD here, then use Preview editor SCAD from the tool menu."></textarea>
        <div class="row" style="margin-top: 12px;">
          <button id="previewEditorButton" type="button">Preview Editor SCAD</button>
          <button id="loadSampleButton" type="button">Load Sample</button>
        </div>
      </section>
    </section>
    <section class="tab-panel" id="tab-results">
      <div class="results-empty" id="resultsEmpty">Generated previews will appear here.</div>
      <section class="results-wrap hidden" id="resultsWrap">
        <div class="gallery" id="gallery"></div>
      </section>
      <details class="panel" style="margin-top: 14px;">
        <summary>Run details</summary>
        <div class="debug-grid">
          <section>
            <label>Pipeline status</label>
            <pre id="pipeline">No run started yet.</pre>
          </section>
          <section>
            <label>Raw response</label>
            <pre id="raw">Waiting.</pre>
          </section>
        </div>
      </details>
    </section>
  </main>
  <div id="lightbox" class="lightbox" role="dialog" aria-modal="true" aria-label="Preview image">
    <div class="lightbox-inner">
      <div class="lightbox-head">
        <strong id="lightboxTitle">Preview</strong>
        <button id="closeLightbox" class="icon-close" type="button" aria-label="Close preview" title="Close">&times;</button>
      </div>
      <img id="lightboxImage" alt="Rendered OpenSCAD preview">
      <iframe id="lightboxFrame" title="Interactive STL preview"></iframe>
    </div>
  </div>
  <script>
    const tokenInput = document.getElementById('token');
    if (tokenInput) tokenInput.value = localStorage.getItem('scadAiToken') || '';
    const raw = document.getElementById('raw');
    const gallery = document.getElementById('gallery');
    const resultsEmpty = document.getElementById('resultsEmpty');
    const resultsWrap = document.getElementById('resultsWrap');
    const scad = document.getElementById('scad');
    const pipeline = document.getElementById('pipeline');
    const libraryResults = document.getElementById('libraryResults');
    const promptInput = document.getElementById('prompt');
    const templateCatalog = document.getElementById('templateCatalog');
    const templateTypes = document.getElementById('templateTypes');
    const templateSearch = document.getElementById('templateSearch');
    const templateFastener = document.getElementById('templateFastener');
    const templateSummary = document.getElementById('templateSummary');
    const projectSearch = document.getElementById('projectSearch');
    const projectFastener = document.getElementById('projectFastener');
    const projectLibrary = document.getElementById('projectLibrary');
    const projectSummary = document.getElementById('projectSummary');
    const reviewSearch = document.getElementById('reviewSearch');
    const reviewSource = document.getElementById('reviewSource');
    const reviewQueue = document.getElementById('reviewQueue');
    const selectedTemplateInput = document.getElementById('selectedTemplateId');
    const paramLength = document.getElementById('paramLength');
    const paramWidth = document.getElementById('paramWidth');
    const paramHeight = document.getElementById('paramHeight');
    const paramThickness = document.getElementById('paramThickness');
    const paramHoleDiameter = document.getElementById('paramHoleDiameter');
    const paramFillet = document.getElementById('paramFillet');
    const paramSummary = document.getElementById('paramSummary');
    const lightbox = document.getElementById('lightbox');
    const lightboxImage = document.getElementById('lightboxImage');
    const lightboxFrame = document.getElementById('lightboxFrame');
    const lightboxTitle = document.getElementById('lightboxTitle');
    const sampleScad = `width = 56;
depth = 34;
height = 16;
corner_r = 5;
hole_r = 3;
$fn = 56;

difference() {{
  hull() {{
    for (x = [-width / 2 + corner_r, width / 2 - corner_r])
      for (y = [-depth / 2 + corner_r, depth / 2 - corner_r])
        translate([x, y, 0]) cylinder(r = corner_r, h = height);
  }}
  translate([0, 0, -1]) cylinder(r = hole_r, h = height + 2);
  translate([0, 0, height * 0.55]) cube([width * 0.68, depth * 0.45, height], center = true);
}}`;

    function headers() {{
      const h = {{'Content-Type': 'application/json'}};
      if (tokenInput && tokenInput.value.trim()) {{
        localStorage.setItem('scadAiToken', tokenInput.value.trim());
        h.Authorization = `Bearer ${{tokenInput.value.trim()}}`;
      }}
      return h;
    }}
    let catalogItems = [];
    let selectedType = 'all';
    let selectedTemplateId = '';
    let interestedType = '';
    let templateTypeList = [];
    function switchTab(name) {{
      document.querySelectorAll('.app-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.tab === name));
      document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.id === `tab-${{name}}`));
    }}
    function templateBrief(item) {{
      return `Use template: ${{item.title}}. Component type: ${{item.component_type}}. Family: ${{item.family}}. Variant: ${{item.variant}}. Fastener: ${{item.fastener}}. ${{item.description}}`;
    }}
    function fastenerHoleDiameter(item) {{
      if (!item || item.fastener === 'm3') return 3.4;
      if (item.fastener === 'm5') return 5.5;
      return 4.5;
    }}
    function configureParamField(key, label, placeholder, visible = true) {{
      const field = document.querySelector(`[data-param="${{key}}"]`);
      if (!field) return;
      field.classList.toggle('hidden', !visible);
      const labelEl = field.querySelector('label');
      const inputEl = field.querySelector('input');
      if (labelEl) labelEl.textContent = label;
      if (inputEl) inputEl.placeholder = placeholder;
    }}
    function applyParameterLayout(item) {{
      const family = item && item.family;
      const title = item && item.title ? item.title : 'Selected template';
      configureParamField('length', 'Length mm', '50.8', true);
      configureParamField('width', 'Width mm', '24', true);
      configureParamField('height', 'Height mm', '30', true);
      configureParamField('thickness', 'Thickness mm', '4', true);
      configureParamField('hole', 'Hole dia mm', '4.5', true);
      configureParamField('fillet', 'Fillet mm', '2', true);
      if (family === 'l-bracket') {{
        configureParamField('length', 'Flange length mm', '50.8', true);
        configureParamField('width', 'Bracket width mm', '26', true);
        configureParamField('height', 'Second flange mm', '50.8', false);
        configureParamField('thickness', 'Material thickness mm', '4.5', true);
        configureParamField('hole', 'Clearance hole dia mm', '4.5', true);
        configureParamField('fillet', 'Corner fillet mm', '2', false);
        paramSummary.textContent = `${{title}}: flange length, bracket width, material thickness, and screw clearance.`;
      }} else if (family === 'u-bracket') {{
        configureParamField('length', 'Channel depth mm', '36', true);
        configureParamField('width', 'Outside width mm', '28', true);
        configureParamField('height', 'Side wall height mm', '28', true);
        configureParamField('thickness', 'Wall thickness mm', '4', true);
        configureParamField('hole', 'Clearance hole dia mm', '4.5', true);
        configureParamField('fillet', 'Fillet mm', '2', false);
        paramSummary.textContent = `${{title}}: outside channel size, wall thickness, and side/base holes.`;
      }} else if (family === 'flat-mounting-plate') {{
        configureParamField('length', 'Plate length mm', '80', true);
        configureParamField('width', 'Plate width mm', '40', true);
        configureParamField('height', 'Height mm', '', false);
        configureParamField('thickness', 'Plate thickness mm', '5', true);
        configureParamField('hole', 'Clearance hole dia mm', '4.5', true);
        configureParamField('fillet', 'Corner radius mm', '3', true);
        paramSummary.textContent = `${{title}}: plate footprint, thickness, corner radius, and screw clearance.`;
      }} else if (family === 'spacer-bushing') {{
        configureParamField('length', 'Length mm', '', false);
        configureParamField('width', 'Outer diameter mm', '14', true);
        configureParamField('height', 'Spacer height mm', '12', true);
        configureParamField('thickness', 'Wall thickness mm', '', false);
        configureParamField('hole', 'Through-hole dia mm', '4.5', true);
        configureParamField('fillet', 'Chamfer/fillet mm', '', false);
        paramSummary.textContent = `${{title}}: outer diameter, height, and through-hole clearance.`;
      }} else if (family === 'hex-standoff') {{
        configureParamField('length', 'Length mm', '', false);
        configureParamField('width', 'Across flats mm', '8', true);
        configureParamField('height', 'Standoff height mm', '12', true);
        configureParamField('thickness', 'Wall thickness mm', '', false);
        configureParamField('hole', 'Axial hole dia mm', '3.4', true);
        configureParamField('fillet', 'Chamfer/fillet mm', '', false);
        paramSummary.textContent = `${{title}}: hex size, height, and axial screw clearance.`;
      }} else if (family === 'cable-clip') {{
        configureParamField('length', 'Tab length mm', '28', true);
        configureParamField('width', 'Cable/clip width mm', '20', true);
        configureParamField('height', 'Height mm', '', false);
        configureParamField('thickness', 'Clip thickness mm', '3', true);
        configureParamField('hole', 'Screw hole dia mm', '4.5', true);
        configureParamField('fillet', 'Fillet mm', '', false);
        paramSummary.textContent = `${{title}}: tab footprint, clip thickness, cable clearance, and screw clearance.`;
      }} else {{
        paramSummary.textContent = 'Choose a template to show focused controls.';
      }}
    }}
    function setTemplateParameters(item) {{
      selectedTemplateId = item.template_id || '';
      selectedTemplateInput.value = selectedTemplateId;
      applyParameterLayout(item);
      const scale = item.variant === 'compact' ? 0.8 : item.variant === 'heavy' ? 1.25 : 1;
      paramHoleDiameter.value = fastenerHoleDiameter(item);
      paramFillet.value = item.family === 'flat-mounting-plate' ? 3 : 2;
      if (item.family === 'l-bracket') {{
        paramLength.value = 50.8;
        paramWidth.value = Math.round(24 * scale * 10) / 10;
        paramHeight.value = 50.8;
        paramThickness.value = Math.round(4.5 * scale * 10) / 10;
      }} else if (item.family === 'u-bracket') {{
        paramLength.value = Math.round(36 * scale * 10) / 10;
        paramWidth.value = Math.round(28 * scale * 10) / 10;
        paramHeight.value = Math.round(28 * scale * 10) / 10;
        paramThickness.value = Math.round(4 * scale * 10) / 10;
      }} else if (item.family === 'flat-mounting-plate') {{
        paramLength.value = Math.round(65 * scale * 10) / 10;
        paramWidth.value = Math.round(34 * scale * 10) / 10;
        paramHeight.value = '';
        paramThickness.value = Math.round(4 * scale * 10) / 10;
      }} else if (item.family === 'spacer-bushing' || item.family === 'hex-standoff') {{
        paramLength.value = '';
        paramWidth.value = item.family === 'hex-standoff' ? Math.round(8 * scale * 10) / 10 : Math.round(14 * scale * 10) / 10;
        paramHeight.value = Math.round(12 * scale * 10) / 10;
        paramThickness.value = '';
      }} else {{
        paramLength.value = Math.round(28 * scale * 10) / 10;
        paramWidth.value = Math.round(20 * scale * 10) / 10;
        paramHeight.value = '';
        paramThickness.value = Math.round(3 * scale * 10) / 10;
      }}
    }}
    function generationParameters() {{
      const value = input => input.value === '' ? null : Number(input.value);
      return {{
        length_mm: value(paramLength),
        width_mm: value(paramWidth),
        height_mm: value(paramHeight),
        thickness_mm: value(paramThickness),
        hole_diameter_mm: value(paramHoleDiameter),
        fillet_radius_mm: value(paramFillet),
        outer_diameter_mm: value(paramWidth)
      }};
    }}
    function renderTemplateTypes(types) {{
      templateTypeList = types;
      const all = ['all', ...types];
      templateTypes.replaceChildren(...all.map(type => {{
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `type-tab${{type === selectedType ? ' active' : ''}}${{type !== selectedType && type === interestedType ? ' interested' : ''}}`;
        button.textContent = type === 'all' ? 'All' : type.replace('-', ' ');
        button.addEventListener('click', () => {{
          selectedType = type;
          interestedType = type === 'all' ? interestedType : type;
          renderTemplateCatalog();
        }});
        return button;
      }}));
    }}
    function renderTemplateCatalog() {{
      if (templateTypeList.length) renderTemplateTypes(templateTypeList);
      const query = templateSearch.value.trim().toLowerCase();
      const fastener = templateFastener.value;
      const filtered = catalogItems.filter(item => {{
        if (selectedType !== 'all' && item.component_type !== selectedType) return false;
        if (fastener && item.fastener !== fastener) return false;
        if (!query) return true;
        const haystack = `${{item.title}} ${{item.description}} ${{item.tags}} ${{item.component_type}} ${{item.family}} ${{item.variant}} ${{item.fastener}}`.toLowerCase();
        return haystack.includes(query);
      }});
      templateSummary.textContent = `${{filtered.length}} of ${{catalogItems.length}} templates shown`;
      templateCatalog.replaceChildren(...filtered.map(item => {{
        const card = document.createElement('article');
        card.className = `template-card${{item.template_id === selectedTemplateId ? ' selected' : ''}}`;
        card.innerHTML = `
          <h3>${{item.title}}</h3>
          <div class="template-meta">
            <span class="chip">${{item.component_type}}</span>
            <span class="chip">${{item.family}}</span>
            <span class="chip">${{item.variant}}</span>
            <span class="chip">${{item.fastener.toUpperCase()}}</span>
          </div>
          <p>${{item.description}}</p>
          <div class="template-actions">
            <button type="button" data-use-template>Use</button>
            <button type="button" data-select-template>Select</button>
          </div>`;
        card.querySelector('[data-use-template]').addEventListener('click', event => {{
          event.stopPropagation();
          setTemplateParameters(item);
          interestedType = item.component_type;
          promptInput.value = templateBrief(item);
          switchTab('generate');
          renderTemplateCatalog();
          promptInput.focus();
        }});
        card.querySelector('[data-select-template]').addEventListener('click', event => {{
          event.stopPropagation();
          setTemplateParameters(item);
          interestedType = item.component_type;
          libraryResults.textContent = JSON.stringify(item, null, 2);
          renderTemplateCatalog();
        }});
        card.addEventListener('click', () => {{
          setTemplateParameters(item);
          interestedType = item.component_type;
          libraryResults.textContent = JSON.stringify(item, null, 2);
          renderTemplateCatalog();
        }});
        return card;
      }}));
    }}
    async function loadTemplateCatalog() {{
      try {{
        const res = await fetch('/api/templates/catalog', {{headers: headers()}});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        catalogItems = Object.values(data.catalog || {{}}).flat();
        renderTemplateTypes(data.component_types || []);
        renderTemplateCatalog();
      }} catch (err) {{
        templateSummary.textContent = `Template catalog unavailable: ${{err.message}}`;
      }}
    }}
    async function loadProjectLibrary() {{
      projectSummary.textContent = 'Loading projects...';
      projectLibrary.replaceChildren();
      const q = encodeURIComponent(projectSearch.value || '');
      const fastener = encodeURIComponent(projectFastener.value || '');
      try {{
        const res = await fetch(`/api/projects?q=${{q}}&fastener=${{fastener}}`, {{headers: headers()}});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        const buckets = data.library || {{}};
        const items = [
          ...(buckets.approved_templates || []),
          ...(buckets.generated_projects || []),
          ...(buckets.revisions || [])
        ];
        const counts = Object.entries(buckets).map(([name, value]) => `${{name.replaceAll('_', ' ')}}: ${{value.length}}`).join(' | ');
        projectSummary.textContent = `${{items.length}} previewable project items. ${{counts}}`;
        projectLibrary.replaceChildren(...items.map(item => card({{...item, name: item.title || item.name || item.library_id || item.version_id}})));
      }} catch (err) {{
        projectSummary.textContent = `Library unavailable: ${{err.message}}`;
      }}
    }}
    async function loadReviewQueue() {{
      reviewQueue.textContent = 'Loading review queue...';
      const q = encodeURIComponent(reviewSearch.value || '');
      const source = encodeURIComponent(reviewSource.value || '');
      try {{
        const res = await fetch(`/api/review-queue?q=${{q}}&source=${{source}}`, {{headers: headers()}});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        reviewQueue.textContent = data.items.length
          ? data.items.map(item => `${{item.review_id}}\\n${{item.name || item.repository}}\\nlicense: ${{item.license}} | compile: ${{item.compile_status}} | preview: ${{item.preview_status}}\\n${{item.html_url || item.repository_url || ''}}`).join('\\n\\n')
          : 'No researched candidates waiting for review.';
      }} catch (err) {{
        reviewQueue.textContent = `Review queue unavailable: ${{err.message}}`;
      }}
    }}
    async function openLatestResult() {{
      const res = await fetch('/api/latest', {{headers: headers()}});
      const data = await res.json();
      if (data.viewer) openPreview(data.viewer, data.latest.title || 'Latest result', 'model');
      else projectSummary.textContent = 'No latest result with STL found yet.';
    }}
    function openPreview(src, title, mode = 'image') {{
      if (mode === 'model') {{
        lightboxImage.style.display = 'none';
        lightboxImage.removeAttribute('src');
        lightboxFrame.style.display = 'block';
        lightboxFrame.src = src;
      }} else {{
        lightboxFrame.style.display = 'none';
        lightboxFrame.removeAttribute('src');
        lightboxImage.style.display = 'block';
        lightboxImage.src = src;
      }}
      lightboxTitle.textContent = title || 'Preview';
      lightbox.classList.add('open');
    }}
    function closePreview() {{
      lightbox.classList.remove('open');
      lightboxImage.removeAttribute('src');
      lightboxFrame.removeAttribute('src');
    }}
    function engineeringText(item) {{
      const checks = item.engineering_checks && item.engineering_checks.checks;
      if (!checks || !checks.length) return '';
      return checks.map(check => `${{check.ok ? 'OK' : 'CHECK'}}  ${{check.name}}: ${{check.message}}`).join('\\n');
    }}
    async function duplicateProject(item) {{
      if (!item.scad) return;
      const title = prompt('New project name', `${{item.name || item.title || 'Model'}} copy`);
      if (!title) return;
      const res = await fetch('/api/duplicate', {{
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({{scad: item.scad, title}})
      }});
      const data = await res.json();
      show(data);
      if (!res.ok) alert(data.error || `HTTP ${{res.status}}`);
    }}
    async function renameProject(item, currentTitle) {{
      if (!item.scad) return;
      const title = prompt('Project title', currentTitle);
      if (!title || title === currentTitle) return;
      const res = await fetch('/api/project/rename', {{
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({{scad: item.scad, title}})
      }});
      const data = await res.json();
      if (!res.ok) {{
        alert(data.error || `HTTP ${{res.status}}`);
        return;
      }}
      if (document.getElementById('tab-library').classList.contains('active')) loadProjectLibrary();
    }}
    async function archiveProjectNow(item, cardEl) {{
      if (!item.scad) return;
      cardEl.classList.add('deleting');
      const parent = cardEl.parentElement;
      const next = cardEl.nextSibling;
      cardEl.remove();
      const res = await fetch('/api/project/delete', {{
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({{scad: item.scad}})
      }});
      const data = await res.json();
      if (!res.ok) {{
        cardEl.classList.remove('deleting');
        if (parent) parent.insertBefore(cardEl, next);
        alert(data.error || `HTTP ${{res.status}}`);
        return;
      }}
    }}
    function requestDeleteProject(item, title, cardEl, event) {{
      if (!item.scad) return;
      if (event && event.ctrlKey) {{
        archiveProjectNow(item, cardEl);
        return;
      }}
      cardEl.classList.add('confirming-delete');
    }}
    function card(item) {{
      const div = document.createElement('article');
      div.className = 'card';
      const title = item.name || item.title || item.iteration || 'Preview';
      const viewer = item.stl ? `/viewer?stl=${{encodeURIComponent(item.stl)}}&scad=${{encodeURIComponent(item.scad || '')}}&title=${{encodeURIComponent(title)}}` : '';
      const imgHref = viewer || item.preview || '#';
      const img = item.preview
        ? `<a class="preview-link" href="${{imgHref}}" title="Open 3D preview"><img src="${{item.preview}}" alt="${{title}}"></a>`
        : `<div class="results-empty" style="min-height: 150px;">${{item.stl ? '3D preview available' : 'No preview image'}}</div>`;
      const dims = item.metrics && item.metrics.dimensions_in
        ? `<pre>${{item.metrics.dimensions_in.x}}" x ${{item.metrics.dimensions_in.y}}" x ${{item.metrics.dimensions_in.z}}"\\n${{item.metrics.dimensions_mm.x}} x ${{item.metrics.dimensions_mm.y}} x ${{item.metrics.dimensions_mm.z}} mm</pre>`
        : '';
      const checks = engineeringText(item);
      div.innerHTML = `${{item.scad ? '<button class="card-delete" type="button" title="Archive project (Ctrl-click skips confirmation)" aria-label="Archive project">&times;</button><div class="delete-confirm"><span>Archive?</span><button type="button" data-confirm-delete>Yes</button><button type="button" data-cancel-delete>Cancel</button></div>' : ''}}${{img}}<div class="body"><div class="card-head"><h2 class="editable-title" title="Click to rename">${{title}}</h2><div class="action-wrap"><button class="action-menu-button" type="button" title="Project actions" aria-label="Project actions">...</button><div class="project-actions">${{item.scad ? `<a href="/project?scad=${{encodeURIComponent(item.scad)}}">Details</a>` : ''}}${{item.scad ? `<a href="${{item.scad}}" download>SCAD Source</a>` : ''}}${{item.cadquery ? `<a href="${{item.cadquery}}" download>CadQuery</a>` : ''}}${{item.step ? `<a href="${{item.step}}" download>STEP</a>` : ''}}${{item.csg ? `<a href="${{item.csg}}" download>CSG</a>` : ''}}${{item.three_mf ? `<a href="${{item.three_mf}}" download>3MF</a>` : ''}}${{item.stl ? `<a href="${{item.stl}}" download>STL</a>` : ''}}${{item.metrics_url ? `<a href="${{item.metrics_url}}" download>Metrics</a>` : ''}}${{item.engineering_checks_url ? `<a href="${{item.engineering_checks_url}}" download>Checks</a>` : ''}}${{item.scad ? `<a href="/api/bundle?scad=${{encodeURIComponent(item.scad)}}" download>Bundle</a>` : ''}}${{viewer ? `<a href="${{viewer}}" data-model-preview>Preview</a>` : ''}}${{item.preview ? `<a href="${{item.preview}}" data-preview>PNG</a>` : ''}}${{item.scad ? `<a href="#" data-duplicate>Duplicate</a>` : ''}}</div></div></div>${{dims}}${{checks ? `<pre>${{checks}}</pre>` : ''}}${{item.error ? `<pre class="error">${{item.error}}</pre>` : ''}}</div>`;
      const deleteButton = div.querySelector('.card-delete');
      if (deleteButton) {{
        deleteButton.addEventListener('click', event => {{
          event.stopPropagation();
          requestDeleteProject(item, title, div, event);
        }});
      }}
      const confirmDelete = div.querySelector('[data-confirm-delete]');
      if (confirmDelete) {{
        confirmDelete.addEventListener('click', event => {{
          event.stopPropagation();
          archiveProjectNow(item, div);
        }});
      }}
      const cancelDelete = div.querySelector('[data-cancel-delete]');
      if (cancelDelete) {{
        cancelDelete.addEventListener('click', event => {{
          event.stopPropagation();
          div.classList.remove('confirming-delete');
        }});
      }}
      const titleEl = div.querySelector('.editable-title');
      if (titleEl && item.scad) {{
        titleEl.addEventListener('click', event => {{
          event.stopPropagation();
          renameProject(item, title);
        }});
      }}
      const actionButton = div.querySelector('.action-menu-button');
      if (actionButton) {{
        actionButton.addEventListener('click', event => {{
          event.preventDefault();
          event.stopPropagation();
          actionButton.closest('.action-wrap').classList.toggle('open');
        }});
      }}
      div.querySelectorAll('a').forEach(link => {{
        link.addEventListener('click', event => {{
          event.stopPropagation();
          if (link.classList.contains('preview-link') && viewer || link.hasAttribute('data-model-preview')) {{
            event.preventDefault();
            openPreview(link.href, title, 'model');
          }} else if (link.classList.contains('preview-link') || link.hasAttribute('data-preview')) {{
            event.preventDefault();
            openPreview(link.href, title, 'image');
          }} else if (link.hasAttribute('data-duplicate')) {{
            event.preventDefault();
            duplicateProject(item);
          }}
        }});
      }});
      div.addEventListener('click', async () => {{
        if (!item.scad) return;
        const res = await fetch(item.scad);
        scad.value = await res.text();
      }});
      return div;
    }}
    function show(data) {{
      raw.textContent = JSON.stringify(data, null, 2);
      if (data.pipeline) {{
        pipeline.textContent = data.pipeline.map(step => {{
          const status = step.ok === false ? 'FAILED' : step.ok === true ? 'OK' : 'INFO';
          return `${{status}}  ${{step.stage}}${{step.model ? ` - ${{step.model}}` : ''}}${{step.source ? ` - ${{step.source}}` : ''}}${{step.seconds ? ` - ${{step.seconds}}s` : ''}}${{step.message ? `\\n${{step.message}}` : ''}}`;
        }}).join('\\n\\n');
      }}
      const items = data.results || (data.preview ? [data] : []);
      if (items.length) {{
        resultsEmpty.style.display = 'none';
        resultsWrap.classList.remove('hidden');
        gallery.replaceChildren(...items.map(card));
        switchTab('results');
        const first = items.find(item => item.scad);
        if (first) fetch(first.scad).then(res => res.text()).then(text => scad.value = text);
      }}
    }}
    async function post(path, body) {{
      const res = await fetch(path, {{method: 'POST', headers: headers(), body: JSON.stringify(body)}});
      const data = await res.json();
      show(data);
      if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
      return data;
    }}
    document.getElementById('generate').addEventListener('click', async event => {{
      event.target.disabled = true;
      pipeline.textContent = 'Starting run...\\n1. Refine prompt\\n2. Generate iterations\\n3. Compile OpenSCAD\\n4. Render PNG previews\\n5. Export STL files';
      try {{
        await post('/api/generate', {{
          prompt: promptInput.value,
          prompt_model: document.getElementById('promptModel').value,
          iteration_model: document.getElementById('iterationModel').value,
          vision_model: document.getElementById('visionModel').value,
          iterations: Number(document.getElementById('iterations').value || 1),
          temperature: Number(document.getElementById('temperature').value || 0.8),
          refine_prompt: document.getElementById('pipelineMode').value !== 'direct',
          use_cache_first: document.getElementById('cacheMode').value === 'cache-first',
          template_id: selectedTemplateInput.value || selectedTemplateId,
          parameters: generationParameters(),
          render: document.getElementById('previewView').value !== 'compile'
        }});
      }} catch (err) {{
        pipeline.textContent = `FAILED\\n${{err.message}}`;
      }} finally {{
        event.target.disabled = false;
      }}
    }});
    async function searchLibrary(eventTarget) {{
      eventTarget.disabled = true;
      libraryResults.textContent = 'Searching approved library and built-in templates...';
      try {{
        const q = encodeURIComponent(promptInput.value || '');
        const res = await fetch(`/api/templates/search?q=${{q}}`, {{headers: headers()}});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        libraryResults.textContent = data.items.length
          ? data.items.map(item => `${{item.kind === 'builtin_template' ? 'TEMPLATE' : 'APPROVED'}}  score ${{item.score || 0}}\\n${{item.component_type || 'approved'}} / ${{item.family || item.library_id || ''}} / ${{item.variant || ''}} / ${{item.fastener || ''}}\\n${{item.title}}\\n${{item.description || item.scad || ''}}\\n${{item.tags || ''}}`).join('\\n\\n')
          : 'No approved library or built-in template matches yet.';
      }} catch (err) {{
        libraryResults.textContent = `FAILED\\n${{err.message}}`;
      }} finally {{
        eventTarget.disabled = false;
      }}
    }}
    async function researchScad(eventTarget) {{
      eventTarget.disabled = true;
      libraryResults.textContent = 'Researching public SCAD candidates...';
      try {{
        const res = await fetch('/api/research/scad', {{
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({{query: promptInput.value || ''}})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        libraryResults.textContent = data.candidates.length
          ? data.candidates.map(item => `${{item.name}} - ${{item.repository}}\\n${{item.html_url}}\\nlicense: ${{item.license}}`).join('\\n\\n')
          : 'No public SCAD candidates found.';
      }} catch (err) {{
        libraryResults.textContent = `FAILED\\n${{err.message}}`;
      }} finally {{
        eventTarget.disabled = false;
      }}
    }}
    async function previewEditorScad(eventTarget) {{
      eventTarget.disabled = true;
      pipeline.textContent = 'Rendering editor SCAD with OpenSCAD...';
      try {{
        await post('/api/preview', {{scad: scad.value}});
      }} catch (err) {{
        pipeline.textContent = `FAILED\\n${{err.message}}`;
      }} finally {{
        eventTarget.disabled = false;
      }}
    }}
    function loadSampleScad() {{
      scad.value = sampleScad;
      pipeline.textContent = 'Sample SCAD loaded. Choose Preview editor SCAD from the tool menu to render it.';
    }}
    document.getElementById('runTool').addEventListener('click', async event => {{
      const action = document.getElementById('toolAction').value;
      if (action === 'search-library') await searchLibrary(event.target);
      if (action === 'research-scad') await researchScad(event.target);
      if (action === 'preview-editor') await previewEditorScad(event.target);
      if (action === 'load-sample') loadSampleScad();
    }});
    document.getElementById('previewEditorButton').addEventListener('click', async event => previewEditorScad(event.target));
    document.getElementById('loadSampleButton').addEventListener('click', loadSampleScad);
    document.getElementById('refreshProjects').addEventListener('click', loadProjectLibrary);
    document.getElementById('openLatest').addEventListener('click', openLatestResult);
    document.getElementById('refreshReview').addEventListener('click', loadReviewQueue);
    projectSearch.addEventListener('change', loadProjectLibrary);
    projectFastener.addEventListener('change', loadProjectLibrary);
    reviewSearch.addEventListener('change', loadReviewQueue);
    reviewSource.addEventListener('change', loadReviewQueue);
    document.querySelectorAll('.app-tab').forEach(tab => {{
      tab.addEventListener('click', () => {{
        switchTab(tab.dataset.tab);
        if (tab.dataset.tab === 'library') loadProjectLibrary();
        if (tab.dataset.tab === 'review') loadReviewQueue();
      }});
    }});
    templateSearch.addEventListener('input', renderTemplateCatalog);
    templateFastener.addEventListener('change', renderTemplateCatalog);
    loadTemplateCatalog();
    document.getElementById('closeLightbox').addEventListener('click', closePreview);
    lightbox.addEventListener('click', event => {{
      if (event.target === lightbox) closePreview();
    }});
    document.addEventListener('keydown', event => {{
      if (event.key === 'Escape') closePreview();
    }});
  </script>
</body>
</html>"""


def fmt_dims(item):
    dims = (item.get("metrics") or {}).get("dimensions_mm") or {}
    if not dims:
        return "dimensions unavailable"
    return f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} mm"


def checks_summary(item):
    checks = ((item.get("engineering_checks") or {}).get("checks") or [])
    if not checks:
        return "No engineering checks recorded."
    return "\n".join(f"{'OK' if check.get('ok') else 'CHECK'}  {check.get('name')}: {check.get('message')}" for check in checks)


def manifest_for_scad(scad_url):
    return read_version_manifest(scad_url) or synthetic_manifest_for_scad(scad_url, "Project")


def project_page(scad_url):
    item = manifest_for_scad(scad_url)
    if not item:
        return ""
    title = html.escape(item.get("title") or item.get("version_id") or "Project")
    viewer = f"/viewer?stl={quote(item.get('stl', ''))}&scad={quote(item.get('scad', ''))}&title={quote(item.get('title', 'Project'))}" if item.get("stl") else ""
    versions, _ = version_manifests_for_root(item.get("scad", scad_url))
    version_rows = []
    previous = ""
    for index, version in enumerate(versions, 1):
        name = html.escape(version.get("title") or version.get("version_id") or f"Version {index}")
        dims = html.escape(fmt_dims(version))
        links = []
        if version.get("stl"):
            links.append(f'<a href="/viewer?stl={quote(version.get("stl", ""))}&scad={quote(version.get("scad", ""))}&title={quote(version.get("title", name))}">View</a>')
        if previous and version.get("scad"):
            links.append(f'<a href="/compare?left={quote(previous)}&right={quote(version.get("scad", ""))}">Compare</a>')
        if version.get("scad"):
            links.append(f'<a href="{html.escape(version.get("scad"))}" download>SCAD</a>')
        if version.get("step"):
            links.append(f'<a href="{html.escape(version.get("step"))}" download>STEP</a>')
        if version.get("stl"):
            links.append(f'<a href="{html.escape(version.get("stl"))}" download>STL</a>')
        version_rows.append(f"<li><strong>v{index}: {name}</strong><span>{dims}</span><div>{' '.join(links)}</div></li>")
        previous = version.get("scad") or previous
    preview = f'<iframe src="{viewer}" title="3D preview"></iframe>' if viewer else '<div class="empty">No STL preview available.</div>'
    downloads = []
    for label, key in (("Bundle", "bundle"), ("SCAD", "scad"), ("STEP", "step"), ("3MF", "three_mf"), ("STL", "stl"), ("Metrics", "metrics_url"), ("Checks", "engineering_checks_url")):
        if key == "bundle" and item.get("scad"):
            downloads.append(f'<a href="/api/bundle?scad={quote(item.get("scad", ""))}" download>{label}</a>')
        elif item.get(key):
            downloads.append(f'<a href="{html.escape(item.get(key))}" download>{label}</a>')
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; background: #101418; color: #f4f7f8; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    main {{ width: min(1180px, calc(100vw - 28px)); margin: 0 auto; padding: 18px 0 36px; }}
    a {{ color: #72e0b7; }}
    .top {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 12px; }}
    h1 {{ margin: 0; font-size: 22px; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 12px; }}
    iframe {{ width: 100%; height: 640px; border: 1px solid #34414b; border-radius: 8px; background: #050708; }}
    .panel {{ border: 1px solid #34414b; background: #171d22; border-radius: 8px; padding: 12px; margin-bottom: 12px; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .links a {{ border: 1px solid rgba(114,224,183,.5); border-radius: 6px; padding: 6px 9px; text-decoration: none; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-size: 12px; color: #d8e2e5; }}
    ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }}
    li {{ border: 1px solid #26343a; border-radius: 7px; padding: 8px; display: grid; gap: 5px; }}
    li span {{ color: #b9ffe5; font-size: 12px; }}
    @media (max-width: 820px) {{ .grid {{ grid-template-columns: 1fr; }} iframe {{ height: 480px; }} }}
  </style>
</head>
<body>
  <main>
    <div class="top"><h1>{title}</h1><a href="/">Back to app</a></div>
    <div class="grid">
      <section>{preview}</section>
      <aside>
        <section class="panel"><strong>Dimensions</strong><pre>{html.escape(fmt_dims(item))}</pre></section>
        <section class="panel"><strong>Downloads</strong><div class="links">{''.join(downloads)}</div></section>
        <section class="panel"><strong>Engineering Checks</strong><pre>{html.escape(checks_summary(item))}</pre></section>
        <section class="panel"><strong>Version History</strong><ul>{''.join(version_rows) or '<li>No versions found.</li>'}</ul></section>
      </aside>
    </div>
  </main>
</body>
</html>"""


def compare_page(left_scad, right_scad):
    left = manifest_for_scad(left_scad)
    right = manifest_for_scad(right_scad)
    if not left or not right:
        return ""
    def pane(item, label):
        title = html.escape(item.get("title") or label)
        viewer = f"/viewer?stl={quote(item.get('stl', ''))}&scad={quote(item.get('scad', ''))}&title={quote(item.get('title', label))}" if item.get("stl") else ""
        preview = f'<iframe src="{viewer}" title="{label}"></iframe>' if viewer else '<div class="empty">No STL preview.</div>'
        return f'<section class="panel"><h2>{label}: {title}</h2>{preview}<pre>{html.escape(fmt_dims(item))}</pre><pre>{html.escape(checks_summary(item))}</pre></section>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Version Compare</title>
<style>
body {{ margin: 0; background: #101418; color: #f4f7f8; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
main {{ width: min(1380px, calc(100vw - 28px)); margin: 0 auto; padding: 18px 0 36px; }}
a {{ color: #72e0b7; }} h1 {{ margin: 0 0 12px; font-size: 22px; }}
.grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
.panel {{ border: 1px solid #34414b; background: #171d22; border-radius: 8px; padding: 12px; }}
iframe {{ width: 100%; height: 520px; border: 1px solid #34414b; border-radius: 8px; background: #050708; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; color: #d8e2e5; font-size: 12px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style></head><body><main><a href="/">Back to app</a><h1>Version Compare</h1><div class="grid">{pane(left, "Left")}{pane(right, "Right")}</div></main></body></html>"""


def viewer_page(stl_url, scad_url, title):
    safe_stl = html.escape(stl_url, quote=True)
    safe_scad = html.escape(scad_url, quote=True)
    safe_title = html.escape(title or "STL Preview")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; height: 100%; overflow: hidden; background: #050708; color: #edf6f4; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    .workspace {{ display: grid; grid-template-columns: minmax(340px, 1fr) 320px; height: 100vh; }}
    #viewer {{ min-width: 0; height: 100vh; position: relative; }}
    .hud {{ position: absolute; left: 12px; top: 10px; z-index: 2; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .dimension-badge {{ position: absolute; left: 12px; bottom: 12px; z-index: 2; border: 1px solid rgba(114, 224, 183, .45); border-radius: 7px; background: rgba(15, 22, 26, .88); color: #d6fff0; padding: 8px 10px; font-size: 12px; line-height: 1.35; }}
    .hud span, .hud button, .hud select {{ border: 1px solid rgba(114, 224, 183, .45); border-radius: 6px; background: rgba(15, 22, 26, .88); color: #edf6f4; padding: 6px 9px; font: inherit; }}
    .hud button {{ width: 38px; height: 36px; display: inline-grid; place-items: center; cursor: pointer; color: #72e0b7; font-size: 19px; font-weight: 800; line-height: 1; transition: background .12s ease, border-color .12s ease, color .12s ease, transform .08s ease, box-shadow .12s ease; }}
    .hud button:hover, button.sidebtn:hover {{ border-color: rgba(114, 224, 183, .9); color: #b9ffe5; box-shadow: 0 0 0 2px rgba(114, 224, 183, .12); }}
    .hud button:active, button.sidebtn:active {{ transform: translateY(1px); }}
    .hud button.active {{ background: #1f4638; border-color: rgba(114, 224, 183, 1); color: #d4ffef; box-shadow: 0 0 0 2px rgba(114, 224, 183, .22), inset 0 0 18px rgba(114, 224, 183, .1); }}
    .hud button:disabled, button.sidebtn:disabled {{ opacity: .55; cursor: wait; }}
    .hud select {{ min-width: 190px; max-width: min(360px, calc(100vw - 28px)); font-weight: 700; }}
    .side {{ border-left: 1px solid #26343a; background: #10171b; height: 100vh; overflow: auto; padding: 10px; }}
    h1 {{ font-size: 16px; margin: 0 0 10px; letter-spacing: 0; }}
    h2 {{ font-size: 13px; margin: 14px 0 6px; color: #b7c8ce; font-weight: 700; letter-spacing: 0; }}
    textarea {{ width: 100%; min-height: 155px; resize: vertical; border: 1px solid #304149; border-radius: 6px; background: #090f12; color: #edf6f4; padding: 9px; font: inherit; line-height: 1.35; }}
    button.sidebtn {{ width: 100%; margin-top: 8px; border: 1px solid rgba(114, 224, 183, .5); border-radius: 6px; background: #172126; color: #72e0b7; padding: 8px; cursor: pointer; font: inherit; font-weight: 700; text-align: left; transition: background .12s ease, border-color .12s ease, color .12s ease, transform .08s ease, box-shadow .12s ease; }}
    button.sidebtn .sym {{ display: inline-grid; place-items: center; width: 22px; margin-right: 6px; color: #b9ffe5; font-weight: 900; }}
    pre {{ margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #d8e2e5; font-size: 12px; line-height: 1.45; }}
    .hint {{ color: #91a4aa; font-size: 12px; line-height: 1.45; margin: 0 0 8px; }}
    .statusline {{ color: #b9ffe5; font-size: 12px; line-height: 1.35; min-height: 18px; margin: 6px 0 8px; }}
    .box {{ border: 1px solid #26343a; border-radius: 8px; padding: 9px; background: #0c1316; }}
    .history-list {{ display: grid; gap: 6px; max-height: 180px; overflow: auto; padding: 6px; }}
    .history-item {{ display: grid; gap: 4px; border: 1px solid #223038; border-radius: 7px; padding: 7px; background: #091014; }}
    .history-item.current {{ border-color: rgba(114, 224, 183, .75); background: #10201d; }}
    .history-top {{ display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }}
    .history-name {{ font-weight: 800; color: #edf6f4; font-size: 12px; }}
    .history-dims {{ color: #b9ffe5; font-size: 11px; white-space: nowrap; }}
    .history-note {{ color: #91a4aa; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .history-actions {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .history-actions a {{ border: 1px solid rgba(114, 224, 183, .45); border-radius: 5px; color: #72e0b7; padding: 3px 6px; font-size: 11px; text-decoration: none; }}
    .history-actions a:hover {{ border-color: rgba(114, 224, 183, .9); color: #b9ffe5; }}
    @media (max-width: 680px) {{
      .workspace {{ grid-template-columns: 1fr; grid-template-rows: minmax(360px, 58vh) 42vh; }}
      #viewer, .side {{ height: auto; }}
      .side {{ border-left: 0; border-top: 1px solid #26343a; }}
    }}
  </style>
  <script type="importmap">
    {{"imports": {{"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}}}
  </script>
</head>
<body>
  <div class="workspace">
    <div id="viewer">
      <div class="hud">
        <select id="versionSelect" aria-label="Version"><option>{safe_title}</option></select>
        <button id="selectMode" type="button" aria-label="Pick point" title="Pick point: click a surface to capture its point and normal">o</button>
        <button id="measureMode" type="button" aria-label="Measure distance" title="Measure distance: click two points">&lt;-&gt;</button>
        <button id="resetMeasure" type="button" aria-label="Clear measurement" title="Clear selected measurement markers">x</button>
        <button id="reset" type="button" aria-label="Fit view" title="Fit model in view">[]</button>
      </div>
    </div>
    <aside class="side">
      <h1>{safe_title}</h1>
      <p class="hint">Use Select to click a surface. Use Measure to click two points and capture distance.</p>
      <div class="statusline" id="toolStatus">Pick Point mode active. Click the model to capture context.</div>
      <h2>Version History</h2>
      <div class="box history-list" id="historyLine">Loading history...</div>
      <button class="sidebtn" id="saveApproved" type="button" title="Save this version to the approved library"><span class="sym">☆</span>Save Approved</button>
      <div class="box" style="margin-top: 8px;"><pre id="approvalResult">Not saved to approved library yet.</pre></div>
      <h2>Selected Context</h2>
      <div class="box"><pre id="selection">No selected surface point yet.</pre></div>
      <button class="sidebtn" id="addSelection" type="button" title="Add picked point coordinates to notes"><span class="sym">◎</span>Add Point</button>
      <h2>Measurement</h2>
      <div class="box"><pre id="measurement">No measurement yet.</pre></div>
      <button class="sidebtn" id="addMeasure" type="button" title="Add measured distance to notes"><span class="sym">↔</span>Add Distance</button>
      <h2>Iteration Notes</h2>
      <textarea id="notes" placeholder="Example: vertical flange holes need to move 5 mm lower; selected point shows current hole edge."></textarea>
      <button class="sidebtn" id="copyNotes" type="button" title="Copy iteration notes for reuse"><span class="sym">⧉</span>Copy Notes</button>
      <h2>Revise Model</h2>
      <textarea id="revisionRequest" placeholder="Example: move the vertical flange holes 5 mm lower and increase bracket width to 30 mm."></textarea>
      <button class="sidebtn" id="createRevision" type="button" title="Create a new version from notes and measurements"><span class="sym">↻</span>Create Revision</button>
      <div class="box" style="margin-top: 8px;"><pre id="revisionResult">No revision created yet.</pre></div>
      <h2>Iteration Chat</h2>
      <div class="box"><pre id="chatLog">Ask about the current iteration, selected surface, or measurement.</pre></div>
      <textarea id="chatInput" placeholder="Example: Are these hole positions reasonable for an M4 2 inch L bracket?"></textarea>
      <button class="sidebtn" id="sendChat" type="button" title="Ask AI using the selected point, measurements, and notes"><span class="sym">?</span>Ask AI</button>
    </aside>
  </div>
  <script type="module">
    import * as THREE from 'three';
    import {{ STLLoader }} from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/STLLoader.js';
    import {{ OrbitControls }} from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js';

    const container = document.getElementById('viewer');
    const selectionEl = document.getElementById('selection');
    const measurementEl = document.getElementById('measurement');
    const notesEl = document.getElementById('notes');
    const chatLog = document.getElementById('chatLog');
    const chatInput = document.getElementById('chatInput');
    const revisionRequest = document.getElementById('revisionRequest');
    const revisionResult = document.getElementById('revisionResult');
    const historyLine = document.getElementById('historyLine');
    const approvalResult = document.getElementById('approvalResult');
    const versionSelect = document.getElementById('versionSelect');
    const toolStatus = document.getElementById('toolStatus');
    const dimensionBadge = document.getElementById('dimensionBadge');
    const notesKey = `scad-review-notes:${{location.search}}`;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050708);
    const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 5000);
    const renderer = new THREE.WebGLRenderer({{ antialias: true }});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const markers = [];
    const measureMarkers = [];
    let mesh;
    let mode = 'select';
    let lastSelection = '';
    let lastMeasurement = '';
    const measurePoints = [];

    scene.add(new THREE.HemisphereLight(0xffffee, 0x263238, 2.0));
    const key = new THREE.DirectionalLight(0xffffff, 2.8);
    key.position.set(60, -80, 120);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x9be7ff, 0.85);
    fill.position.set(-80, 70, 60);
    scene.add(fill);

    notesEl.value = localStorage.getItem(notesKey) || '';
    notesEl.addEventListener('input', () => localStorage.setItem(notesKey, notesEl.value));

    function fmt(v) {{
      return `${{v.x.toFixed(2)}}, ${{v.y.toFixed(2)}}, ${{v.z.toFixed(2)}} mm`;
    }}
    function addMarker(point, color = 0x72e0b7, list = markers) {{
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(1.25, 24, 12),
        new THREE.MeshBasicMaterial({{ color }})
      );
      marker.position.copy(point);
      scene.add(marker);
      list.push(marker);
    }}
    function clearList(list) {{
      while (list.length) scene.remove(list.pop());
    }}
    function setStatus(message) {{
      toolStatus.textContent = message;
    }}
    async function copyText(text) {{
      if (!text.trim()) throw new Error('No notes to copy yet.');
      if (navigator.clipboard && window.isSecureContext) {{
        await navigator.clipboard.writeText(text);
        return;
      }}
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.left = '-9999px';
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      if (!ok) throw new Error('Clipboard blocked. Select the notes text and copy manually.');
    }}
    function setMode(next) {{
      mode = next;
      document.getElementById('selectMode').classList.toggle('active', mode === 'select');
      document.getElementById('measureMode').classList.toggle('active', mode === 'measure');
      setStatus(mode === 'select'
        ? 'Pick Point mode active. Click a face, edge, or hole area to capture context.'
        : 'Measure Distance mode active. Click two points on the model.');
    }}
    function viewerUrlForVersion(version) {{
      return version.stl && version.scad
        ? `/viewer?stl=${{encodeURIComponent(version.stl)}}&scad=${{encodeURIComponent(version.scad)}}&title=${{encodeURIComponent(version.title || version.version_id)}}`
        : '';
    }}
    function esc(value) {{
      return String(value || '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }}[ch]));
    }}
    function dimsText(version) {{
      const dims = version.metrics && version.metrics.dimensions_mm;
      if (!dims) return '';
      return `${{dims.x}} x ${{dims.y}} x ${{dims.z}} mm`;
    }}
    function displayVersionTitle(version, index, versions) {{
      if (index === 0 || version.kind === 'existing') return 'Original';
      if (version.kind === 'revision') {{
        const revisionNumber = versions.slice(0, index + 1).filter(item => item.kind === 'revision').length;
        return `Revision ${{revisionNumber}}`;
      }}
      const raw = String(version.title || version.version_id || `Version ${{index + 1}}`);
      return raw
        .replace(/\\s+Revision(\\s+Revision)+/gi, ' Revision')
        .replace(/^Iteration\\s+(\\d+)\\s+Revision$/i, 'Revision for Iteration $1');
    }}
    function versionLabel(version, index, versions) {{
      const dims = dimsText(version);
      return `v${{index + 1}} ${{displayVersionTitle(version, index, versions)}}${{dims ? ` - ${{dims}}` : ''}}`;
    }}
    async function loadHistory(scadUrl = '{safe_scad}') {{
      if (!scadUrl) {{
        historyLine.textContent = 'No SCAD source attached to this preview.';
        versionSelect.innerHTML = `<option>{safe_title}</option>`;
        return;
      }}
      try {{
        const res = await fetch(`/api/history?scad=${{encodeURIComponent(scadUrl)}}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        if (!data.versions.length) {{
          historyLine.textContent = 'No saved history yet.';
          versionSelect.innerHTML = `<option>{safe_title}</option>`;
          return;
        }}
        versionSelect.replaceChildren(...data.versions.map((version, index) => {{
          const option = document.createElement('option');
          option.value = viewerUrlForVersion(version);
          option.textContent = versionLabel(version, index, data.versions);
          option.selected = version.scad === scadUrl;
          return option;
        }}));
        historyLine.innerHTML = data.versions.map((version, index) => {{
          const name = versionLabel(version, index, data.versions);
          const dims = dimsText(version);
          const note = String(version.request || version.notes || version.source || '').replace(/\\s+/g, ' ').trim();
          const viewer = viewerUrlForVersion(version);
          const links = [
            viewer ? `<a href="${{esc(viewer)}}" title="Open this version">View</a>` : '',
            version.scad ? `<a href="${{esc(version.scad)}}" download title="Download SCAD source">SCAD</a>` : '',
            version.step ? `<a href="${{esc(version.step)}}" download title="Download STEP">STEP</a>` : '',
            version.stl ? `<a href="${{esc(version.stl)}}" download title="Download STL">STL</a>` : ''
          ].filter(Boolean).join(' ');
          return `<div class="history-item${{version.scad === scadUrl ? ' current' : ''}}">
            <div class="history-top"><span class="history-name">${{esc(name)}}</span>${{dims ? `<span class="history-dims">${{esc(dims)}}</span>` : ''}}</div>
            ${{note ? `<div class="history-note" title="${{esc(note)}}">${{esc(note.slice(0, 90))}}</div>` : ''}}
            <div class="history-actions">${{links}}</div>
          </div>`;
        }}).join('');
      }} catch (err) {{
        historyLine.textContent = `History unavailable: ${{err.message}}`;
      }}
    }}
    function frameGeometry(geometry) {{
      geometry.computeBoundingBox();
      geometry.computeVertexNormals();
      const box = geometry.boundingBox;
      const center = new THREE.Vector3();
      const size = new THREE.Vector3();
      box.getCenter(center);
      box.getSize(size);
      geometry.translate(-center.x, -center.y, -center.z);
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      dimensionBadge.textContent = `Bounding box: ${{size.x.toFixed(2)}} x ${{size.y.toFixed(2)}} x ${{size.z.toFixed(2)}} mm | ${{(size.x / 25.4).toFixed(3)}} x ${{(size.y / 25.4).toFixed(3)}} x ${{(size.z / 25.4).toFixed(3)}} in`;
      camera.position.set(maxDim * 1.15, -maxDim * 1.65, maxDim * 1.1);
      camera.near = maxDim / 100;
      camera.far = maxDim * 20;
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();
    }}

    new STLLoader().load('{safe_stl}', geometry => {{
      frameGeometry(geometry);
      const material = new THREE.MeshStandardMaterial({{ color: 0xffd21f, roughness: 0.45, metalness: 0.05 }});
      mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);
      const grid = new THREE.GridHelper(120, 12, 0x2c3b42, 0x19252b);
      grid.rotation.x = Math.PI / 2;
      scene.add(grid);
    }}, undefined, error => {{
      container.textContent = 'Unable to load STL preview.';
      console.error(error);
    }});

    renderer.domElement.addEventListener('click', event => {{
      if (!mesh) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(mesh, false)[0];
      if (!hit) return;
      if (mode === 'measure') {{
        measurePoints.push(hit.point.clone());
        addMarker(hit.point, 0x9be7ff, measureMarkers);
        if (measurePoints.length > 2) {{
          measurePoints.splice(0, measurePoints.length - 2);
          clearList(measureMarkers);
          measurePoints.forEach(point => addMarker(point, 0x9be7ff, measureMarkers));
        }}
        if (measurePoints.length === 2) {{
          const distance = measurePoints[0].distanceTo(measurePoints[1]);
          lastMeasurement = `Measure: ${{distance.toFixed(2)}} mm (${{(distance / 25.4).toFixed(3)}} in)\\nA: ${{fmt(measurePoints[0])}}\\nB: ${{fmt(measurePoints[1])}}`;
          measurementEl.textContent = lastMeasurement;
          setStatus(`Distance captured: ${{distance.toFixed(2)}} mm. Use Add Distance To Notes when it is useful.`);
        }} else {{
          measurementEl.textContent = `Measure A: ${{fmt(measurePoints[0])}}\\nClick a second point.`;
          setStatus('First measurement point captured. Click the second point.');
        }}
      }} else {{
        clearList(markers);
        addMarker(hit.point);
        lastSelection = `Selected surface point: ${{fmt(hit.point)}}\\nFace normal: ${{hit.face.normal.x.toFixed(2)}}, ${{hit.face.normal.y.toFixed(2)}}, ${{hit.face.normal.z.toFixed(2)}}`;
        selectionEl.textContent = lastSelection;
        setStatus('Point captured. Use Add Point To Notes if this is relevant.');
      }}
    }});

    document.getElementById('reset').addEventListener('click', () => {{
      if (mesh) frameGeometry(mesh.geometry);
    }});
    document.getElementById('selectMode').addEventListener('click', () => setMode('select'));
    document.getElementById('measureMode').addEventListener('click', () => setMode('measure'));
    document.getElementById('resetMeasure').addEventListener('click', () => {{
      measurePoints.length = 0;
      lastMeasurement = '';
      measurementEl.textContent = 'No measurement yet.';
      clearList(measureMarkers);
      setStatus('Measurement cleared.');
    }});
    document.getElementById('addSelection').addEventListener('click', () => {{
      if (!lastSelection) {{
        setStatus('Pick a point on the model first.');
        return;
      }}
      notesEl.value = `${{notesEl.value.trim()}}\\n\\n${{lastSelection}}`.trim();
      notesEl.dispatchEvent(new Event('input'));
      setStatus('Selected point added to notes.');
    }});
    document.getElementById('addMeasure').addEventListener('click', () => {{
      if (!lastMeasurement) {{
        setStatus('Measure two points first.');
        return;
      }}
      notesEl.value = `${{notesEl.value.trim()}}\\n\\n${{lastMeasurement}}`.trim();
      notesEl.dispatchEvent(new Event('input'));
      setStatus('Measurement added to notes.');
    }});
    document.getElementById('copyNotes').addEventListener('click', async () => {{
      const payload = `Iteration review for {safe_title}\\nSTL: {safe_stl}\\n\\n${{notesEl.value}}`;
      try {{
        await copyText(payload);
        setStatus('Notes copied.');
      }} catch (err) {{
        notesEl.focus();
        notesEl.select();
        setStatus(err.message);
      }}
    }});
    document.getElementById('saveApproved').addEventListener('click', async event => {{
      if (!'{safe_scad}') {{
        approvalResult.textContent = 'No SCAD source attached to this preview.';
        return;
      }}
      event.target.disabled = true;
      const oldLabel = event.target.innerHTML;
      event.target.innerHTML = '<span class="sym">⋯</span>Saving';
      setStatus('Saving this version to the approved library...');
      approvalResult.textContent = 'Saving approved version...';
      try {{
        const headers = {{'Content-Type': 'application/json'}};
        const savedToken = localStorage.getItem('scadAiToken');
        if (savedToken) headers.Authorization = `Bearer ${{savedToken}}`;
        const res = await fetch('/api/library/approve', {{
          method: 'POST',
          headers,
          body: JSON.stringify({{
            title: '{safe_title}',
            scad: '{safe_scad}',
            notes: notesEl.value,
            tags: revisionRequest.value
          }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        approvalResult.textContent = `Saved: ${{data.item.title}}\\n${{data.item.library_id}}\\n${{data.item.scad || ''}}`;
        setStatus('Approved version saved.');
      }} catch (err) {{
        approvalResult.textContent = `Save failed: ${{err.message}}`;
        setStatus(`Save failed: ${{err.message}}`);
      }} finally {{
        event.target.disabled = false;
        event.target.innerHTML = oldLabel;
      }}
    }});
    document.getElementById('createRevision').addEventListener('click', async event => {{
      const request = revisionRequest.value.trim();
      if (!request && !notesEl.value.trim() && !lastSelection && !lastMeasurement) return;
      event.target.disabled = true;
      const oldLabel = event.target.innerHTML;
      event.target.innerHTML = '<span class="sym">⋯</span>Creating';
      setStatus('Creating revised model from the current notes...');
      revisionResult.textContent = 'Creating revised model...';
      try {{
        const headers = {{'Content-Type': 'application/json'}};
        const savedToken = localStorage.getItem('scadAiToken');
        if (savedToken) headers.Authorization = `Bearer ${{savedToken}}`;
        const res = await fetch('/api/revise', {{
          method: 'POST',
          headers,
          body: JSON.stringify({{
            title: '{safe_title}',
            stl: '{safe_stl}',
            scad: '{safe_scad}',
            notes: notesEl.value,
            selection: lastSelection,
            measurement: lastMeasurement,
            request
          }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        const links = [
          data.viewer ? ['3D Preview', data.viewer] : null,
          data.preview ? ['PNG', data.preview] : null,
          data.scad ? ['SCAD', data.scad] : null,
          data.step ? ['STEP', data.step] : null,
          data.stl ? ['STL', data.stl] : null
        ].filter(Boolean).map(([label, href]) => `<a href="${{href}}">${{label}}</a>`).join('\\n');
        revisionResult.innerHTML = `Revision created.\\n${{links}}`;
        setStatus('Revision created. Opening the new version...');
        if (data.scad) loadHistory(data.scad);
        if (data.viewer) {{
          revisionResult.textContent = 'Revision created. Opening new version...';
          window.location.href = data.viewer;
        }}
      }} catch (err) {{
        revisionResult.textContent = `Revision failed: ${{err.message}}`;
        setStatus(`Revision failed: ${{err.message}}`);
      }} finally {{
        event.target.disabled = false;
        event.target.innerHTML = oldLabel;
      }}
    }});
    document.getElementById('sendChat').addEventListener('click', async event => {{
      const question = chatInput.value.trim();
      if (!question) return;
      event.target.disabled = true;
      const oldLabel = event.target.innerHTML;
      event.target.innerHTML = '<span class="sym">⋯</span>Asking';
      setStatus('Asking AI about this iteration...');
      chatLog.textContent = `${{chatLog.textContent}}\\n\\nYou: ${{question}}\\n\\nAI: thinking...`;
      try {{
        const headers = {{'Content-Type': 'application/json'}};
        const savedToken = localStorage.getItem('scadAiToken');
        if (savedToken) headers.Authorization = `Bearer ${{savedToken}}`;
        const res = await fetch('/api/iteration-chat', {{
          method: 'POST',
          headers,
          body: JSON.stringify({{
            title: '{safe_title}',
            stl: '{safe_stl}',
            notes: notesEl.value,
            selection: lastSelection,
            measurement: lastMeasurement,
            question
          }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
        chatLog.textContent = chatLog.textContent.replace(/AI: thinking\\.\\.\\.$/, `AI: ${{data.answer}}`);
        chatInput.value = '';
        setStatus('AI response added.');
      }} catch (err) {{
        chatLog.textContent = chatLog.textContent.replace(/AI: thinking\\.\\.\\.$/, `AI: ${{err.message}}`);
        setStatus(`AI request failed: ${{err.message}}`);
      }} finally {{
        event.target.disabled = false;
        event.target.innerHTML = oldLabel;
      }}
    }});
    versionSelect.addEventListener('change', () => {{
      if (versionSelect.value) window.location.href = versionSelect.value;
    }});
    setMode('select');
    loadHistory();
    window.addEventListener('resize', () => {{
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    }});
    renderer.setAnimationLoop(() => {{
      controls.update();
      renderer.render(scene, camera);
    }});
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-scad-ai-generator/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            body = page().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/viewer":
            query = parse_qs(parsed.query)
            stl_url = (query.get("stl") or [""])[0]
            scad_url = (query.get("scad") or [""])[0]
            title = (query.get("title") or ["STL Preview"])[0]
            if not stl_url.startswith("/artifacts/") or not stl_url.endswith(".stl"):
                write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_stl_url"})
                return
            if scad_url and (not scad_url.startswith("/artifacts/") or not scad_url.endswith(".scad")):
                write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_scad_url"})
                return
            body = viewer_page(stl_url, scad_url, title).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/project":
            query = parse_qs(parsed.query)
            scad_url = (query.get("scad") or [""])[0]
            if not artifact_path_from_url(scad_url, {".scad"}):
                write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_scad_url"})
                return
            html_body = project_page(scad_url)
            if not html_body:
                write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "project_not_found"})
                return
            body = html_body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/compare":
            query = parse_qs(parsed.query)
            left = (query.get("left") or [""])[0]
            right = (query.get("right") or [""])[0]
            if not artifact_path_from_url(left, {".scad"}) or not artifact_path_from_url(right, {".scad"}):
                write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_compare_scad_url"})
                return
            html_body = compare_page(left, right)
            if not html_body:
                write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "compare_not_found"})
                return
            body = html_body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/history":
            query = parse_qs(parsed.query)
            scad_url = (query.get("scad") or [""])[0]
            if not artifact_path_from_url(scad_url, {".scad"}):
                write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_scad_url"})
                return
            versions, root_scad = version_manifests_for_root(scad_url)
            write_json(self, HTTPStatus.OK, {"ok": True, "root_scad": root_scad, "versions": versions})
            return
        if path == "/api/projects":
            query = parse_qs(parsed.query)
            write_json(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "library": project_library(
                        query=(query.get("q") or [""])[0],
                        component_type=(query.get("component_type") or [""])[0],
                        fastener=(query.get("fastener") or [""])[0],
                        source=(query.get("source") or [""])[0],
                    ),
                },
            )
            return
        if path == "/api/review-queue":
            query = parse_qs(parsed.query)
            write_json(self, HTTPStatus.OK, {"ok": True, "items": review_queue_items(query=(query.get("q") or [""])[0], source=(query.get("source") or [""])[0])})
            return
        if path == "/api/latest":
            versions = all_version_manifests()
            latest = versions[0] if versions else {}
            viewer = f"/viewer?stl={quote(latest.get('stl', ''))}&scad={quote(latest.get('scad', ''))}&title={quote(latest.get('title', 'Latest'))}" if latest.get("stl") else ""
            write_json(self, HTTPStatus.OK, {"ok": True, "latest": latest, "viewer": viewer})
            return
        if path == "/api/bundle":
            query = parse_qs(parsed.query)
            scad_url = (query.get("scad") or [""])[0]
            bundle_path = bundle_for_artifact(scad_url)
            if not bundle_path:
                write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_scad_url"})
                return
            body = bundle_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{bundle_path.name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/library/search":
            query = parse_qs(parsed.query)
            q = (query.get("q") or [""])[0]
            write_json(self, HTTPStatus.OK, {"ok": True, "items": search_library(q)})
            return
        if path == "/api/templates/search":
            query = parse_qs(parsed.query)
            q = (query.get("q") or [""])[0]
            write_json(self, HTTPStatus.OK, {"ok": True, "items": search_all_templates(q)})
            return
        if path == "/api/templates/catalog":
            catalog = grouped_builtin_templates()
            write_json(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "component_types": list(catalog.keys()),
                    "count": sum(len(items) for items in catalog.values()),
                    "catalog": catalog,
                },
            )
            return
        if path == "/health":
            write_json(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "openscad": bool(shutil.which("openscad")),
                    "xvfb_run": bool(shutil.which("xvfb-run")),
                    "ollama_host": OLLAMA_HOST,
                    "default_model": DEFAULT_MODEL,
                    "prompt_model": PROMPT_MODEL,
                    "iteration_model": ITERATION_MODEL,
                    "vision_model": VISION_MODEL,
                    "model_options": MODEL_OPTIONS,
                    "prompt_base_url_configured": bool(PROMPT_BASE_URL),
                    "iteration_base_url_configured": bool(ITERATION_BASE_URL),
                    "jarvis_core_configured": bool(JARVIS_CORE_URL and JARVIS_CORE_TOKEN),
                    "jarvis_core_url": JARVIS_CORE_URL,
                    "data_dir": str(DATA_DIR),
                    "data_dir_writable": data_dir_writable(),
                    "max_iterations": MAX_ITERATIONS,
                },
            )
            return
        if path.startswith("/artifacts/"):
            rel = unquote(path[len("/artifacts/") :])
            target = (DATA_DIR / rel).resolve()
            if not str(target).startswith(str(DATA_DIR.resolve())) or not target.is_file():
                write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
                return
            ctype = "application/octet-stream"
            if target.suffix == ".png":
                ctype = "image/png"
            elif target.suffix == ".scad":
                ctype = "text/plain; charset=utf-8"
            elif target.suffix == ".stl":
                ctype = "model/stl"
            elif target.suffix == ".3mf":
                ctype = "model/3mf"
            elif target.suffix in {".step", ".stp"}:
                ctype = "model/step"
            elif target.suffix == ".json":
                ctype = "application/json"
            elif target.suffix == ".py":
                ctype = "text/plain; charset=utf-8"
            body = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if target.suffix in {".scad", ".stl", ".csg", ".3mf", ".step", ".stp", ".json", ".py"}:
                self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
            self.end_headers()
            self.wfile.write(body)
            return
        write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not authorized(self):
            write_json(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = read_json(self)
            if path == "/api/preview":
                scad = extract_scad(payload.get("scad", ""))
                run_dir = DATA_DIR / "previews" / now_id("preview")
                started = time.time()
                result = render_artifacts(scad, run_dir, render_preview=True)
                result.update(
                    {
                        "ok": result["ok"],
                        "run_id": run_dir.name,
                        "name": "Manual preview",
                        "pipeline": [
                            {"stage": "validate_editor_scad", "ok": not bool(validate_scad(scad))},
                            {"stage": "compile_scad", "ok": result.get("compile", {}).get("ok"), "seconds": result.get("compile", {}).get("seconds")},
                            {"stage": "render_png", "ok": result.get("render", {}).get("ok"), "seconds": result.get("render", {}).get("seconds")},
                            {"stage": "export_stl", "ok": result.get("export", {}).get("ok"), "seconds": result.get("export", {}).get("seconds")},
                            {"stage": "total", "ok": result["ok"], "seconds": round(time.time() - started, 2)},
                        ],
                    }
                )
                write_json(self, HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_REQUEST, result)
                return
            if path == "/api/iteration-chat":
                question = str(payload.get("question", "")).strip()
                if not question:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_question"})
                    return
                title = str(payload.get("title", "Iteration")).strip()[:120]
                stl = str(payload.get("stl", "")).strip()[:300]
                notes = str(payload.get("notes", "")).strip()[:3000]
                selection = str(payload.get("selection", "")).strip()[:1000]
                measurement = str(payload.get("measurement", "")).strip()[:1000]
                prompt = f"""You are a mechanical CAD review assistant helping inspect one generated iteration.
Answer briefly and practically. Use the selected surface point and measurements as geometry context.
If the user asks for a change, describe the exact CAD intent that should be fed back into generation.

Iteration: {title}
STL: {stl}
Selected context:
{selection or "none"}

Measurement:
{measurement or "none"}

Review notes:
{notes or "none"}

User question:
{question}
"""
                started = time.time()
                try:
                    answer, source = model_complete("prompt", PROMPT_MODEL, prompt, 0.25)
                    write_json(
                        self,
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "answer": answer.strip(),
                            "model": PROMPT_MODEL,
                            "source": source,
                            "seconds": round(time.time() - started, 2),
                        },
                    )
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                    write_json(self, HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
                return
            if path == "/api/library/approve":
                try:
                    item = save_approved_version(
                        str(payload.get("scad", "")).strip(),
                        str(payload.get("title", "")).strip(),
                        notes=str(payload.get("notes", "")).strip(),
                        tags=str(payload.get("tags", "")).strip(),
                        source_url=str(payload.get("source_url", "")).strip(),
                        license_name=str(payload.get("license", "")).strip(),
                    )
                    write_json(self, HTTPStatus.OK, {"ok": True, "item": item})
                except (ValueError, OSError) as exc:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            if path == "/api/duplicate":
                scad_path = artifact_path_from_url(payload.get("scad", ""), {".scad"})
                if not scad_path:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_or_invalid_scad"})
                    return
                title = str(payload.get("title", "Duplicated project")).strip()[:120] or "Duplicated project"
                source_scad = scad_path.read_text(encoding="utf-8", errors="replace")
                run_dir = DATA_DIR / "runs" / now_id("duplicate") / "iteration-001"
                result = render_artifacts(source_scad, run_dir, render_preview=True)
                result.update({"iteration": 1, "name": title, "source": "duplicated_project"})
                manifest_scad = artifact_path_from_url(result.get("scad", ""), {".scad"})
                if manifest_scad:
                    write_version_manifest(
                        manifest_scad.parent,
                        title,
                        "iteration",
                        result,
                        source="duplicated_project",
                        parent_scad=str(payload.get("scad", "")).strip(),
                        request=str(payload.get("request", "")).strip()[:2000],
                        notes="Duplicated as a new project.",
                    )
                result["viewer"] = f"/viewer?stl={quote(result.get('stl', ''))}&scad={quote(result.get('scad', ''))}&title={quote(title)}" if result.get("stl") else ""
                write_json(self, HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_REQUEST, result)
                return
            if path == "/api/project/rename":
                try:
                    item = update_project_title(str(payload.get("scad", "")).strip(), str(payload.get("title", "")).strip())
                    write_json(self, HTTPStatus.OK, {"ok": True, "item": item})
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            if path == "/api/project/delete":
                try:
                    item = archive_project(str(payload.get("scad", "")).strip())
                    write_json(self, HTTPStatus.OK, {"ok": True, "item": item})
                except (ValueError, OSError, shutil.Error) as exc:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            if path == "/api/research/scad":
                query = str(payload.get("query", "")).strip()
                if not query:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_query"})
                    return
                try:
                    candidates, saved = github_scad_research(query)
                    source = candidates[0].get("source") if candidates else "github-search"
                    write_json(self, HTTPStatus.OK, {"ok": True, "source": source, "candidates": candidates, "saved": saved})
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                    write_json(self, HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc), "candidates": []})
                return
            if path == "/api/revise":
                scad_path = artifact_path_from_url(payload.get("scad", ""), {".scad"})
                if not scad_path:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_or_invalid_scad"})
                    return
                title = str(payload.get("title", "Revision")).strip()[:120]
                request = str(payload.get("request", "")).strip()[:2000]
                notes = str(payload.get("notes", "")).strip()[:3000]
                selection = str(payload.get("selection", "")).strip()[:1000]
                measurement = str(payload.get("measurement", "")).strip()[:1000]
                revision_title = next_revision_title(str(payload.get("scad", "")).strip(), title)
                current_scad = scad_path.read_text(encoding="utf-8", errors="replace")
                run_dir = DATA_DIR / "revisions" / now_id("revision")
                pipeline = []
                started = time.time()
                try:
                    revised, source = revise_scad(ITERATION_MODEL, title, current_scad, request, notes, selection, measurement)
                    pipeline.append({"stage": "revise_scad", "ok": True, "model": ITERATION_MODEL, "source": source, "seconds": round(time.time() - started, 2)})
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                    revised, source = deterministic_revision_scad(current_scad, request, notes)
                    pipeline.append(
                        {
                            "stage": "revise_scad_ai_failed",
                            "ok": None,
                            "model": ITERATION_MODEL,
                            "seconds": round(time.time() - started, 2),
                            "message": str(exc),
                        }
                    )
                    pipeline.append(
                        {
                            "stage": "revise_scad_deterministic",
                            "ok": source != "deterministic:no_parametric_l_bracket_match",
                            "source": source,
                            "message": "Applied parameter-level fallback revision." if source != "deterministic:no_parametric_l_bracket_match" else "No deterministic parameter match; rendering original SCAD.",
                        }
                    )
                result = render_artifacts(revised, run_dir, render_preview=True)
                pipeline.append(
                    {
                        "stage": "render_revision",
                        "ok": result["ok"],
                        "seconds": (result.get("render", {}).get("seconds") or result.get("compile", {}).get("seconds")),
                        "message": result.get("error", ""),
                    }
                )
                if not result["ok"]:
                    repair_started = time.time()
                    try:
                        repaired, repair_source = repair_scad(ITERATION_MODEL, request or notes or title, revised, result.get("error", ""), 0.35)
                        repair_dir = run_dir / "repair"
                        repaired_result = render_artifacts(repaired, repair_dir, render_preview=True)
                        pipeline.append(
                            {
                                "stage": "repair_revision",
                                "ok": repaired_result["ok"],
                                "model": ITERATION_MODEL,
                                "source": repair_source,
                                "seconds": round(time.time() - repair_started, 2),
                                "message": repaired_result.get("error", ""),
                            }
                        )
                        if repaired_result["ok"]:
                            result = repaired_result
                            revised = repaired
                            source = f"{source}; repaired by {repair_source}"
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                        pipeline.append({"stage": "repair_revision_failed", "ok": None, "model": ITERATION_MODEL, "seconds": round(time.time() - repair_started, 2), "message": str(exc)})
                result.update(
                    {
                        "run_id": run_dir.name,
                        "name": revision_title,
                        "source": source,
                        "pipeline": pipeline,
                        "viewer": f"/viewer?stl={quote(result.get('stl', ''))}&scad={quote(result.get('scad', ''))}&title={quote(revision_title)}" if result.get("stl") else "",
                    }
                )
                manifest_scad = artifact_path_from_url(result.get("scad", ""), {".scad"})
                if manifest_scad:
                    write_version_manifest(
                        manifest_scad.parent,
                        revision_title,
                        "revision",
                        result,
                        source=source,
                        parent_scad=str(payload.get("scad", "")).strip(),
                        request=request,
                        notes=notes,
                    )
                write_json(self, HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_REQUEST, result)
                return
            if path == "/api/generate":
                prompt = str(payload.get("prompt", "")).strip()
                if not prompt:
                    write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_prompt"})
                    return
                iterations = max(1, min(MAX_ITERATIONS, int(payload.get("iterations", 1))))
                prompt_model = str(payload.get("prompt_model") or PROMPT_MODEL).strip()
                iteration_model = str(payload.get("iteration_model") or payload.get("model") or ITERATION_MODEL or DEFAULT_MODEL).strip()
                vision_model = str(payload.get("vision_model") or VISION_MODEL).strip()
                temperature = float(payload.get("temperature", 0.8))
                refine_first = bool(payload.get("refine_prompt", True))
                render_preview = bool(payload.get("render", True))
                use_cache_first = bool(payload.get("use_cache_first", False))
                requested_template_id = str(payload.get("template_id", "")).strip()
                parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
                pipeline = [
                    {"stage": "configuration", "ok": True, "message": f"prompt_model={prompt_model}; iteration_model={iteration_model}; vision_model={vision_model}; render={render_preview}; cache_first={use_cache_first}"},
                    {"stage": "data_dir_writable", "ok": data_dir_writable(), "message": str(DATA_DIR)},
                ]
                if not pipeline[-1]["ok"]:
                    write_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"{DATA_DIR} is not writable", "pipeline": pipeline})
                    return
                run_dir = DATA_DIR / "runs" / now_id("run")
                run_dir.mkdir(parents=True, exist_ok=True)
                refined_prompt = prompt
                profiles = jarvis_core_profiles() if JARVIS_CORE_URL and JARVIS_CORE_TOKEN else {}
                deep_ready = bool((profiles.get("deep") or {}).get("configured"))
                fast_ready = bool((profiles.get("fast") or {}).get("configured"))
                vision_ready = bool((profiles.get("vision") or {}).get("configured"))
                if JARVIS_CORE_URL and JARVIS_CORE_TOKEN:
                    pipeline.append(
                        {
                            "stage": "remote_model_profiles",
                            "ok": True if deep_ready and fast_ready and (vision_ready or not VISION_ENABLED) else None,
                            "message": (
                                f"deep={'configured' if deep_ready else 'missing base URL/API key'}; "
                                f"fast={'configured' if fast_ready else 'missing base URL/API key'}; "
                                f"vision={'configured' if vision_ready else 'missing base URL/API key'}"
                            ),
                        }
                    )
                if refine_first:
                    started = time.time()
                    try:
                        refined_prompt, source = refine_prompt(prompt, prompt_model, temperature)
                        pipeline.append({"stage": "refine_prompt", "ok": True, "model": prompt_model, "source": source, "seconds": round(time.time() - started, 2), "message": refined_prompt})
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                        pipeline.append({"stage": "refine_prompt_fallback", "ok": None, "model": prompt_model, "seconds": round(time.time() - started, 2), "message": str(exc)})
                cache_matches = search_library(refined_prompt if use_cache_first else "", limit=3) if use_cache_first else []
                if use_cache_first:
                    pipeline.append(
                        {
                            "stage": "approved_cache_search",
                            "ok": bool(cache_matches),
                            "message": f"{len(cache_matches)} match(es)" if cache_matches else "No approved cache match; continuing with templates/AI.",
                        }
                    )
                results = []
                for index in range(1, iterations + 1):
                    item_dir = run_dir / f"iteration-{index:03d}"
                    started = time.time()
                    template_id = requested_template_id if builtin_template_by_id(requested_template_id) else selected_builtin_template(refined_prompt)
                    template_item = next((item for item in builtin_template_items() if item.get("template_id") == template_id), {})
                    trusted = builtin_template_scad(template_id, refined_prompt, index, parameters) if template_id else ""
                    cadquery_source = ""
                    cache_match = cache_matches[0] if cache_matches and index == 1 else None
                    if cache_match:
                        cache_scad_path = artifact_path_from_url(cache_match.get("scad", ""), {".scad"})
                        if cache_scad_path:
                            try:
                                generated, source = revise_scad(
                                    iteration_model,
                                    cache_match.get("title", "Approved cache item"),
                                    cache_scad_path.read_text(encoding="utf-8", errors="replace"),
                                    refined_prompt,
                                    f"Adapt approved cached design for this prompt. Cache item: {cache_match.get('title', '')}",
                                    "",
                                    "",
                                )
                                source = f"approved-cache:{cache_match.get('library_id')}; adapted by {source}"
                                pipeline.append(
                                    {
                                        "stage": f"generate_iteration_{index}_approved_cache",
                                        "ok": True,
                                        "model": iteration_model,
                                        "source": source,
                                        "seconds": round(time.time() - started, 2),
                                        "message": cache_match.get("title", ""),
                                    }
                                )
                            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                                generated = ""
                                source = f"approved-cache failed: {exc}"
                                pipeline.append({"stage": f"generate_iteration_{index}_approved_cache_failed", "ok": None, "model": iteration_model, "seconds": round(time.time() - started, 2), "message": str(exc)})
                        else:
                            generated = ""
                            source = "approved-cache missing scad"
                    if not cache_match and trusted:
                        generated = trusted
                        cadquery_source = builtin_template_cadquery(template_id, refined_prompt, index, parameters)
                        source = f"builtin-template:{template_id}"
                        pipeline.append(
                            {
                                "stage": f"generate_iteration_{index}_trusted",
                                "ok": True,
                                "model": f"engineering-template:{template_id}",
                                "seconds": round(time.time() - started, 2),
                                "message": template_item.get("title", "Rule-backed hardware template"),
                            }
                        )
                    elif not cache_match:
                        try:
                            generated, source = generate_scad(iteration_model, refined_prompt, index, iterations, temperature)
                            pipeline.append({"stage": f"generate_iteration_{index}", "ok": True, "model": iteration_model, "source": source, "seconds": round(time.time() - started, 2)})
                        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                            generated = fallback_scad(refined_prompt, index, parameters)
                            source = f"fallback: {exc}"
                            pipeline.append({"stage": f"generate_iteration_{index}_fallback", "ok": None, "model": iteration_model, "seconds": round(time.time() - started, 2), "message": source})
                    if not generated:
                        generated = trusted or fallback_scad(refined_prompt, index, parameters)
                        source = f"fallback: {source}"
                    result = render_artifacts(generated, item_dir, render_preview=render_preview, cadquery_source=cadquery_source)
                    checks = basic_engineering_checks(generated, result, source)
                    checks_path = item_dir / "engineering_checks.json"
                    try:
                        checks_path.write_text(json.dumps(checks, indent=2), encoding="utf-8")
                        result["engineering_checks"] = checks
                        result["engineering_checks_url"] = artifact_url(checks_path)
                    except OSError:
                        result["engineering_checks"] = checks
                    if not result["ok"] and not str(source).startswith("fallback:"):
                        repair_started = time.time()
                        try:
                            repaired, repair_source = repair_scad(iteration_model, refined_prompt, generated, result.get("error", ""), temperature)
                            repair_dir = item_dir / "repair"
                            repaired_result = render_artifacts(repaired, repair_dir, render_preview=render_preview)
                            pipeline.append(
                                {
                                    "stage": f"repair_iteration_{index}",
                                    "ok": repaired_result["ok"],
                                    "model": iteration_model,
                                    "source": repair_source,
                                    "seconds": round(time.time() - repair_started, 2),
                                    "message": repaired_result.get("error", ""),
                                }
                            )
                            if repaired_result["ok"]:
                                generated = repaired
                                source = f"{source}; repaired by {repair_source}"
                                result = repaired_result
                        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                            pipeline.append({"stage": f"repair_iteration_{index}_failed", "ok": None, "model": iteration_model, "seconds": round(time.time() - repair_started, 2), "message": str(exc)})
                    if not result["ok"] and not str(source).startswith("fallback:"):
                        fallback = fallback_scad(refined_prompt, index, parameters)
                        fallback_dir = item_dir / "fallback"
                        fallback_result = render_artifacts(fallback, fallback_dir, render_preview=render_preview)
                        pipeline.append(
                            {
                                "stage": f"fallback_iteration_{index}",
                                "ok": fallback_result["ok"],
                                "seconds": (fallback_result.get("render", {}).get("seconds") or fallback_result.get("compile", {}).get("seconds")),
                                "message": fallback_result.get("error", ""),
                            }
                        )
                        if fallback_result["ok"]:
                            generated = fallback
                            source = f"fallback: AI generation did not compile/render cleanly; original source was {source}"
                            result = fallback_result
                    if result["ok"] and (str(source).startswith("trusted:") or str(source).startswith("builtin-template:")):
                        pipeline.append(
                            {
                                "stage": f"engineering_verify_iteration_{index}",
                                "ok": True,
                                "model": "engineering-template",
                                "message": "Trusted template generated the functional geometry directly; vision repair skipped to avoid replacing it with weaker freehand SCAD.",
                            }
                        )
                    elif result["ok"] and VISION_ENABLED:
                        if JARVIS_CORE_URL and JARVIS_CORE_TOKEN and vision_ready:
                            vision_started = time.time()
                            try:
                                critique, critique_source = vision_critique(refined_prompt, result, vision_model)
                                passed = bool(critique.get("pass", False))
                                pipeline.append(
                                    {
                                        "stage": f"vision_verify_iteration_{index}",
                                        "ok": passed,
                                        "model": vision_model,
                                        "source": critique_source,
                                        "seconds": round(time.time() - vision_started, 2),
                                        "message": json.dumps(critique, separators=(",", ":"))[:1200],
                                    }
                                )
                                if not passed and not str(source).startswith("fallback:"):
                                    repair_note = critique.get("repair_instruction") or "; ".join(critique.get("issues") or [])
                                    repaired, repair_source = repair_scad(
                                        iteration_model,
                                        refined_prompt,
                                        generated,
                                        "Visual critique failed: " + str(repair_note),
                                        temperature,
                                    )
                                    vision_repair_dir = item_dir / "vision-repair"
                                    vision_repair_result = render_artifacts(repaired, vision_repair_dir, render_preview=render_preview)
                                    pipeline.append(
                                        {
                                            "stage": f"vision_repair_iteration_{index}",
                                            "ok": vision_repair_result["ok"],
                                            "model": iteration_model,
                                            "source": repair_source,
                                            "seconds": round(time.time() - vision_started, 2),
                                            "message": vision_repair_result.get("error", ""),
                                        }
                                    )
                                    if vision_repair_result["ok"]:
                                        recheck_started = time.time()
                                        recheck, recheck_source = vision_critique(refined_prompt, vision_repair_result, vision_model)
                                        recheck_passed = bool(recheck.get("pass", False))
                                        pipeline.append(
                                            {
                                                "stage": f"vision_recheck_iteration_{index}",
                                                "ok": recheck_passed,
                                                "model": vision_model,
                                                "source": recheck_source,
                                                "seconds": round(time.time() - recheck_started, 2),
                                                "message": json.dumps(recheck, separators=(",", ":"))[:1200],
                                            }
                                        )
                                        if recheck_passed:
                                            generated = repaired
                                            source = f"{source}; visually repaired by {repair_source}"
                                            result = vision_repair_result
                                        else:
                                            fallback = fallback_scad(refined_prompt, index, parameters)
                                            fallback_dir = item_dir / "vision-fallback"
                                            fallback_result = render_artifacts(fallback, fallback_dir, render_preview=render_preview)
                                            pipeline.append(
                                                {
                                                    "stage": f"vision_fallback_iteration_{index}",
                                                    "ok": fallback_result["ok"],
                                                    "seconds": (fallback_result.get("render", {}).get("seconds") or fallback_result.get("compile", {}).get("seconds")),
                                                    "message": fallback_result.get("error", ""),
                                                }
                                            )
                                            if fallback_result["ok"]:
                                                generated = fallback
                                                source = f"fallback: vision repair did not pass verification; original source was {source}"
                                                result = fallback_result
                            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, RuntimeError) as exc:
                                pipeline.append({"stage": f"vision_verify_iteration_{index}_failed", "ok": None, "model": vision_model, "seconds": round(time.time() - vision_started, 2), "message": str(exc)})
                        else:
                            pipeline.append({"stage": f"vision_verify_iteration_{index}_skipped", "ok": None, "model": vision_model, "message": "Vision profile is not configured."})
                    result.update({"iteration": index, "name": f"Iteration {index}", "source": source})
                    manifest_scad = artifact_path_from_url(result.get("scad", ""), {".scad"})
                    if manifest_scad:
                        write_version_manifest(
                            manifest_scad.parent,
                            f"Iteration {index}",
                            "iteration",
                            result,
                            source=source,
                            request=prompt,
                            notes=refined_prompt,
                        )
                    pipeline.append(
                        {
                            "stage": f"render_iteration_{index}",
                            "ok": result["ok"],
                            "seconds": (result.get("render", {}).get("seconds") or result.get("compile", {}).get("seconds")),
                            "message": result.get("error", ""),
                        }
                    )
                    results.append(result)
                summary = {
                    "ok": any(item.get("ok") for item in results),
                    "run_id": run_dir.name,
                    "prompt": prompt,
                    "refined_prompt": refined_prompt,
                    "prompt_model": prompt_model,
                    "iteration_model": iteration_model,
                    "vision_model": vision_model,
                    "pipeline": pipeline,
                    "results": results,
                }
                (run_dir / "run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
                write_json(self, HTTPStatus.OK, summary)
                return
            write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except Exception as exc:
            write_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"SCAD AI Generator listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

