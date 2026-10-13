"""Bookmark maker: pet photo, silhouette or picture (SVG/PNG/JPEG) -> multicolor 3MF + STL bookmark.

Pipeline: cutout.py (photo -> clean mask, step 1 of the page) -> potrace -> OpenSCAD (one render per color
part, run in parallel) -> Python assembles STL/3MF. See geometry.py for the shapes, imaging.py for the bitmaps
and styles.py for the looks offered on the page.
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

from PIL import Image, ImageChops, ImageFilter

import cutout
import geometry
import imaging
import styles
import threemf

PORT = int(os.environ.get("BOOKMARK_PORT", "8105"))
DATA_DIR = Path(os.environ.get("BOOKMARK_DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
CUTS_DIR = DATA_DIR / "cutouts"
KEEP_DAYS = float(os.environ.get("BOOKMARK_KEEP_DAYS", "7"))
OPENSCAD_TIMEOUT = int(os.environ.get("BOOKMARK_OPENSCAD_TIMEOUT", "120"))
MAX_UPLOAD = 15 * 1024 * 1024
JOB_RE = re.compile(r"^[0-9a-f]{12}$")
FILE_RE = re.compile(r"^[a-z0-9_]+\.(stl|3mf|svg|png)$")
CTYPES = {".stl": "model/stl", ".3mf": "model/3mf", ".svg": "image/svg+xml", ".png": "image/png"}
PAGE = Path(__file__).with_name("page.html").read_bytes()
CHOICES = {  # first option is the default
    "style": ("clip", "solid", "corner", "paws", "tail", "magnet"),
    "tail_end": ("bottom", "left", "right", "top"),
    "face": ("raised", "flush"),
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
    "thickness": (1.5, 0.6, 4.0),
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
    "page_line": (0.78, 0.4, 0.95),  # paws: where the book's top edge crosses the art (fraction from the top)
    "slot_center": (0.5, 0.1, 0.9),  # paws: tongue position across the art
    "crop": (1.0, 0.3, 1.0),  # keep only the top part of the art (1 = all), e.g. 0.5 = head for a corner biter
    "thicken": (1.0, 0.0, 1.0),
    "art_x": (0.0, -60.0, 60.0),  # drag to place: art offset from the centre
    "art_y": (0.0, -40.0, 40.0),  # drag to place: art offset upward
    "tail_show": (0.5, 0.2, 0.9),
    "details": (0.0, 0.0, 3.0),  # face details from the photo: 0 off, 1 less, 2 some, 3 more
    "face_layers": (1.0, 1.0, 3.0),  # flat face-down color: layers of face color (1 = one filament change)  # tail: how much of the pet sticks out of the bottom of the book
    "magnet_d": (6.0, 3.0, 12.0),  # magnet: disc magnet diameter
    "magnet_t": (1.0, 0.5, 3.0),  # magnet: disc magnet thickness  # widen features thinner than MIN_FEATURE so they don't vanish in the slicer
}
MIN_FEATURE = 0.8  # mm, two 0.4 mm nozzle widths


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


SVG_VIEW = re.compile(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"')
SVG_PATH = re.compile(r'<path d="([^"]*)"')


def compose_preview(job_dir, body_svg, art_svg):
    """One SVG with the body in a light color and the art + text in a dark one (OpenSCAD can't color 2D)."""
    views, paths = [], []
    for name, fill in ((body_svg, "#e7e1d3"), (art_svg, "#2b3a55")):
        f = job_dir / name
        if not f.is_file():
            continue
        text = f.read_text()
        m = SVG_VIEW.search(text)
        if m:
            x, y, w, h = map(float, m.groups())
            views.append((x, y, x + w, y + h))
        group = "".join(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="#333" stroke-width="0.3"/>'
                        for d in SVG_PATH.findall(text))
        paths.append(f'<g id="art">{group}</g>' if name == art_svg else group)
    if not views:
        return
    x0, y0 = min(v[0] for v in views) - 1, min(v[1] for v in views) - 1
    x1, y1 = max(v[2] for v in views) + 1, max(v[3] for v in views) + 1
    (job_dir / "preview.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" '
        f'width="{x1 - x0}mm" height="{y1 - y0}mm">{"".join(paths)}</svg>')


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def prepare_mask(params, mask, photo=None):
    """Crop to the art, apply the top crop, thicken thin features. Returns (mask, noticeably_thickened, photo),
    with the photo (if given, same size as the mask) cropped and turned the same way."""
    box = mask.getbbox()
    if not box:
        raise ValueError("No silhouette found. Try moving the threshold slider or toggling invert.")
    imgs = [mask, photo]

    def crop(b):
        imgs[:] = [im.crop(b) if im is not None else None for im in imgs]

    crop(box)
    if params["style"] == "tail":  # turn the chosen end of the pet downward and keep only that end
        turn = {"bottom": None, "left": Image.ROTATE_90, "right": Image.ROTATE_270, "top": Image.ROTATE_180}
        if turn[params["tail_end"]] is not None:
            imgs[:] = [im.transpose(turn[params["tail_end"]]) if im is not None else None for im in imgs]
        top = round(imgs[0].height * (1 - params["tail_show"]))
        crop((0, min(top, imgs[0].height - 4), imgs[0].width, imgs[0].height))
        crop(imgs[0].getbbox())
    if params["crop"] < 0.999:
        crop((0, 0, imgs[0].width, max(4, round(imgs[0].height * params["crop"]))))
        crop(imgs[0].getbbox())
    mask, photo = imgs
    thickened = False
    if params["thicken"]:
        mm = min(params["art_width"] / mask.width, params["art_height"] / mask.height)
        r = round(MIN_FEATURE / 2 / mm)
        if r >= 1:
            k = 2 * r + 1
            opened = mask.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
            thin = ImageChops.subtract(mask, opened)
            thin_px = sum(1 for v in thin.getdata() if v)
            if thin_px:
                thickened = thin_px > 0.01 * sum(1 for v in mask.getdata() if v)
                mask = ImageChops.lighter(mask, thin.filter(ImageFilter.MaxFilter(k)))
    return mask, thickened, photo


DETAIL_AMOUNT = {1: 50, 2: 35, 3: 24}  # face details: contrast needed for Less / Some / More
DETAIL_H = 0.4  # one-color looks: details stand this far above the pet
FLUSH_STYLES = ("solid", "clip", "tail", "paws")


def build_plan(params, img, job_dir, mask=None, photo=None):
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
        plan = geometry.plan_photo(params, levels, gray.size, lines)
        plan["card"]["changes"] = filament_changes(plan)
        return plan
    if mask is None:
        mask = imaging.silhouette_mask(img, params["threshold"], params["invert"])
    level = int(round(params["details"]))
    if photo is not None and level:
        photo = photo.convert("RGB").resize(mask.size)
    mask, thickened, photo = prepare_mask(params, mask, photo if level else None)
    tongue = None
    if params["style"] == "paws":
        mask, tongue, notes = geometry.paws_prepare(params, mask)
    det_polys = []
    if photo is not None and level:
        ppm = 1 / min(params["art_width"] / mask.width, params["art_height"] / mask.height)  # px per printed mm
        det = cutout.detail_mask(photo, mask, DETAIL_AMOUNT.get(level, 35), ppm)
        if det.getbbox():
            det_polys, _ = imaging.trace(det, job_dir, "det", turdsize=2)
    polys, _ = imaging.trace(mask, job_dir, "art")
    if not polys:
        raise ValueError("No silhouette found. Try moving the threshold slider or toggling invert.")
    if params["style"] == "corner":
        plan = geometry.plan_corner(params, polys, lines)
    elif params["style"] == "paws":
        plan = geometry.plan_paws(params, polys, lines, tongue)
        plan["warnings"] = notes + plan["warnings"]
    else:
        plan = geometry.plan_standard(params, polys, lines)
    if thickened:
        plan["warnings"].append(f"Thin details (under {MIN_FEATURE} mm) were thickened so they print.")
    add_details(params, plan, det_polys)
    if params["face"] == "flush":
        make_flush(params, plan)
    plan["card"]["changes"] = filament_changes(plan)
    return plan


def add_details(params, plan, det_polys):
    """Cut the face details out of the raised pet (the body color shows through, no extra filament change),
    or for one-color looks raise them a little above the pet."""
    plan["files"]["art.scad"] += "module det_raw() { " + (
        imaging.polygon_scad(det_polys, plan["to_mm"]) if det_polys else "") + " }\n"
    if not det_polys or params["art_raise"] > 0 or params["face"] == "flush":
        return
    body = next(p for p in plan["parts"] if p["name"] == "Body")
    outline = plan["outline"].rstrip().rstrip(";")
    body["pieces"].append(("details", f"translate([0,0,{body['z1']:.3f}]) linear_extrude({DETAIL_H}) "
                                      f"intersection() {{ det_all(); {outline}; }}", geometry.ART))
    body["z1"] += DETAIL_H
    if params["style"] == "paws":  # the paws are inside the book
        plan["layout"]["in_book"] = round(max(plan["layout"]["in_book"], params["thickness"] + DETAIL_H), 2)


def make_flush(params, plan):
    """Flat face-down color: the pet and text are printed in the first layer(s), flush with the body, against
    the build plate. The model is mirrored so the face reads correctly once it is turned over."""
    if params["style"] not in FLUSH_STYLES or not plan.get("face2d"):
        plan["warnings"].append("Flat face-down color isn't available for this look, so the pet is raised instead.")
        return
    thick = params["thickness"]
    t0 = round(0.2 * int(round(params["face_layers"])), 2)
    face = f"union() {{ {plan['face2d']}; text2d(); }}"
    flip = "mirror([1, 0, 0])"
    plan["parts"] = [
        {"name": "Face", "z0": 0.0, "z1": t0, "color": "#2b3a55",
         "pieces": [("face", f"{flip} linear_extrude({t0}) intersection() {{ {face}; base_cut(); }}", geometry.ART)]},
        {"name": "Body", "z0": 0.0, "z1": thick, "color": "#f4f1ea",
         "pieces": [("body_a", f"{flip} linear_extrude({t0}) difference() {{ base_cut(); {face}; }}", geometry.ART),
                    ("body_b", f"{flip} translate([0,0,{t0}]) linear_extrude({thick - t0:.3f}) base_cut();", geometry.ART)]},
    ]
    c = geometry.card(plan["parts"], 0.2)
    c["flush_layers"] = int(round(params["face_layers"]))
    c["notes"] = ["Print as it comes: the face is printed against the plate, so the model looks mirrored in the slicer.",
                  "A textured PEI plate gives a sparkly matte face; a smooth plate gives a glossy one.",
                  "The pet and the text share the face color."]
    plan["card"] = c
    plan["layout"]["in_book"] = round(thick, 2)
    plan["layout"]["flush"] = True


def filament_changes(plan):
    """How many times you swap filament by hand on a printer without an AMS."""
    c = plan["card"]
    if c.get("flush_layers"):
        return 2 * c["flush_layers"] - 1  # face color, then body; one more change per extra face layer
    return len(c["swaps"])


def estimate(verts, card):
    """Rough PLA grams and print minutes for the print card (Bambu-class printer, 100% infill)."""
    vol = 0.0
    for i in range(0, len(verts) - 2, 3):
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = verts[i:i + 3]
        vol += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6
    height = max(v[2] for v in verts) - min(v[2] for v in verts)
    layers = max(1, round(height / card["layer_height"]))
    grams = abs(vol) / 1000 * 1.24
    minutes = (abs(vol) / 7 + layers * 3) / 60 + 1 + 1.5 * len(card["swaps"])
    return round(grams, 1), max(1, round(minutes))


def card_summary(c):
    """The print card in plain words, also written into the 3MF."""
    lines = [f"About {c['grams']} g of PLA and {c['minutes']} minutes. Flat side down, no supports, "
             f"{c['layer_height']} mm layers, 100% infill."]
    steps = [(sw["z"], f"At {sw['z']} mm (layer {sw['layer']}): switch to color {i + 2} for {' / '.join(sw['parts'])}.")
             for i, sw in enumerate(c["swaps"])]
    if c.get("flush_layers"):
        steps.append((0, f"The face prints against the plate: face color first, then switch to the body color "
                         f"after {'layer 1' if c['flush_layers'] == 1 else 'each of the first %d layers' % c['flush_layers']}."))
    if c.get("pause"):
        steps.append((c["pause"]["z"], f"At {c['pause']['z']} mm (layer {c['pause']['layer']}): pause and {c['pause']['what']}."))
    return " ".join(lines + [t for _, t in sorted(steps)])


def assemble(job_id, job_dir, parts_meta, colors, title="Bookmark", description=""):
    """Write the combined STL and the 3MF from the per-part STLs on disk."""
    parts = []
    for i, meta in enumerate(parts_meta):
        color = colors[i] if i < len(colors) and colors[i] else meta["color"].lstrip("#")
        meta["color"] = "#" + color.lower()
        parts.append({"name": meta["name"], "color": meta["color"], "extruder": meta["extruder"],
                      "verts": threemf.read_stl(job_dir / meta["file"])})
    threemf.write_3mf(job_dir / "bookmark.3mf", parts, title, description)
    return parts


def load_cutout(cut_id):
    path = CUTS_DIR / cut_id / "mask.png"
    if not JOB_RE.match(cut_id or "") or not path.is_file():
        raise ValueError("That photo has expired. Upload it again.")
    return Image.open(path).convert("L")


def render_outlines(job_dir, plan):
    """2D outline SVG of the body and (when the plan has one) of the art; then compose preview.svg."""
    art = "".join(f"include <{n}>\n" for n in plan["files"] if n == "art.scad")
    jobs = [("outline", plan["outline"])] + ([("art2d", plan["art_outline"])] if plan.get("art_outline") else [])
    for stem, code in jobs:
        (job_dir / f"{stem}.scad").write_text(f"include <common.scad>\n{art}{code}\n")
    with ThreadPoolExecutor(max_workers=2) as ex:
        for fut in [ex.submit(openscad, job_dir, f"{stem}.scad", f"{stem}.svg") for stem, _ in jobs]:
            fut.result()
    compose_preview(job_dir, "outline.svg", "art2d.svg")


def preview_url(job_id, job_dir):
    name = "preview.svg" if (job_dir / "preview.svg").is_file() else "outline.svg"
    return f"/jobs/{job_id}/{name}"


def make_cutout(data=None, cut_id=None, opts=None):
    """Step 1: photo -> mask. With data, stores a new photo; with cut_id, re-cuts the stored one."""
    opts = opts or {}
    if data is not None:
        cut_id = uuid.uuid4().hex[:12]
        cut_dir = CUTS_DIR / cut_id
        cut_dir.mkdir(parents=True)
        img = imaging.load_image(data, cut_dir)
        img.thumbnail((cutout.WORK_PX, cutout.WORK_PX))
        img.save(cut_dir / "photo.png")
    else:
        cut_dir = CUTS_DIR / cut_id
        if not JOB_RE.match(cut_id or "") or not (cut_dir / "photo.png").is_file():
            raise ValueError("That photo has expired. Upload it again.")
        img = Image.open(cut_dir / "photo.png")
    method = opts.get("method") if opts.get("method") in ("auto", "art") else "auto"
    raw_path = cut_dir / "raw.png"
    raw = None
    if method == "auto" and raw_path.is_file():
        raw = Image.open(raw_path).convert("L")
        raw.info["method"] = (cut_dir / "raw.txt").read_text() if (cut_dir / "raw.txt").is_file() else "model"
    strokes = [s for s in opts.get("strokes", []) if isinstance(s, list) and len(s) == 4
               and all(isinstance(v, (int, float)) for v in s)]
    mask, info = cutout.make_mask(img, method, float(opts.get("threshold", 128)), bool(opts.get("invert")),
                                  min(max(int(opts.get("smooth", 2)), 0), 6), bool(opts.get("fill_holes", True)),
                                  strokes, raw)
    if "raw" in info:
        info["raw"].save(raw_path)
        (cut_dir / "raw.txt").write_text(info["method"])
    mask.save(cut_dir / "mask.png")
    # preview: the pet on a transparent background
    pet = img.convert("RGBA")
    pet.putalpha(mask.resize(pet.size))
    pet.crop(mask.getbbox()).save(cut_dir / "pet.png")
    # view: the whole photo with the background faded, for painting fixes in step 1
    view = Image.blend(img.convert("RGB"), Image.new("RGB", img.size, (255, 255, 255)), 0.75)
    view.paste(img.convert("RGB"), (0, 0), mask.resize(img.size))
    view.save(cut_dir / "view.png")
    return {"id": cut_id, "pet": f"/cutouts/{cut_id}/pet.png?v={uuid.uuid4().hex[:6]}",
            "mask": f"/cutouts/{cut_id}/mask.png", "view": f"/cutouts/{cut_id}/view.png?v={uuid.uuid4().hex[:6]}",
            "size": list(mask.size), "box": list(mask.getbbox()),
            "method": info["method"], "removed_specks": info["removed_specks"]}


def make_bookmark(data, params, cut_id=None, preview_only=False):
    started = time.time()
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    if cut_id and params["mode"] == "silhouette":
        plan = build_plan(params, None, job_dir, load_cutout(cut_id), Image.open(CUTS_DIR / cut_id / "photo.png"))
    elif cut_id:
        plan = build_plan(params, Image.open(CUTS_DIR / cut_id / "photo.png"), job_dir)
    else:
        plan = build_plan(params, imaging.load_image(data, job_dir), job_dir)
    if preview_only:
        (job_dir / "common.scad").write_text(plan["common"])
        for name, text in plan["files"].items():
            (job_dir / name).write_text(text)
        render_outlines(job_dir, plan)
        return {"id": job_id, "preview": preview_url(job_id, job_dir), "layout": plan["layout"],
                "warnings": [{"message": m} for m in plan["warnings"]], "seconds": round(time.time() - started, 1)}

    # one OpenSCAD render per piece, in parallel
    (job_dir / "common.scad").write_text(plan["common"])
    for name, text in plan["files"].items():
        (job_dir / name).write_text(text)
    art = [n for n in plan["files"] if n == "art.scad"]
    head = f"include <common.scad>\n{''.join(f'include <{n}>' + chr(10) for n in art)}"
    jobs = [("outline", f"{head}{plan['outline']}\n", "svg")]
    if plan.get("art_outline"):
        jobs.append(("art2d", f"{head}{plan['art_outline']}\n", "svg"))
    for part in plan["parts"]:
        for stem, code, includes in part["pieces"]:
            jobs.append((stem, "include <common.scad>\n" + "".join(f"include <{n}>\n" for n in includes) + code + "\n", "stl"))
    for stem, text, _ in jobs:
        (job_dir / f"{stem}.scad").write_text(text)
    with ThreadPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 4)) as pool:
        for fut in [pool.submit(openscad, job_dir, f"{stem}.scad", f"{stem}.{ext}") for stem, _, ext in jobs]:
            fut.result()
    compose_preview(job_dir, "outline.svg", "art2d.svg")

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
    plan["card"]["grams"], plan["card"]["minutes"] = estimate(all_verts, plan["card"])
    plan["card"]["summary"] = card_summary(plan["card"])
    assemble(job_id, job_dir, parts_meta, params["colors"], description=plan["card"]["summary"])

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
        "preview": preview_url(job_id, job_dir),
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
    assemble(job_id, job_dir, parts_meta, colors, description=info["print_card"].get("summary", ""))
    for meta, old in zip(parts_meta, info["parts"]):
        old["color"] = meta["color"]
    (job_dir / "job.json").write_text(json.dumps(info, indent=2))


