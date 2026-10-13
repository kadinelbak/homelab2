"""Smoke test for a running bookmark-maker (stdlib + Pillow). Usage: BASE_URL=http://host:port python smoke_test.py"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8105").rstrip("/")
NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


def blob_png(with_dot=False):
    img = Image.new("RGB", (400, 480), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((100, 180, 300, 400), fill="black")  # body
    d.ellipse((100, 90, 170, 190), fill="black")  # ears
    d.ellipse((230, 90, 300, 190), fill="black")
    d.ellipse((160, 230, 190, 260), fill="white")  # eye hole
    if with_dot:
        d.ellipse((312, 300, 330, 318), fill="black")  # floating dot close to the body
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def photo_png():
    img = Image.new("L", (300, 400), 255)
    d = ImageDraw.Draw(img)
    for i, shade in enumerate((200, 140, 80, 20)):
        d.ellipse((40 + i * 25, 60 + i * 40, 260 - i * 25, 330 - i * 20), fill=shade)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def cat_photo():
    """A sitting cat on a plain background: head, ears, body, two front legs with a gap, tail."""
    img = Image.new("RGB", (600, 500), (186, 214, 235))
    d = ImageDraw.Draw(img)
    fur = (120, 78, 40)
    d.ellipse((190, 170, 410, 430), fill=fur)  # body
    d.ellipse((220, 60, 380, 200), fill=fur)  # head
    d.polygon([(228, 110), (240, 30), (290, 80)], fill=fur)  # ears
    d.polygon([(372, 110), (360, 30), (310, 80)], fill=fur)
    d.rectangle((215, 380, 265, 470), fill=fur)  # front legs, gap in the middle
    d.rectangle((335, 380, 385, 470), fill=fur)
    d.ellipse((395, 330, 520, 380), fill=fur)  # tail
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def call(path, data=None):
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, resp.headers.get("Content-Type"), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type"), exc.read()


def make(params, image):
    started = time.time()
    status, _, body = call("/api/make?" + urllib.parse.urlencode(params), image)
    return status, json.loads(body), round(time.time() - started, 1)


def check_3mf(info, expect_parts):
    status, ctype, body = call(info["threemf"])
    assert status == 200 and ctype == "model/3mf", f"3mf status {status} {ctype}"
    zf = zipfile.ZipFile(io.BytesIO(body))
    assert zf.testzip() is None
    root = ET.fromstring(zf.read("3D/3dmodel.model"))
    meshes = [o for o in root.findall(".//m:object", NS) if o.find("m:mesh", NS) is not None]
    comps = root.findall(".//m:component", NS)
    assert len(meshes) == expect_parts == len(comps), f"3mf meshes={len(meshes)} comps={len(comps)} want {expect_parts}"
    for o in meshes:
        assert len(o.findall(".//m:triangle", NS)) > 0, "empty mesh in 3mf"
    cfg = ET.fromstring(zf.read("Metadata/model_settings.config"))
    assert len(cfg.findall(".//part")) == expect_parts
    status, ctype, stl = call(info["stl"])
    assert status == 200 and ctype == "model/stl" and len(stl) > 1000, "bad combined STL"
    for part in info["parts"]:
        status, _, stl = call(part["url"])
        assert status == 200 and len(stl) > 84, f"bad part STL {part['name']}"


CASES = [
    ("defaults", {}, 2, {}),
    ("flat", {"art_raise": 0}, 1, {}),
    ("solid", {"style": "solid"}, 2, {}),
    ("text raised solid 2 lines", {"style": "solid", "text1": "READ MORE", "text2": "Kadin"}, 3, {}),
    ("text raised clip", {"text1": "BOOK"}, 3, {"size_min": 3.5}),
    ("text engraved", {"style": "solid", "text1": "Hello", "text_mode": "engraved"}, 2, {}),
    ("text liberation serif", {"style": "solid", "text1": "Serif", "font": "liberation-serif"}, 3, {}),
    ("text injection", {"style": "solid", "text1": 'A"); cube(1000); //\\'}, 3, {}),
    ("text too long -> 400", {"style": "solid", "length": 40, "text1": "x" * 30}, 400, {}),
    ("bottom point", {"bottom": "point"}, 2, {}),
    ("bottom swallowtail", {"bottom": "swallowtail", "style": "solid"}, 2, {}),
    ("bottom square", {"bottom": "square"}, 2, {}),
    ("bottom taper", {"bottom": "taper", "style": "solid"}, 2, {}),
    ("hole clip", {"hole": 1}, 2, {}),
    ("hole solid", {"hole": 1, "style": "solid"}, 2, {}),
    ("hole swallowtail clip", {"hole": 1, "bottom": "swallowtail"}, 2, {}),
    ("corner", {"style": "corner"}, 2, {}),
    ("corner flat", {"style": "corner", "art_raise": 0}, 1, {}),
    ("peek solid", {"style": "solid", "peek": 1}, 2, {}),
    ("peek clip", {"peek": 1}, 2, {}),
    ("pattern honeycomb", {"style": "solid", "pattern": "honeycomb"}, 2, {"pattern": True}),
    ("pattern diamonds", {"style": "solid", "pattern": "diamonds"}, 2, {"pattern": True}),
    ("pattern stars", {"style": "solid", "pattern": "stars"}, 2, {"pattern": True}),
    ("pattern dots", {"style": "solid", "pattern": "dots"}, 2, {"pattern": True}),
    ("pattern+text+hole", {"style": "solid", "pattern": "honeycomb", "text1": "Hi", "hole": 1}, 3, {}),
    ("all-in-one", {"style": "solid", "bottom": "swallowtail", "text1": "ABC", "hole": 1, "pattern": "dots", "text_mode": "engraved"}, 2, {}),
]


def v3_flow():
    """Photo -> cutout -> every style's preview, and a full build for the ones that print."""
    failures = 0
    status, _, body = call("/api/cutout", cat_photo())
    cut = json.loads(body)
    if status != 200:
        print("FAIL cutout:", cut)
        return 1
    for key in ("pet", "view", "mask"):
        st, ctype, _ = call(cut[key])
        if st != 200 or ctype != "image/png":
            failures += 1
            print(f"FAIL cutout {key} image: {st} {ctype}")
    print(f"PASS cutout via {cut['method']}, box {cut['box']}")
    st, _, body = call(f"/api/cutout/{cut['id']}", json.dumps({"strokes": [[0.02, 0.02, 0.03, 0]], "smooth": 3}).encode())
    print(("PASS" if st == 200 else "FAIL") + " re-cut with a brush stroke")
    failures += st != 200
    st, _, body = call("/api/cutout/000000000000", b"{}")
    print(("PASS" if st == 400 else "FAIL") + " expired cutout -> 400")
    failures += st != 400
    _, _, body = call("/api/styles")
    for style in json.loads(body):
        q = dict(style["params"], cutout=cut["id"])
        if style["key"] in ("paws", "memorial"):
            q.update(text1="Biscuit")
        try:
            st, _, body = call("/api/preview?" + urllib.parse.urlencode(q), b"")
            info = json.loads(body)
            assert st == 200, f"preview {st}: {info.get('error')}"
            st, ctype, svg = call(info["preview"])
            assert st == 200 and b"<svg" in svg, "preview svg"
            if style["key"] != "photo":
                st, info, secs = make(q, b"")
                assert st == 200, f"make {st}: {info.get('error')}"
                check_3mf(info, len(info["parts"]))
                in_book = info["layout"].get("in_book")
                assert in_book is None or in_book <= 1.5, f"in-book thickness {in_book} mm"
                assert not any(w.get("kind") == "loose" for w in info["warnings"]), info["warnings"]
                card = info["print_card"]
                assert card["grams"] > 0 and card["minutes"] > 0 and card["summary"], "print card estimate"
                if style["key"] == "magnet":
                    assert card.get("pause") and info["layout"]["magnets"] >= 1, "magnet pause layer"
            print(f"PASS style {style['key']}: {info['layout'].get('total_w')} x {info['layout'].get('total_h')} mm")
        except Exception as exc:
            failures += 1
            print(f"FAIL style {style['key']}: {exc}")
    # drag to place: the offset moves the art and comes back as the effective value
    q = dict(style="clip", cutout=cut["id"], art_x=8, art_y=200)
    st, _, body = call("/api/preview?" + urllib.parse.urlencode(q), b"")
    lay = json.loads(body).get("layout", {})
    if st == 200 and lay.get("art_x") == 8 and 0 < lay.get("art_y", 0) <= 6:
        print(f"PASS drag to place: {lay['art_x']}, {lay['art_y']}")
    else:
        failures += 1
        print(f"FAIL drag to place: {st} {lay}")
    return failures


