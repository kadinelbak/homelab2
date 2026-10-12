"""Bookmark geometry: layout, text fitting, patterns and OpenSCAD source generation.

Every printable color is its own "part"; a part is one or more OpenSCAD pieces, each a plain
linear_extrude of a 2D shape (no 3D booleans, so renders are fast and parts never overlap).
Coordinates: x centered on the body, y=0 at the bottom tip of the body, y grows toward the art.
"""
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from imaging import bbox, polygon_scad, raster_polys

FONTS = {  # key: (OpenSCAD font name, TrueType file used to measure the text)
    "dejavu-sans": ("DejaVu Sans:style=Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    "dejavu-serif": ("DejaVu Serif:style=Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    "liberation-sans": ("Liberation Sans:style=Bold", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    "liberation-serif": ("Liberation Serif:style=Bold", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
    "liberation-mono": ("Liberation Mono:style=Bold", "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"),
}
MIN_LETTER = 3.5
TEXT_MARGIN = 1.5
LEVEL_H = 0.24
PLATE, PAGE_GAP, CORNER_WALL = 0.8, 0.8, 4.0
WALL_MIN = 1.2
ART = ["art.scad"]
PPM = 2.0  # raster scale (px per mm) for the loose-piece check


# ---------- small 2D helpers ----------

def arc(cx, cy, r, a0, a1, step=7.5):
    n = max(2, int(abs(a1 - a0) / step))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def body_polygon(shape, w, top, ref_len):
    h = w / 2
    if shape == "round":
        return [(-h, top)] + arc(0, h, h, 180, 360) + [(h, top)]
    if shape == "point":
        return [(-h, top), (-h, w * 0.9), (0, 0), (h, w * 0.9), (h, top)]
    if shape == "swallowtail":
        return [(-h, top), (-h, 0), (0, w * 0.45), (h, 0), (h, top)]
    if shape == "taper":
        rt = w * 0.2
        ys = min(2.2 * w, ref_len * 0.6)
        return [(-h, top), (-h, ys)] + arc(0, rt, rt, 180, 360) + [(h, ys), (h, top)]
    return [(-h, top), (-h, 0), (h, 0), (h, top)]  # square


def inside(pt, poly):
    x, y = pt
    hit = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def clearance(pt, poly):
    """Signed distance from pt to the polygon boundary (negative outside)."""
    best = float("inf")
    px, py = pt
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        dx, dy = x2 - x1, y2 - y1
        t = 0 if dx == dy == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))
    return best if inside(pt, poly) else -best


def pts_scad(poly):
    return "[" + ",".join("[%.3f,%.3f]" % pt for pt in poly) + "]"


def esc(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def clean_text(raw):
    return "".join(ch for ch in (raw or "") if ch.isprintable() and ch not in "\r\n\t")[:30].strip()


# ---------- text ----------

def _ink(text, font_path):
    font = ImageFont.truetype(font_path, 200)
    img = Image.new("L", (int(font.getlength(text)) + 600, 800), 0)
    ImageDraw.Draw(img).text((300, 400), text, font=font, fill=255, anchor="ls")
    box = img.getbbox()
    if not box:
        raise ValueError("Text has no printable glyphs in this font.")
    return box[0] - 300, box[1] - 400, box[2] - 300, box[3] - 400  # l, t, r, b (y down from baseline)


def fit_text(lines, font_key, size_req, poly, ins, y_hi, y_lo_min):
    """Find the largest letter height that fits; returns dict with scad + rect, or raises ValueError."""
    name, path = FONTS[font_key]
    try:
        cap = -_ink("H", path)[1]
        inks = [_ink(t, path) for t in lines]
    except OSError as exc:
        raise ValueError(f"Font {font_key} is not installed.") from exc
    n = len(lines)
    widest = max(r - l for l, _, r, _ in inks)

    def dims(hl):
        pitch = 1.35 * hl
        return pitch, 1.3 * hl + (n - 1) * pitch, widest * hl / cap

    def bottom(across):
        y = y_lo_min
        while y < y_hi:
            if all(clearance((-across / 2 + across * i / 8, y), poly) >= ins for i in range(9)):
                return y
            y += 0.25
        return None

    def fits(hl):
        _, across, length = dims(hl)
        yb = bottom(across)
        top_ok = all(clearance((-across / 2 + across * i / 8, y_hi), poly) >= ins for i in range(9))
        return yb is not None and top_ok and length <= y_hi - yb

    wanted = size_req if size_req > 0 else 8.0
    if not fits(MIN_LETTER):
        raise ValueError(
            f"Text does not fit: letters would be smaller than {MIN_LETTER} mm. "
            "Shorten the text, use one line, or make the body wider/longer (clip tongue: reduce rail/gap)."
        )
    if fits(wanted):
        hl = wanted
    else:
        lo, hi = MIN_LETTER, wanted
        for _ in range(14):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fits(mid) else (lo, mid)
        hl = lo
    pitch, across, length = dims(hl)
    yb = bottom(across)
    yc = (yb + y_hi) / 2
    scale = hl / cap
    parts = []
    for k, (line, (l, t, r, b)) in enumerate(zip(lines, inks)):
        xk = (k - (n - 1) / 2) * pitch
        parts.append(
            f'translate([{xk:.3f},{yc:.3f}]) rotate(90) translate([{-scale * (l + r) / 2:.4f},{-hl / 2:.4f}]) '
            f'resize([{scale * (r - l):.4f},{scale * (b - t):.4f}]) '
            f'text("{esc(line)}", size=10, font="{esc(name)}", halign="left", valign="baseline");'
        )
    return {"scad": " ".join(parts), "size": round(hl, 2), "wanted": wanted,
            "rect": (-across / 2, yc - length / 2, across / 2, yc + length / 2)}


# ---------- patterns ----------

def _star(radius):
    pts = []
    for i in range(10):
        a = math.radians(90 + 36 * i)
        r = radius if i % 2 == 0 else radius * 0.42
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def pattern_cells(kind, cell, xmax, ymin, ymax, ok):
    """Cell centers of a lattice that pass ok(x, y, radius); returns (centers, cell_scad, radius)."""
    wall = WALL_MIN
    if kind == "honeycomb":
        rad = (cell - wall) / math.sqrt(3)
        shape = f"circle(r={rad:.3f}, $fn=6);"
        lattice = [(i * cell * math.sqrt(3) / 2, j * cell + (i % 2) * cell / 2)
                   for i in range(-40, 41) for j in range(-80, 81)]
    elif kind == "diamonds":
        side = cell - wall
        rad = side * math.sqrt(2) / 2
        shape = f"rotate(45) square({side:.3f}, center=true);"
        u = cell / math.sqrt(2)
        lattice = [((i + j) * u, (i - j) * u) for i in range(-60, 61) for j in range(-60, 61)]
    elif kind == "stars":
        rad = (cell - wall) / 2
        shape = f"polygon({pts_scad(_star(rad))});"
        lattice = [(i * cell + (j % 2) * cell / 2, j * cell * 0.87) for i in range(-40, 41) for j in range(-80, 81)]
    else:  # dots
        rad = min(cell * 0.6, cell - wall) / 2
        shape = f"circle(r={rad:.3f}, $fn=24);"
        lattice = [(i * cell + (j % 2) * cell / 2, j * cell * 0.87) for i in range(-40, 41) for j in range(-80, 81)]
    cells = [(x, y) for x, y in lattice if abs(x) <= xmax and ymin <= y <= ymax and ok(x, y, rad)]
    return cells, shape, rad


def _rect_dist(x, y, rect):
    x0, y0, x1, y1 = rect
    return math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))


