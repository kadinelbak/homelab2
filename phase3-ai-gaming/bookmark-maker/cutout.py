"""Photo -> clean pet silhouette mask.

Uses the IS-Net "general use" ONNX model (same weights rembg ships) when it and onnxruntime are installed;
otherwise falls back to removing the background color found along the image border. All local, no network.
"""
import os
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

MODEL = Path(os.environ.get("BOOKMARK_CUTOUT_MODEL", "/models/isnet-general-use.onnx"))
WORK_PX = 900  # masks are stored at most this many px on the long side
_session = None


def model_available():
    if not MODEL.is_file():
        return False
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _model_mask(img):
    global _session
    import numpy as np
    import onnxruntime as ort

    if _session is None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
        _session = ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
    rgb = img.convert("RGB")
    arr = np.asarray(rgb.resize((1024, 1024), Image.LANCZOS), dtype=np.float32)
    arr = arr / max(float(arr.max()), 1e-6) - 0.5
    inp = arr.transpose(2, 0, 1)[None]
    pred = _session.run(None, {_session.get_inputs()[0].name: inp})[0][:, 0, :, :]
    lo, hi = float(pred.min()), float(pred.max())
    pred = (pred - lo) / max(hi - lo, 1e-6)
    return Image.fromarray((pred[0] * 255).astype("uint8"), "L").resize(rgb.size, Image.LANCZOS)


def _border_mask(img):
    """Fallback: flood the background in from the image border by color distance."""
    rgb = img.convert("RGB")
    rgb.thumbnail((400, 400))
    w, h = rgb.size
    px = rgb.load()
    edge = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)] + \
           [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    bg = tuple(sorted(c[i] for c in edge)[len(edge) // 2] for i in range(3))
    tol = 60 ** 2

    def is_bg(c):
        return sum((c[i] - bg[i]) ** 2 for i in range(3)) <= tol

    seen = bytearray(w * h)
    q = deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i] or not is_bg(px[x, y]):
            continue
        seen[i] = 1
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                q.append((nx, ny))
    mask = Image.frombytes("L", (w, h), bytes(0 if s else 255 for s in seen))
    return mask.resize(img.size, Image.NEAREST)


def _keep_main(mask, min_frac=0.02):
    """Keep connected pieces of at least min_frac of the largest one; returns (mask, removed_count)."""
    small = mask.copy()
    small.thumbnail((300, 300))
    w, h = small.size
    data = bytearray(small.point(lambda p: 1 if p else 0).tobytes())
    comps = []
    for start in range(len(data)):
        if data[start] != 1:
            continue
        data[start] = 2
        pix, q = [start], deque([start])
        while q:
            p = q.popleft()
            x, y = p % w, p // w
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and data[ny * w + nx] == 1:
                    data[ny * w + nx] = 2
                    pix.append(ny * w + nx)
                    q.append(ny * w + nx)
        comps.append(pix)
    if len(comps) <= 1:
        return mask, 0
    big = max(len(c) for c in comps)
    drop = [c for c in comps if len(c) < big * min_frac]
    if not drop:
        return mask, 0
    eraser = Image.new("L", (w, h), 0)
    ep = eraser.load()
    for c in drop:
        for p in c:
            ep[p % w, p // w] = 255
    eraser = eraser.resize(mask.size, Image.NEAREST).filter(ImageFilter.MaxFilter(5))
    return ImageChops.subtract(mask, eraser), len(drop)


def _fill_holes(mask):
    """Fill enclosed background (e.g. gaps between legs stay; holes inside the body close)."""
    w, h = mask.size
    inv = ImageOps.invert(mask)
    framed = ImageOps.expand(inv, 1, 255)
    ImageDraw.floodfill(framed, (0, 0), 0)
    holes = framed.crop((1, 1, w + 1, h + 1))
    return ImageChops.lighter(mask, holes)


def apply_strokes(mask, strokes):
    """strokes: [[x, y, r, keep]] with x, y, r as fractions of the mask width/height (r of width)."""
    draw = ImageDraw.Draw(mask)
    w, h = mask.size
    for x, y, r, keep in strokes[:2000]:
        cx, cy, rr = x * w, y * h, max(1.0, r * w)
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=255 if keep else 0)
    return mask


def make_mask(img, method="auto", threshold=128, invert=False, smooth=2, fill_holes=True, strokes=None, raw=None):
    """Return (L mask 255 = pet at <= WORK_PX, info dict). info["raw"] is the unsmoothed automatic mask,
    which can be passed back as raw= to re-cut with other settings without running the model again."""
    img = img.copy()
    img.thumbnail((WORK_PX, WORK_PX))
    info = {"method": method}
    if method == "art":  # black-and-white art: plain threshold, as in v2
        rgba = img.convert("RGBA")
        gray = Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba).convert("L")
        mask = gray.point(lambda p: 255 if (p < threshold) != bool(invert) else 0)
    elif raw is not None:
        mask, info["method"] = raw.resize(img.size), raw.info.get("method", "model")
    else:
        if img.mode in ("RGBA", "LA") and img.getextrema()[-1][0] < 250:
            mask, info["method"] = img.getchannel("A"), "transparency"
        elif model_available():
            mask, info["method"] = _model_mask(img), "model"
        else:
            mask, info["method"] = _border_mask(img), "background color"
        mask = mask.point(lambda p: 255 if p >= 128 else 0)
        info["raw"] = mask
    if smooth > 0:
        k = 2 * int(smooth) + 1
        mask = mask.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))  # close small gaps
        mask = mask.filter(ImageFilter.GaussianBlur(smooth * 0.8)).point(lambda p: 255 if p >= 128 else 0)
    if fill_holes and method != "art":
        mask = _fill_holes(mask)
    if strokes:
        mask = apply_strokes(mask, strokes)
    mask, info["removed_specks"] = _keep_main(mask)
    if not mask.getbbox():
        raise ValueError("Couldn't find the pet in this photo. Try a photo with a plainer background.")
    return mask, info