def main():
    status, _, body = call("/health")
    assert status == 200, f"/health {status}"
    status, ctype, page = call("/")
    assert status == 200 and b"Bookmark Maker" in page and b"three.min.js" in page
    failures = 0
    blob, blob_dot = blob_png(), blob_png(True)

    def run(name, params, image, expect, extra=None):
        nonlocal failures
        try:
            status, info, secs = make(params, image)
            if expect == 400:
                assert status == 400 and "error" in info, f"expected 400, got {status}"
                print(f"PASS {name}: 400 {info['error'][:70]} ({secs}s)")
                return info
            assert status == 200, f"status {status}: {info.get('error')}"
            check_3mf(info, expect)
            if extra and extra.get("pattern"):
                assert not any("ignored" in w["message"] for w in info["warnings"]), info["warnings"]
            print(f"PASS {name}: {len(info['parts'])} parts, {info['seconds']}s server / {secs}s total, "
                  f"{len(info['warnings'])} warning(s)")
            return info
        except Exception as exc:  # report and continue
            failures += 1
            print(f"FAIL {name}: {exc}")
            return None

    for name, params, expect, extra in CASES:
        run(name, params, blob, expect, extra)
    for levels in (2, 3, 4):
        info = run(f"photo {levels} levels", {"mode": "photo", "levels": levels}, photo_png(), 1 + levels)
        if info:
            print("     card:", info["print_card"]["layer_height"], [s["layer"] for s in info["print_card"]["swaps"]])
    run("photo contain + hole", {"mode": "photo", "levels": 3, "photo_fit": "contain", "hole": 1}, photo_png(), 4)
    info = run("loose piece warning", {"style": "solid", "border": 0}, blob_dot, 2)
    if info:
        loose = [w for w in info["warnings"] if w.get("kind") == "loose"]
        if loose and loose[0].get("suggested_border"):
            print("     suggestion:", loose[0]["message"])
            info = run("apply suggested outline", {"style": "solid", "border": loose[0]["suggested_border"]}, blob_dot, 2)
            if info and any(w.get("kind") == "loose" for w in info["warnings"]):
                failures += 1
                print("FAIL suggested border still leaves loose pieces")
        else:
            failures += 1
            print("FAIL expected a loose-piece warning with a suggestion:", info["warnings"])
    info = run("no warning when connected", {"style": "solid"}, blob, 2)
    if info and any(w.get("kind") == "loose" for w in info["warnings"]):
        failures += 1
        print("FAIL unexpected loose warning")
    if info:  # recolor endpoint
        status, _, body = call(info["threemf"] + "?colors=ff0000,00ff00")
        zf = zipfile.ZipFile(io.BytesIO(body))
        assert b"#FF0000" in zf.read("3D/3dmodel.model"), "recolor did not apply"
        print("PASS recolor")
    failures += v3_flow()
    print("FAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