def cleanup_old_jobs():
    cutoff = time.time() - KEEP_DAYS * 86400
    for root in (JOBS_DIR, CUTS_DIR):
        if not root.exists():
            continue
        for job in root.iterdir():
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
            return self.send_json(200 if ok else 503, {"ok": ok, "cutout_model": cutout.model_available()})
        if path == "/api/styles":
            return self.send_json(200, styles.STYLES)
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "cutouts" and JOB_RE.match(parts[1]) and parts[2] in ("pet.png", "mask.png", "view.png"):
            target = CUTS_DIR / parts[1] / parts[2]
            if target.is_file():
                return self.send(200, target.read_bytes(), "image/png")
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
        parts = url.path.strip("/").split("/")
        query = parse_qs(url.query)
        cut_id = query.get("cutout", [""])[0] or None
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_UPLOAD or (size == 0 and not (cut_id or len(parts) == 3)):
            return self.send_json(400, {"error": "Upload an SVG, PNG or JPEG up to 15 MB."})
        data = self.rfile.read(size) if size else None
        cleanup_old_jobs()
        try:
            if url.path == "/api/cutout":
                result = make_cutout(data=data)
            elif len(parts) == 3 and parts[:2] == ["api", "cutout"]:
                opts = json.loads(data or b"{}")
                result = make_cutout(cut_id=parts[2], opts=opts if isinstance(opts, dict) else {})
            elif url.path in ("/api/make", "/api/preview"):
                result = make_bookmark(None if cut_id else data, parse_params(query), cut_id,
                                       preview_only=url.path == "/api/preview")
            else:
                return self.send_json(404, {"error": "not found"})
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