# ---------- shared pieces ----------

def lowest_inside(poly, length):
    y = 0.0
    while y < length and not inside((0, y), poly):
        y += 0.1
    return y


def place_hole(p, poly, clip, rail, warnings):
    """Return dict(hcy, r, tab, tcy, tr) or None. Hole sits near the bottom end with >= 2 mm of material."""
    r = p["hole_d"] / 2
    y0 = lowest_inside(poly, p["length"])
    if not clip:
        y = y0
        while y < p["length"] / 2:
            if clearance((0, y), poly) >= r + 2.0:
                return {"hcy": y, "r": r, "tab": False}
            y += 0.25
    tr = r + 2.5
    top = y0 + (min(max(rail - 0.5, 1.2), rail - 0.1) if clip else 3.5)
    cy = top - tr
    return {"hcy": cy, "r": r, "tab": True, "tcy": cy, "tr": tr}


def card(parts, layer_h):
    """Print settings plus filament-swap layers for single-nozzle printers."""
    swaps = {}
    for part in parts:
        if part["z0"] <= 1e-6:
            continue
        layer = 1 if part["z0"] <= 0.2 else math.ceil(1.5 + (part["z0"] - 0.2) / layer_h - 1e-9)
        swaps.setdefault(layer, (part["z0"], []))[1].append(part["name"])
    notes = ["Print flat side down, no supports."]
    if len({part["z0"] for part in parts if part["z0"] > 0}) < len([x for x in parts if x["z0"] > 0]):
        notes.append("Parts that start on the same layer (for example Silhouette and Text) can share one filament "
                     "on a single-nozzle printer; with an AMS assign a filament to each part.")
    return {
        "layer_height": layer_h, "first_layer": 0.2, "walls": 2, "infill": 100, "supports": "none",
        "orientation": "flat side down",
        "swaps": [{"layer": k, "z": round(z, 2), "parts": names} for k, (z, names) in sorted(swaps.items())],
        "notes": notes,
    }


