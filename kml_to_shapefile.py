#!/usr/bin/env python3
"""Convert the polygons in a Google Earth KML/KMZ export to an ESRI Shapefile.

No Google Earth Engine account needed. Only dependency: pyshp
(``pip install pyshp``).

Usage:
    python kml_to_shapefile.py my_project.kml                 # -> my_project_polygons.zip
    python kml_to_shapefile.py my_project.kmz -o out/areas     # -> out/areas.shp/.shx/.dbf/.prj/.cpg + out/areas.zip

Output: one polygon feature per Google Earth placemark (MultiGeometry
placemarks become multi-part polygons), WGS84 (EPSG:4326), with attributes
NAME, DESCR, FOLDER, AREA_M2, AREA_HA plus any <ExtendedData> fields.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

try:
    import shapefile  # pyshp
except ImportError:
    sys.exit("Missing dependency: run  pip install pyshp")

from kml_polygons import feature_area_m2, parse_kml, signed_area_deg

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)
TEXT_LEN = 254  # max DBF character field width


def _orient(ring, clockwise: bool):
    """Shapefile spec: outer rings clockwise, holes counter-clockwise."""
    is_cw = signed_area_deg(ring) < 0
    return ring if is_cw == clockwise else ring[::-1]


def _dbf_field_names(keys: list[str], taken: set[str]) -> dict[str, str]:
    """Map arbitrary attribute names to unique DBF names (<= 10 chars, A-Z0-9_)."""
    mapping: dict[str, str] = {}
    for key in keys:
        base = "".join(ch if ch.isalnum() else "_" for ch in key.upper())[:10] or "FIELD"
        name, n = base, 1
        while name in taken:
            suffix = str(n)
            name = base[: 10 - len(suffix)] + suffix
            n += 1
        taken.add(name)
        mapping[key] = name
    return mapping


def write_shapefile(features: list[dict], out_base: Path) -> list[Path]:
    out_base.parent.mkdir(parents=True, exist_ok=True)

    ext_keys: list[str] = []
    for f in features:
        for k in f["extended"]:
            if k not in ext_keys:
                ext_keys.append(k)
    ext_map = _dbf_field_names(ext_keys, {"NAME", "DESCR", "FOLDER", "AREA_M2", "AREA_HA"})

    with shapefile.Writer(str(out_base), shapeType=shapefile.POLYGON, encoding="utf-8") as w:
        w.field("NAME", "C", size=TEXT_LEN)
        w.field("DESCR", "C", size=TEXT_LEN)
        w.field("FOLDER", "C", size=TEXT_LEN)
        w.field("AREA_M2", "N", size=18, decimal=2)
        w.field("AREA_HA", "N", size=16, decimal=4)
        for k in ext_keys:
            w.field(ext_map[k], "C", size=TEXT_LEN)

        for f in features:
            parts = []
            for outer, *holes in f["polygons"]:
                parts.append(_orient(outer, clockwise=True))
                parts.extend(_orient(h, clockwise=False) for h in holes)
            w.poly([[list(p) for p in ring] for ring in parts])
            area = feature_area_m2(f)
            w.record(
                f["name"][:TEXT_LEN],
                f["description"][:TEXT_LEN],
                f["folder"][:TEXT_LEN],
                round(area, 2),
                round(area / 10_000, 4),
                *[str(f["extended"].get(k, ""))[:TEXT_LEN] for k in ext_keys],
            )

    out_base.with_suffix(".prj").write_text(WGS84_PRJ)
    out_base.with_suffix(".cpg").write_text("UTF-8")
    return [out_base.with_suffix(ext) for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kml", type=Path, help="KML or KMZ exported from Google Earth")
    ap.add_argument("-o", "--out", type=Path,
                    help="output path without extension (default: <input>_polygons)")
    ap.add_argument("--no-zip", action="store_true", help="don't bundle the files into a .zip")
    args = ap.parse_args()

    features, skipped = parse_kml(args.kml)
    if not features:
        sys.exit(f"No polygons found in {args.kml}. Skipped placemarks: {skipped or 'none'}")

    out_base = args.out or args.kml.with_name(args.kml.stem + "_polygons")
    files = write_shapefile(features, out_base)

    print(f"Wrote {len(features)} polygon feature(s) to {out_base}.shp")
    for f in features:
        print(f"  - {f['name'] or '(unnamed)'}: {feature_area_m2(f) / 10_000:,.4f} ha")
    if skipped:
        print(f"Skipped {len(skipped)} non-polygon placemark(s): " + "; ".join(skipped))

    if not args.no_zip:
        zip_path = out_base.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, p.name)
        print(f"Zipped shapefile: {zip_path}")


if __name__ == "__main__":
    main()
