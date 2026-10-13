# Bookmark Maker

Turn a photo of your pet (or any silhouette) into a multicolor 3MF + STL bookmark for Bambu Studio, in three steps:

1. **Photo.** Upload any photo. The background is removed on the server (IS-Net model, offline). Paint to erase or restore parts, and adjust smoothness. Black-and-white art can use a plain threshold instead.
2. **Pick a look.** A gallery made from your photo: Paws over the page, Peeking, Page clip, Corner biter, Memorial, Tail out, Magnetic, Photo layers.
3. **Tweak and download.** A few plain controls per look (size, outline, colors, text, thickness), a live flat preview where you drag your pet to move it, and a "fits in a book" check. The print card gives grams, minutes and the color-swap and magnet-pause layers in plain words (also written into the 3MF). Advanced millimetre settings sit in a drawer.

Paws over the page: the pet sits on the top edge of the book. A thin tongue goes behind the page, and the paws hang in front of it, cut free from the tongue by a slot. The tongue is placed automatically where it keeps the paws, and any bits it would cut loose are removed.

Tail out: the chosen end of your pet (feet, left, right or head) sticks out of the bottom of the book. Magnetic: a front and a mirrored back piece; the heads sit above the page and hold 6 x 1 mm disc magnets (pause layer on the print card), and the thin tongues sit on either side of a page.

Book-safe defaults: everything that goes inside the book is at most 1.5 mm thick (a bank card is 0.76 mm). Every look prints in one piece, flat, with no supports.

Files: `app.py` (HTTP + build pipeline), `cutout.py` (photo to mask), `geometry.py` (shapes and OpenSCAD source), `imaging.py` (tracing), `styles.py` (the looks), `threemf.py` (3MF writer), `page.html` (the page).

## API

- `GET /` - the page. `GET /health` - tools and whether the cutout model is installed. `GET /api/styles` - the looks.
- `POST /api/cutout` (body: image) - returns a cutout id plus `pet`, `view` and `mask` PNG URLs.
- `POST /api/cutout/<id>` (JSON: `method` auto|art, `threshold`, `invert`, `smooth` 0-6, `fill_holes`, `strokes` `[[x, y, r, keep]]` as fractions) - re-cut.
- Drag to place: `art_x` / `art_y` (mm) move the art; the layout returns the values actually used.
- `POST /api/preview?cutout=<id>&...` - fast flat preview SVG and layout. `POST /api/make?cutout=<id>&...` - full 3MF/STL build. Both also accept an image body instead of `cutout` (v2 behaviour).

Jobs and cutouts are kept under `/data` for 7 days (`BOOKMARK_KEEP_DAYS`). Smoke test: `BASE_URL=http://host:18105 python smoke_test.py`.
