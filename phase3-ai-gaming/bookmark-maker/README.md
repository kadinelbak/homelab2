# Bookmark Maker

Upload a silhouette (SVG, PNG or JPEG) and download a flat, single-color bookmark STL for Bambu Studio. The silhouette sits on top of a standard bookmark body and can overhang its sides.

Pipeline: `rsvg-convert` (SVG only) → Pillow threshold → `potrace` → OpenSCAD → STL. No AI, no CAD GUI.

Options:

- **Body**: Paperclip (a U-shaped slot leaves a springy center tongue that clips over a page) or Solid.
- **Bottom**: Round or Point.
- Defaults: body 24 × 110 mm, 1.5 mm thick, silhouette up to 50 × 60 mm, sinking 6 mm into the top of the body. Clip rail 3 mm, gap 3 mm.

Any part of the silhouette that doesn't touch the rest (a floating dot, say) prints as a loose piece, so pick silhouettes where everything connects.

## API

- `GET /` - upload page.
- `GET /health` - checks `openscad`, `potrace` and `rsvg-convert` are installed.
- `POST /api/make?style=clip&bottom=round&width=24&length=110&thickness=1.5&art_width=50&art_height=60&overlap=6&rail=3&gap=3&threshold=128&invert=0` - body is the raw file; returns JSON with `stl` and `preview` (outline SVG) URLs.

Jobs are kept under `/data/jobs` for 7 days (`BOOKMARK_KEEP_DAYS`).
