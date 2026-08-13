# SCAD AI Generator

Small homelab service for generating and previewing OpenSCAD iterations.

## API

- `GET /` - browser UI.
- `GET /health` - OpenSCAD and config status.
- `POST /api/generate` - JSON body with `prompt`, `iterations`, optional `model`, optional `temperature`.
- `POST /api/preview` - JSON body with `scad`.

Generated runs are stored under `/data/runs`, with each iteration keeping the source `.scad`, rendered `.png`, and exported `.stl`.

The renderer rejects `include`, `use`, and `import` statements so prompts cannot pull arbitrary host files into OpenSCAD jobs.
