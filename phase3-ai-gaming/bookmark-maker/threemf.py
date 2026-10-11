"""STL reading/writing and multicolor 3MF packaging (stdlib only).

A mesh is a flat list of (x, y, z) tuples; every three consecutive vertices form a triangle.
"""
import re
import struct
import zipfile
from xml.sax.saxutils import quoteattr

_VERTEX = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")
BED_CENTER = 128.0


def read_stl(path):
    data = path.read_bytes()
    if data.lstrip()[:5] == b"solid" and b"vertex" in data[:4096] + data[-4096:]:
        return [(float(x), float(y), float(z)) for x, y, z in _VERTEX.findall(data)]
    count = struct.unpack_from("<I", data, 80)[0]
    verts = []
    for rec in struct.iter_unpack("<12fH", data[84:84 + count * 50]):
        verts.extend(((rec[3], rec[4], rec[5]), (rec[6], rec[7], rec[8]), (rec[9], rec[10], rec[11])))
    return verts


def write_stl(path, verts):
    out = [b"bookmark-maker".ljust(80, b" "), struct.pack("<I", len(verts) // 3)]
    for i in range(0, len(verts), 3):
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = verts[i:i + 3]
        ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        norm = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        out.append(struct.pack("<12fH", nx / norm, ny / norm, nz / norm, ax, ay, az, bx, by, bz, cx, cy, cz, 0))
    path.write_bytes(b"".join(out))


def _indexed(verts):
    index, points, tris = {}, [], []
    for v in verts:
        i = index.get(v)
        if i is None:
            i = index[v] = len(points)
            points.append(v)
        tris.append(i)
    keep = []
    for i in range(0, len(tris), 3):
        a, b, c = tris[i:i + 3]
        if a != b and b != c and a != c:
            keep.append((a, b, c))
    return points, keep


def _mesh_xml(verts):
    points, tris = _indexed(verts)
    vx = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in points)
    tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    return f"<mesh><vertices>{vx}</vertices><triangles>{tx}</triangles></mesh>"


def write_3mf(path, parts, title="Bookmark"):
    """parts: list of dicts with name, color ('#rrggbb'), extruder (1-based) and verts."""
    allv = [v for p in parts for v in p["verts"]]
    if not allv:
        raise ValueError("Nothing to export.")
    xs, ys, zs = zip(*allv)
    tx = BED_CENTER - (min(xs) + max(xs)) / 2
    ty = BED_CENTER - (min(ys) + max(ys)) / 2
    tz = -min(zs)
    first_id = 2  # id 1 is the basematerials group
    mats = "".join(f"<base name={quoteattr(p['name'])} displaycolor={quoteattr(p['color'].upper())}/>" for p in parts)
    objects, comps = [], []
    for i, p in enumerate(parts):
        oid = first_id + i
        objects.append(
            f'<object id="{oid}" name={quoteattr(p["name"])} type="model" pid="1" pindex="{i}">{_mesh_xml(p["verts"])}</object>'
        )
        comps.append(f'<component objectid="{oid}"/>')
    root_id = first_id + len(parts)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Title">{title}</metadata><metadata name="Application">bookmark-maker</metadata>'
        f'<resources><basematerials id="1">{mats}</basematerials>{"".join(objects)}'
        f'<object id="{root_id}" name={quoteattr(title)} type="model"><components>{"".join(comps)}</components></object>'
        f'</resources><build><item objectid="{root_id}" printable="1" '
        f'transform="1 0 0 0 1 0 0 0 1 {tx:.5f} {ty:.5f} {tz:.5f}"/></build></model>'
    )
    part_cfg = "".join(
        f'<part id="{first_id + i}" subtype="normal_part"><metadata key="name" value={quoteattr(p["name"])}/>'
        f'<metadata key="extruder" value="{p["extruder"]}"/></part>'
        for i, p in enumerate(parts)
    )
    config = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>'
        f'<object id="{root_id}"><metadata key="name" value={quoteattr(title)}/><metadata key="extruder" value="1"/>'
        f"{part_cfg}</object></config>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model)
        zf.writestr("Metadata/model_settings.config", config)
