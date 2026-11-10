#!/usr/bin/env python3
"""Export Google Earth polygons to a Shapefile through Google Earth Engine.

Reads a KML/KMZ exported from Google Earth (web or Pro), turns every polygon
placemark into an ``ee.Feature`` and starts an Earth Engine export task:

  * ``Export.table.toDrive`` with ``fileFormat='SHP'``  (default), and/or
  * ``Export.table.toAsset`` so you can use the polygons in Code Editor scripts.

Requirements:
    pip install earthengine-api
    earthengine authenticate          # once
    A Google Cloud project registered for Earth Engine.

Usage:
    python gee_export.py my_project.kml --project my-gcp-project
    python gee_export.py my_project.kml --project my-gcp-project \
        --folder EarthEngine --prefix my_areas \
        --asset projects/my-gcp-project/assets/my_areas
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    import ee
except ImportError:
    sys.exit("Missing dependency: run  pip install earthengine-api")

from kml_polygons import feature_area_m2, parse_kml


def to_ee_feature(f: dict) -> "ee.Feature":
    polys = [[[list(pt) for pt in ring] for ring in poly] for poly in f["polygons"]]
    geom = ee.Geometry.Polygon(polys[0]) if len(polys) == 1 else ee.Geometry.MultiPolygon(polys)
    props = {
        "name": f["name"],
        "descr": f["description"][:254],
        "folder": f["folder"],
        "area_ha": round(feature_area_m2(f) / 10_000, 4),
        **{k: str(v) for k, v in f["extended"].items()},
    }
    return ee.Feature(geom, props)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kml", type=Path, help="KML or KMZ exported from Google Earth")
    ap.add_argument("--project", required=True, help="Google Cloud project used for Earth Engine")
    ap.add_argument("--folder", default="EarthEngine", help="Google Drive folder for the shapefile")
    ap.add_argument("--prefix", help="output file name prefix (default: KML file name)")
    ap.add_argument("--asset", help="also save as an Earth Engine table asset, e.g. projects/<p>/assets/<name>")
    ap.add_argument("--no-drive", action="store_true", help="skip the Drive shapefile export")
    ap.add_argument("--wait", action="store_true", help="wait for the export task(s) to finish")
    args = ap.parse_args()

    features, skipped = parse_kml(args.kml)
    if not features:
        sys.exit(f"No polygons found in {args.kml}. Skipped placemarks: {skipped or 'none'}")
    if skipped:
        print(f"Skipping {len(skipped)} non-polygon placemark(s): " + "; ".join(skipped))

    ee.Initialize(project=args.project)
    fc = ee.FeatureCollection([to_ee_feature(f) for f in features])
    # GEE-computed area as a cross-check (geodesic, WGS84 ellipsoid).
    fc = fc.map(lambda feat: feat.set("gee_area_ha", feat.geometry().area(maxError=1).divide(10_000)))
    print(f"Built FeatureCollection with {fc.size().getInfo()} polygon feature(s).")

    prefix = args.prefix or args.kml.stem
    tasks = []
    if not args.no_drive:
        tasks.append(ee.batch.Export.table.toDrive(
            collection=fc,
            description=f"{prefix}_shp",
            folder=args.folder,
            fileNamePrefix=prefix,
            fileFormat="SHP",
        ))
    if args.asset:
        tasks.append(ee.batch.Export.table.toAsset(
            collection=fc, description=f"{prefix}_asset", assetId=args.asset,
        ))
    if not tasks:
        sys.exit("Nothing to export (--no-drive without --asset).")

    for t in tasks:
        t.start()
        print(f"Started task {t.id}: {t.config.get('description', '')}")
    print("Track progress at https://code.earthengine.google.com/tasks")

    if args.wait:
        while any(t.active() for t in tasks):
            time.sleep(10)
        for t in tasks:
            st = t.status()
            print(f"{st.get('description')}: {st.get('state')} {st.get('error_message', '')}")
        if not args.no_drive:
            print(f"Shapefile parts ({prefix}.shp/.shx/.dbf/.prj/.cpg) are in Drive folder '{args.folder}'.")


if __name__ == "__main__":
    main()