def hex_color(v):
    return "#%02x%02x%02x" % (v, v, v)


# ---------- plans ----------

def _art_placement(p, polys, extra_limit=None):
    x0, y0, x1, y1 = bbox(polys)
    aw, ah = x1 - x0, y1 - y0
    s = min(p["art_width"] / aw, p["art_height"] / ah)
    if extra_limit:
        s = min(s, extra_limit(aw, ah))
    return x0, y0, aw, ah, s


def _art_masks(polys, x0, y0, aw, ah, s):
    """Raster of the whole art at PPM, rows top to bottom."""
    wpx, hpx = math.ceil(aw * s * PPM) + 1, math.ceil(ah * s * PPM) + 1
    return raster_polys(polys, lambda x, y: ((x - x0) * s * PPM, (ah - (y - y0)) * s * PPM), wpx, hpx)


def plan_standard(p, polys, lines):
    w, length, thick = p["width"], p["length"], p["thickness"]
    clip, peek = p["style"] == "clip", bool(p["peek"])
    shape = "square" if peek else p["bottom"]
    rail, gap, border, raise_h, cr = p["rail"], p["gap"], p["border"], p["art_raise"], p["corner_r"]
    warnings = []
    if clip and w - 2 * (rail + gap) < 3:
        raise ValueError("Body is too narrow for the clip. Widen it or reduce the rail/gap.")
    x0, y0, aw, ah, s = _art_placement(p, polys)
    art_w, art_h = aw * s, ah * s
    ht = art_h * p["peek_split"] if peek else art_h
    hb = art_h - ht
    overlap = min(p["overlap"], ht * 0.8)
    ovb = min(p["overlap"], hb * 0.8, rail if clip else 99.0) if peek else 0.0
    yb0 = length - overlap  # bottom of the unsplit art
    ysplit = yb0 + hb
    out_poly = body_polygon(shape, w, length, length)
    out_ext = body_polygon(shape, w, length + 100, length)
    ins = (rail + gap) if clip else 0.0
    slot_top = length - overlap - rail
    sticker_lo = yb0 - border  # lowest point of the top sticker
    top_y = yb0 + ht
    bottom_y = min(0.0, ovb - hb) if peek else 0.0

    # tassel hole
    hole = None
    if p["hole"]:
        if peek:
            warnings.append("Tassel hole is disabled when the split peek is on.")
        else:
            hole = place_hole(p, out_poly, clip, rail, warnings)
            if hole["tab"]:
                bottom_y = min(bottom_y, hole["tcy"] - hole["tr"])
    ko = (hole["r"] + 2.0 + 1.0) if hole else 0.0
    zone_lo = 0.0
    if peek:
        zone_lo = ovb + border + TEXT_MARGIN
    if hole:
        area_top = hole["tcy"] + hole["tr"] if hole["tab"] else hole["hcy"] + hole["r"] + 2.0
        zone_lo = max(zone_lo, area_top + TEXT_MARGIN)

    # text
    text = None
    if lines:
        text = fit_text(lines, p["font"], p["text_size"], out_poly, ins + TEXT_MARGIN,
                        sticker_lo - TEXT_MARGIN, zone_lo)
        if text["size"] < text["wanted"] - 0.01 and p["text_size"] > 0:
            warnings.append(f"Text was reduced to {text['size']} mm letters to fit.")

    # pattern cutouts
    cells, cell_scad = [], ""
    if p["pattern"] != "none":
        tongue = w - 2 * (rail + gap)
        if clip and tongue < 10:
            warnings.append("Pattern ignored: the clip tongue is narrower than 10 mm.")
        else:
            margin = 2.5 + ins
            y_hi = sticker_lo - 2.5
            y_lo = (ovb + border + 2.5) if peek else 0.0
            trect = text["rect"] if text else None

            def ok(x, y, rad):
                if clearance((x, y), out_poly) < margin + rad or y + rad > y_hi or y - rad < y_lo:
                    return False
                if trect and _rect_dist(x, y, trect) < rad + TEXT_MARGIN:
                    return False
                if hole and math.hypot(x, y - hole["hcy"]) < ko + rad:
                    return False
                return True

            cells, cell_scad, _ = pattern_cells(p["pattern"], p["cell"], w / 2, 0, length, ok)
            if not cells:
                warnings.append("Pattern ignored: no room for whole cells; try a smaller cell size.")
            elif len(cells) > 700:
                warnings.append("Pattern ignored: too many cells; use a larger cell size.")
                cells = []

    x1o = aw / 2  # centered: x_mm = (x - x0 - aw/2) * s
    art_scad = "module art_raw() { " + polygon_scad(polys, lambda x, y: ((x - x0 - x1o) * s, yb0 + (y - y0) * s)) + " }\n"

    common = f"""// generated by bookmark-maker
$fn = 64;
BIG = 1000;
CR = {cr}; CLIP = {int(clip)}; RAIL = {rail}; GAP = {gap}; W = {w}; B = {border}; SLOT_TOP = {slot_top:.3f};
PEEK = {int(peek)}; HB = {hb:.3f}; YSPLIT = {ysplit:.3f}; OVB = {ovb:.3f};
OUT = {pts_scad(out_poly)};
OUT_EXT = {pts_scad(out_ext)};
module rnd() {{ if (CR > 0) offset(r=CR) offset(delta=-CR) children(); else children(); }}
module outline() {{ rnd() polygon(OUT); }}
module outline_ext() {{ rnd() polygon(OUT_EXT); }}
module slot() {{ if (CLIP) difference() {{
  intersection() {{ offset(delta=-RAIL) outline(); translate([-W, -BIG]) square([2 * W, SLOT_TOP + BIG]); }}
  offset(delta=-(RAIL + GAP)) outline_ext();
}} }}
module art_top() {{ translate([0, -HB]) intersection() {{ art_raw(); translate([-BIG, YSPLIT]) square([2 * BIG, BIG]); }} }}
module art_bot() {{ translate([0, OVB - YSPLIT]) intersection() {{ art_raw(); translate([-BIG, YSPLIT - BIG]) square([2 * BIG, BIG]); }} }}
module art_all() {{ if (PEEK) {{ art_top(); art_bot(); }} else art_raw(); }}
module sticker() {{ if (B > 0) offset(r=B) art_all(); else art_all(); }}
module tab() {{ {f"translate([0, {hole['tcy']:.3f}]) circle(r={hole['tr']:.3f});" if hole and hole["tab"] else ""} }}
module hole() {{ {f"translate([0, {hole['hcy']:.3f}]) circle(d={p['hole_d']}, $fn=48);" if hole else ""} }}
module patterns() {{ {f"for (c = {pts_scad(cells)}) translate(c) {cell_scad}" if cells else ""} }}
module text2d() {{ {text["scad"] if text else ""} }}
module base() {{ union() {{
  difference() {{ outline(); slot(); }}
  difference() {{ sticker(); slot(); }}
  tab();
}} }}
module base_cut() {{ difference() {{ base(); hole(); patterns(); }} }}
"""
    parts = []
    engraved = text and p["text_mode"] == "engraved"
    depth = min(0.6, thick * 0.5)
    if engraved:
        body = [("body_a", f"linear_extrude({thick - depth:.3f}) base_cut();", ART),
                ("body_b", f"translate([0,0,{thick - depth:.3f}]) linear_extrude({depth:.3f}) "
                           "difference() { base_cut(); text2d(); }", ART)]
    else:
        body = [("body", f"linear_extrude({thick}) base_cut();", ART)]
    parts.append({"name": "Body", "z0": 0.0, "z1": thick, "pieces": body, "color": "#f4f1ea"})
    if raise_h > 0:
        parts.append({"name": "Silhouette", "z0": thick, "z1": thick + raise_h, "color": "#2b3a55",
                      "pieces": [("silhouette", f"translate([0,0,{thick}]) linear_extrude({raise_h}) "
                                                "difference() { art_all(); hole(); }", ART)]})
    if text and p["text_mode"] == "raised":
        th = p["text_height"]
        parts.append({"name": "Text", "z0": thick, "z1": thick + th, "color": "#c8553d",
                      "pieces": [("text", f"translate([0,0,{thick}]) linear_extrude({th}) text2d();", [])]})

    # loose-piece check on the final footprint
    top_px = round(ht * PPM)
    full = _art_masks(polys, x0, y0, aw, ah, s)
    if peek:
        pieces = [(full.crop((0, 0, full.width, top_px)), -art_w / 2, yb0 + ht),
                  (full.crop((0, top_px, full.width, full.height)), -art_w / 2, ovb)]
        pieces = [pc for pc in pieces if pc[0].height > 0]
    else:
        pieces = [(full, -art_w / 2, yb0 + art_h)]
    return {
        "common": common, "files": {"art.scad": art_scad}, "parts": parts, "warnings": warnings, "card": card(parts, 0.2),
        "outline": "base_cut();", "art_outline": "union() { art_all(); text2d(); }", "loose": (out_poly, pieces, border),
        "layout": {"total_w": round(max(art_w + 2 * border, w), 1),
                   "total_h": round(top_y - bottom_y + border, 1), "art_w": round(art_w, 2),
                   "art_h": round(art_h, 2), "text_size": text["size"] if text else None,
                   "in_book": round(thick + (p["text_height"] if text and p["text_mode"] == "raised" else 0), 2),
                   "page_line": None if peek else round(yb0, 2)},
    }


