# Bookmark Maker

Upload a silhouette (PNG/JPEG), pick a style, download a printable bookmark STL for Bambu Studio.

Pipeline: Pillow threshold → `potrace` (SVG) → OpenSCAD (extrude onto a rounded bookmark base) → STL. No AI, no CAD GUI.

Styles (single color):

- **Raised**: art sits on top of the base (`depth` mm higher).
- **Cut-through**: art is cut out of the base like a stencil. Holes inside the art are filled so no loose islands print.
- **Engraved**: art is sunk `depth` mm into the top face (flush top).

Defaults: 50 × 150 × 2 mm, art at the top up to 60 mm tall, optional tassel hole.

## API

- `GET /` - upload page.
- `GET /health` - checks `openscad` and `potrace` are installed.
- `POST /api/make?style=raised&width=50&length=150&thickness=2&depth=0.8&art_height=60&threshold=128&invert=0&hole=1` - body is the raw image; returns JSON with `stl` and `svg` URLs.

Jobs are kept under `/data/jobs` for 7 days (`BOOKMARK_KEEP_DAYS`).
