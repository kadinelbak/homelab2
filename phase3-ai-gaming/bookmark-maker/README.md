# Bookmark Maker

Turn a photo of your pet (or any silhouette) into a multicolor 3MF + STL bookmark for Bambu Studio, in three steps:

1. **Photo.** Upload any photo. The background is removed on the server (IS-Net model, offline). Paint to erase or restore parts, and adjust smoothness. Black-and-white art can use a plain threshold instead.
2. **Pick a look.** A gallery made from your photo: Paws over the page, Peeking, Page clip, Corner biter, Memorial, Photo layers.
3. **Tweak and download.** A few plain controls per look (size, outline, colors, text, thickness), a live flat preview and a "fits in a book" check. Advanced millimetre settings sit in a drawer.

Paws over the page: the pet sits on the top edge of the book. A thin tongue goes behind the page, and the paws hang in front of it, cut free from the tongue by a slot. The tongue is placed automatically where it keeps the paws, and any bits it would cut loose are removed.

Book-safe defaults: everything that goes inside the book is at most 1.5 mm thick (a bank card is 0.76 mm). Every look prints in one piece, flat, with no supports.

Files: `app.py` (HTTP + build pipeline), `cutout.py` (photo to mask), `geometry.py` (shapes and OpenSCAD source), `imaging.py` (tracing), `styles.py` (the looks), `threemf.py` (3MF writer), `page.html` (the page).

## API

- `GET /` - the page. `GET /health` - tools and whether the cutout model is installed. `GET /api/styles` - the looks.
- `POST /api/cutout` (body: image) - returns a cutout id plus `pet`, `view` and `mask` PNG URLs.
- `POST /api/cutout/<id>` (JSON: `method` auto|art, `threshold`, `invert`, `smooth` 0-6, `fill_holes`, `strokes` `[[x, y, r, keep]]` as fractions) - re-cut.
- `POST /api/preview?cutout=<id>&...` - fast flat preview SVG and layout. `POST /api/make?cutout=<id>&...` - full 3MF/STL build. Both also accept an image body instead of `cutout` (v2 behaviour).

Jobs and cutouts are kept under `/data` for 7 days (`BOOKMARK_KEEP_DAYS`). Smoke test: `BASE_URL=http://host:18105 python smoke_test.py`.