def _ink_px(mask, box):
    """Number of art pixels of an L mask inside box (clipped)."""
    x0, y0, x1, y1 = (max(0, round(box[0])), max(0, round(box[1])),
                      min(mask.width, round(box[2])), min(mask.height, round(box[3])))
    if x1 <= x0 or y1 <= y0:
        return 0
    return mask.crop((x0, y0, x1, y1)).histogram()[255]


def _keep_largest(mask, grow_px):
    """Drop art pieces that won't join the main piece once outlined by grow_px; returns (mask, dropped)."""
    f = max(1, max(mask.size) // 300)
    small = mask.resize((max(1, mask.width // f), max(1, mask.height // f)), Image.BILINEAR).point(
        lambda v: 255 if v >= 64 else 0)
    k = 2 * max(1, round(grow_px / f)) + 1
    grown = small.filter(ImageFilter.MaxFilter(k))
    w, h = grown.size
    data = bytearray(grown.point(lambda v: 1 if v else 0).tobytes())
    comps = []
    for start in range(len(data)):
        if data[start] != 1:
            continue
        data[start] = 2
        pix, i = [start], 0
        while i < len(pix):
            q = pix[i]
            i += 1
            x, y = q % w, q // w
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and data[ny * w + nx] == 1:
                    data[ny * w + nx] = 2
                    pix.append(ny * w + nx)
        comps.append(pix)
    if len(comps) <= 1:
        return mask, 0
    keep = Image.new("L", (w, h), 0)
    kp = keep.load()
    for q in max(comps, key=len):
        kp[q % w, q // w] = 255
    keep = keep.resize(mask.size, Image.NEAREST).filter(ImageFilter.MaxFilter(2 * f + 1))
    return ImageChops.multiply(mask, keep), len(comps) - 1


def paws_prepare(p, mask):
    """Place the tongue on the art mask (cropped, 255 = art) and clear the art around it below the page line.

    Returns (clean mask, tongue dict in mm, warnings). The tongue goes where it removes the least art (between
    the paws when there is a gap), close to the requested position, and must join solid art above the line.
    """
    W, H = mask.size
    s = min(p["art_width"] / W, p["art_height"] / H)  # mm per px, same as _art_placement on the traced art
    art_w, art_h = W * s, H * s
    drop = min(max(art_h * (1 - p["page_line"]), 3.0), art_h * 0.6)
    gap, border = p["gap"], p["border"]
    line_row = H - drop / s
    tw_req = min(p["width"], art_w - 2 * gap - 4)
    if tw_req < 6:
        raise ValueError("The art is too narrow for a tongue. Make the art wider or the tongue narrower.")
    tc_req = (p["slot_center"] - 0.5) * art_w

    def col(x_mm):
        return (x_mm + art_w / 2) / s

    def reach(tc, tw):
        xs = [round(col(tc + dx)) for dx in (-tw / 4, 0, tw / 4)]
        for row in range(int(line_row) - 1, -1, -1):
            if all(0 <= x < W and mask.getpixel((x, row)) for x in xs):
                return (H - row) * s
        return None

    # paws = runs of art columns along the bottom few mm of the art; a tongue that eats most of one is bad
    band = mask.crop((0, round(max(line_row, H - 4 / s)), W, H))
    cols = [any(band.getpixel((x, y)) for y in range(0, band.height, max(1, band.height // 10))) for x in range(W)]
    paws, start = [], None
    for x, ink in enumerate(cols + [False]):
        if ink and start is None:
            start = x
        elif not ink and start is not None:
            if (x - start) * s >= 2:
                paws.append((start, x))
            start = None

    def lost(zone):
        bad = 0
        for a, b in paws:
            overlap = max(0, min(b, zone[2]) - max(a, zone[0]))
            bad += overlap / (b - a) > 0.6
        return bad

    best = None
    for tw in sorted({tw_req, 14.0, 12.0, 10.0, 8.0}, reverse=True):
        if tw > tw_req:
            continue
        lim = art_w / 2 - gap - 2 - tw / 2
        for k in range(-20, 21):
            tc = max(-lim, min(lim, tc_req + k * art_w * 0.025))
            zone = (col(tc - tw / 2 - gap - border), line_row - (gap + border) / s, col(tc + tw / 2 + gap + border), H)
            cut = _ink_px(mask, zone) * s * s  # mm^2 of art the slot would remove
            score = cut + 3 * abs(tc - tc_req) + 25 * (tw_req - tw) + 2000 * lost(zone)
            if best is None or score < best[0]:
                r = reach(tc, tw)
                if r is not None:
                    best = (score, tc, tw, r, zone)
    if best is None:
        raise ValueError("Couldn't find solid art above the page line to join the tongue to. Lower the page line.")
    _, tc, tw, r, zone = best
    clean = mask.copy()
    ImageDraw.Draw(clean).rectangle([round(v) for v in zone], fill=0)
    clean, dropped = _keep_largest(clean, border / s)
    warnings = []
    if abs(tc - tc_req) > 1 or tw < tw_req - 0.1:
        warnings.append(f"Placed the tongue ({tw:.0f} mm wide) between the paws.")
    if dropped:
        warnings.append(f"Removed {dropped} small bit(s) next to the tongue that would have printed loose.")
    return clean, {"tc": tc, "tw": tw, "reach": r, "drop": drop, "frame": (W, H), "s": s}, warnings


def plan_paws(p, polys, lines, tongue):
    """Pet sits on the top edge of the book; its lower part (paws) hangs in front of the page.

    A thin tongue goes behind the page. It is cut free from the paws by a slot (like the paperclip), so in
    use the page slides between the tongue (behind) and the paws (in front). Everything is one flat print.
    """
    tw, length, thick = p["width"], p["length"], p["thickness"]
    gap, border, raise_h, cr = p["gap"], p["border"], p["art_raise"], p["corner_r"]
    warnings = []
    if p["hole"]:
        warnings.append("Tassel hole is not available for paws over the page.")
    if p["pattern"] != "none":
        warnings.append("Pattern cutouts are not available for paws over the page.")
    (aw, ah), s = tongue["frame"], tongue["s"]
    x0 = y0 = 0.0  # polys are in the mask frame, so the page line stays put even if paws were trimmed
    art_w, art_h = aw * s, ah * s
    drop, tc, tw, reach = tongue["drop"], tongue["tc"], tongue["tw"], tongue["reach"]
    pl = length  # page line: top edge of the book
    yb0 = pl - drop
    full = _art_masks(polys, x0, y0, aw, ah, s)
    t_top = yb0 + reach + 3.0
    tongue = [(tc + x, y) for x, y in body_polygon(p["bottom"] if p["bottom"] != "taper" else "round",
                                                    tw, t_top, length)]

    text = None
    if lines:
        text = fit_text(lines, p["font"], p["text_size"], [(x - tc, y) for x, y in tongue], TEXT_MARGIN,
                        pl - gap - TEXT_MARGIN, 0.0)
        text["scad"] = f"translate([{tc:.3f},0]) {{ {text['scad']} }}"
        if text["size"] < text["wanted"] - 0.01 and p["text_size"] > 0:
            warnings.append(f"Text was reduced to {text['size']} mm letters to fit.")

    art_scad = "module art_raw() { " + polygon_scad(
        polys, lambda x, y: ((x - x0) * s - art_w / 2, yb0 + (y - y0) * s)) + " }\n"
    common = f"""// generated by bookmark-maker (paws over the page)
$fn = 64;
BIG = 1000; B = {border}; CR = {cr}; GAP = {gap}; PL = {pl:.3f};
TONGUE = {pts_scad(tongue)};
module rnd() {{ if (CR > 0) offset(r=CR) offset(delta=-CR) children(); else children(); }}
module art_all() {{ art_raw(); }}
module tongue() {{ rnd() polygon(TONGUE); }}
module tongue_low() {{ intersection() {{ tongue(); translate([-BIG, -BIG]) square([2 * BIG, BIG + PL]); }} }}
module slot() {{ offset(delta=GAP) tongue_low(); }}
module sticker() {{ if (B > 0) offset(r=B) art_all(); else art_all(); }}
module text2d() {{ {text["scad"] if text else ""} }}
module base_cut() {{ union() {{ tongue(); difference() {{ sticker(); slot(); }} }} }}
"""
    parts = [{"name": "Body", "z0": 0.0, "z1": thick, "color": "#f4f1ea",
              "pieces": [("body", f"linear_extrude({thick}) base_cut();", ART)]}]
    if raise_h > 0:
        parts.append({"name": "Silhouette", "z0": thick, "z1": thick + raise_h, "color": "#2b3a55",
                      "pieces": [("silhouette", f"translate([0,0,{thick}]) linear_extrude({raise_h}) "
                                                "difference() { art_all(); slot(); }", ART)]})
    if text:
        th = p["text_height"]
        parts.append({"name": "Text", "z0": thick, "z1": thick + th, "color": "#c8553d",
                      "pieces": [("text", f"translate([0,0,{thick}]) linear_extrude({th}) text2d();", [])]})
    in_book = thick + max(raise_h, p["text_height"] if text else 0)
    cd = card(parts, 0.2 if thick >= 1.0 else 0.12)
    cd["notes"].append("Slide the tongue behind a page so the paws hang in front of it; the pet sits on top of the book.")
    return {
        "common": common, "files": {"art.scad": art_scad}, "parts": parts, "warnings": warnings, "card": cd,
        "outline": "base_cut();", "art_outline": "union() { difference() { art_all(); slot(); } text2d(); }",
        "loose": (tongue, [(full, -art_w / 2, yb0 + art_h)], border),
        "layout": {"total_w": round(max(art_w + 2 * border, tw), 1), "total_h": round(yb0 + art_h + border, 1),
                   "art_w": round(art_w, 2), "art_h": round(art_h, 2), "text_size": text["size"] if text else None,
                   "page_line": round(pl, 2), "in_book": round(in_book, 2),
                   "tongue": [round(tc - tw / 2, 2), round(tc + tw / 2, 2)]},
    }


def plan_corner(p, polys, lines):
    leg, border, raise_h, cr = p["corner_leg"], p["border"], p["art_raise"], p["corner_r"]
    warnings = []
    for key, label in (("hole", "Tassel hole"), ("peek", "Split peek")):
        if p[key]:
            warnings.append(f"{label} is not available for the corner style.")
    if lines:
        warnings.append("Text is not available for the corner style.")
    if p["pattern"] != "none":
        warnings.append("Pattern cutouts are not available for the corner style.")
    x0, y0, aw, ah, s = _art_placement(p, polys, lambda a, b: (leg + 8 - 2 * (border + 0.5)) / (a + b))
    art_w, art_h = aw * s, ah * s
    ox = oy = -4.0  # art lower-left corner: overhangs the right-angle corner only
    top = PLATE * 2 + PAGE_GAP
    art_scad = "module art_raw() { " + polygon_scad(
        polys, lambda x, y: (ox + (x - x0) * s, oy + (y - y0) * s)) + " }\n"
    tri = [(0, 0), (leg, 0), (0, leg)]
    common = f"""// generated by bookmark-maker (corner)
$fn = 64;
BIG = 1000; LEG = {leg}; WALL = {CORNER_WALL}; B = {border}; CR = {cr};
module rnd() {{ if (CR > 0) offset(r=CR) offset(delta=-CR) children(); else children(); }}
module tri() {{ rnd() polygon([[0,0],[LEG,0],[0,LEG]]); }}
module walls() {{ difference() {{ tri(); polygon([[WALL,WALL],[LEG-WALL,WALL],[WALL,LEG-WALL]]); }} }}
module half() {{ polygon([[-BIG,-BIG],[-BIG,LEG+BIG],[LEG+BIG,-BIG]]); }}
module art_all() {{ art_raw(); }}
module sticker() {{ intersection() {{ if (B > 0) offset(r=B) art_all(); else art_all(); half(); }} }}
"""
    pieces = [
        ("body_plate", f"linear_extrude({PLATE}) tri();"),
        ("body_walls", f"translate([0,0,{PLATE}]) linear_extrude({PAGE_GAP}) walls();"),
        ("body_top", f"translate([0,0,{PLATE + PAGE_GAP}]) linear_extrude({PLATE}) tri();"),
        ("body_flange", f"linear_extrude({top}) difference() {{ sticker(); tri(); }}"),
    ]
    parts = [{"name": "Body", "z0": 0.0, "z1": top, "color": "#f4f1ea",
              "pieces": [(a, b, ART) for a, b in pieces]}]
    if raise_h > 0:
        parts.append({"name": "Silhouette", "z0": top, "z1": top + raise_h, "color": "#2b3a55",
                      "pieces": [("silhouette", f"translate([0,0,{top}]) linear_extrude({raise_h}) "
                                                "intersection() { art_all(); half(); }", ART)]})
    full = _art_masks(polys, x0, y0, aw, ah, s)
    cd = card(parts, 0.2)
    cd["notes"].append("The top plate bridges a 0.8 mm page gap: print slowly with bridging enabled; "
                       "slide the page corner in from the open long edge.")
    return {
        "common": common, "files": {"art.scad": art_scad}, "parts": parts, "warnings": warnings, "card": cd,
        "outline": "union() { tri(); sticker(); }", "art_outline": "intersection() { art_all(); half(); }", "loose": (tri, [(full, ox, oy + art_h)], border),
        "layout": {"total_w": round(leg + 4 + border, 1), "total_h": round(leg + 4 + border, 1),
                   "art_w": round(art_w, 2), "art_h": round(art_h, 2), "text_size": None},
    }


def plan_photo(p, levels_polys, size_px, lines):
    w, length, thick, cr = p["width"], p["length"], p["thickness"], p["corner_r"]
    n = len(levels_polys)
    warnings = []
    if lines:
        warnings.append("Text is not available in photo mode.")
    for key, label in (("peek", "Split peek"), ("pattern", "Pattern cutouts")):
        if p[key] and p[key] != "none":
            warnings.append(f"{label} is not available in photo mode.")
    out_poly = body_polygon("square", w, length, length)
    hole = None
    if p["hole"]:
        hole = place_hole(p, out_poly, False, 0, warnings)
    sx, sy = w / size_px[0], length / size_px[1]
    files = {}
    for k, polys in enumerate(levels_polys, 1):
        files[f"lvl{k}.scad"] = f"module lvl{k}() {{ " + polygon_scad(
            polys, lambda x, y: (x * sx - w / 2, y * sy)) + " }\n"
    common = f"""// generated by bookmark-maker (photo)
$fn = 64;
CR = {cr};
OUT = {pts_scad(out_poly)};
module rnd() {{ if (CR > 0) offset(r=CR) offset(delta=-CR) children(); else children(); }}
module outline() {{ rnd() polygon(OUT); }}
module hole() {{ {f"translate([0, {hole['hcy']:.3f}]) circle(d={p['hole_d']}, $fn=48);" if hole else ""} }}
module base_cut() {{ difference() {{ outline(); hole(); }} }}
"""
    parts = [{"name": "Base", "z0": 0.0, "z1": thick, "color": "#f4f1ea",
              "pieces": [("base", f"linear_extrude({thick}) base_cut();", [])]}]
    for k in range(1, n + 1):
        z0 = thick + (k - 1) * LEVEL_H
        shade = hex_color(round(205 - (k - 1) * (170 / max(n - 1, 1))))
        parts.append({"name": f"Level {k}", "z0": z0, "z1": z0 + LEVEL_H, "color": shade,
                      "pieces": [(f"level_{k}", f"translate([0,0,{z0:.3f}]) linear_extrude({LEVEL_H}) "
                                                f"intersection() {{ difference() {{ lvl{k}(); hole(); }} outline(); }}",
                                  [f"lvl{k}.scad"])]})
    cd = card(parts, 0.08)
    cd["notes"].append("Photo mode: each level adds 0.24 mm (3 layers at 0.08 mm). Print slowly for best detail.")
    return {
        "common": common, "files": files, "parts": parts, "warnings": warnings, "card": cd,
        "outline": "base_cut();", "loose": None,
        "layout": {"total_w": w, "total_h": length, "art_w": w, "art_h": length, "text_size": None,
                   "in_book": round(thick + n * LEVEL_H, 2)},
    }
