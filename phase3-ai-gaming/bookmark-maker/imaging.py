"""Image handling: upload loading, silhouette/photo bitmaps, potrace tracing, loose-piece check."""
import io
import re
import subprocess
from collections import deque

from PIL import Image, ImageChops, ImageDraw, ImageOps

MAX_TRACE_PX = 1200
PAD_PX = 4
_TOKEN = re.compile(r"[MmLlCcHhVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


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
    try:
        return ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    except OSError as exc:
        raise ValueError("Could not read the image. Upload an SVG, PNG or JPEG.") from exc


def silhouette_mask(img, threshold, invert):
    """Return an L image (255 = art) cropped to the art."""
    img = img.convert("RGBA")
    white = Image.new("RGBA", img.size, (255, 255, 255, 255))
    gray = Image.alpha_composite(white, img).convert("L")
    gray.thumbnail((MAX_TRACE_PX, MAX_TRACE_PX))
    art = gray.point(lambda p: 255 if (p < threshold) != bool(invert) else 0)
    box = art.getbbox()
    if not box:
        raise ValueError("No silhouette found. Try moving the threshold slider or toggling invert.")
    return art.crop(box)


def photo_gray(img, width_mm, length_mm, fit, auto_level):
    """Grayscale photo fitted to the body rectangle; returns (L image, px_per_mm)."""
    ppm = min(10.0, 1400.0 / max(width_mm, length_mm))
    size = (max(8, round(width_mm * ppm)), max(8, round(length_mm * ppm)))
    img = img.convert("RGBA")
    img = Image.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img).convert("L")
    if fit == "contain":
        small = ImageOps.contain(img, size)
        canvas = Image.new("L", size, 255)
        canvas.paste(small, ((size[0] - small.width) // 2, (size[1] - small.height) // 2))
        img = canvas
    else:
        img = ImageOps.fit(img, size, Image.LANCZOS)
    if auto_level:
        img = ImageOps.autocontrast(img, cutoff=1)
    return img, ppm


def level_masks(gray, levels):
    """Region k (1..levels) = pixels at least k bands dark; returns L masks (255 = region)."""
    step = 256.0 / (levels + 1)
    dark = ImageOps.invert(gray)
    return [dark.point(lambda p, t=k * step: 255 if p >= t else 0) for k in range(1, levels + 1)]


def _flatten(d, seg):
    toks = _TOKEN.findall(d)
    polys, poly, cur, start, cmd, i = [], None, (0.0, 0.0), (0.0, 0.0), None, 0

    def num():
        nonlocal i
        i += 1
        return float(toks[i - 1])

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if poly and len(poly) >= 3:
                    polys.append(poly)
                poly, cur = None, start
            continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == "M":
            cur = start = (ox + num(), oy + num())
            poly = [cur]
            cmd = "l" if rel else "L"
        elif c == "L":
            cur = (ox + num(), oy + num())
            poly.append(cur)
        elif c == "H":
            cur = ((cur[0] if rel else 0.0) + num(), cur[1])
            poly.append(cur)
        elif c == "V":
            cur = (cur[0], (cur[1] if rel else 0.0) + num())
            poly.append(cur)
        elif c == "C":
            p1 = (ox + num(), oy + num())
            p2 = (ox + num(), oy + num())
            p3 = (ox + num(), oy + num())
            p0 = cur
            for k in range(1, seg + 1):
                t = k / seg
                a, b, cc, dd = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
                poly.append((a * p0[0] + b * p1[0] + cc * p2[0] + dd * p3[0],
                             a * p0[1] + b * p1[1] + cc * p2[1] + dd * p3[1]))
            cur = p3
        else:
            raise ValueError("Unsupported path command from potrace.")
    return polys


def trace(mask, job_dir, name, turdsize=8, seg=6):
    """Trace an L mask (255 = shape) with potrace; returns (polygons in px, y up, (w, h))."""
    bitmap = ImageOps.expand(mask.point(lambda p: 0 if p else 255), border=PAD_PX, fill=255).convert("1")
    pbm, svg = job_dir / f"{name}.pbm", job_dir / f"{name}.svg"
    bitmap.save(pbm)
    subprocess.run(
        ["potrace", str(pbm), "-s", "--turdsize", str(turdsize), "--alphamax", "1", "-o", str(svg)],
        check=True, capture_output=True, timeout=120,
    )
    text = svg.read_text()
    pbm.unlink()
    svg.unlink()
    m = re.search(r"scale\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*\)", text)
    sx, sy = (abs(float(m.group(1))), abs(float(m.group(2)))) if m else (0.1, 0.1)
    polys = []
    for d in re.findall(r'<path[^>]*?\sd="([^"]+)"', text):
        for poly in _flatten(d, seg):
            polys.append([((x * sx) - PAD_PX, (y * sy) - PAD_PX) for x, y in poly])
    return polys, mask.size


def bbox(polys):
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_scad(polys, mapper):
    """OpenSCAD polygon() for several rings; mapper(x, y) -> (x_mm, y_mm)."""
    pts, paths, n = [], [], 0
    for poly in polys:
        ring = poly[:-1] if poly[0] == poly[-1] else poly
        if len(ring) < 3:
            continue
        pts.extend("[%.3f,%.3f]" % mapper(x, y) for x, y in ring)
        paths.append("[" + ",".join(str(k) for k in range(n, n + len(ring))) + "]")
        n += len(ring)
    return f"polygon(points=[{','.join(pts)}],paths=[{','.join(paths)}]);"


def raster_polys(polys, mapper, width_px, height_px):
    """Even-odd raster of rings (px coordinates already mapped by mapper to image px, y down)."""
    canvas = Image.new("1", (width_px, height_px), 0)
    for poly in polys:
        layer = Image.new("1", (width_px, height_px), 0)
        ImageDraw.Draw(layer).polygon([mapper(x, y) for x, y in poly], fill=1)
        canvas = ImageChops.logical_xor(canvas, layer)
    return canvas.convert("L").point(lambda p: 255 if p else 0)


def _dilate(mask, radius):
    if radius <= 0:
        return mask
    out = mask
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius and (dx or dy):
                out = ImageChops.lighter(out, ImageChops.offset(mask, dx, dy))
    return out


def count_components(mask):
    w, h = mask.size
    data = bytearray(mask.tobytes())
    count = 0
    for start in range(len(data)):
        if not data[start]:
            continue
        count += 1
        data[start] = 0
        queue = deque([start])
        while queue:
            p = queue.popleft()
            x, y = p % w, p // w
            for ny in (y - 1, y, y + 1):
                if 0 <= ny < h:
                    for nx in (x - 1, x, x + 1):
                        if 0 <= nx < w and data[ny * w + nx]:
                            data[ny * w + nx] = 0
                            queue.append(ny * w + nx)
    return count


def loose_check(body_pts, art_pieces, border, ppm=2.0):
    """Count connected pieces of body + outlined art.

    art_pieces: list of (L mask image at ppm scale, x_left_mm, y_top_mm). Returns (components, suggested_border)
    where suggested_border is None when the footprint is already connected or cannot be connected by 4 mm.
    """
    xs = [p[0] for p in body_pts] + [x for _, x, _ in art_pieces] + [x + m.width / ppm for m, x, _ in art_pieces]
    ys = [p[1] for p in body_pts] + [y for _, _, y in art_pieces] + [y - m.height / ppm for m, _, y in art_pieces]
    x0, y1 = min(xs) - 6, max(ys) + 6
    size = (round((max(xs) + 6 - x0) * ppm) + 1, round((y1 - (min(ys) - 6)) * ppm) + 1)
    body = Image.new("L", size, 0)
    ImageDraw.Draw(body).polygon([((x - x0) * ppm, (y1 - y) * ppm) for x, y in body_pts], fill=255)
    art = Image.new("L", size, 0)
    for m, x, y in art_pieces:
        art.paste(255, (round((x - x0) * ppm), round((y1 - y) * ppm)), m)

    def comps(b):
        return count_components(ImageChops.lighter(body, _dilate(art, round(b * ppm))))

    now = comps(border)
    if now <= 1:
        return now, None
    b = border + 0.5
    while b <= 4.0 + 1e-9:
        if comps(b) <= 1:
            return now, round(b, 1)
        b += 0.5
    return now, None
