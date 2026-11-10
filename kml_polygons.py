"""Read polygon placemarks from a Google Earth KML / KMZ export.

Pure standard library. Used by both ``kml_to_shapefile.py`` (local conversion)
and ``gee_export.py`` (export through Google Earth Engine).

Each polygon placemark becomes a dict::

    {
        "name": str,
        "description": str,
        "folder": str,                 # "Folder/Subfolder" path inside the KML
        "extended": {key: value},      # <ExtendedData> fields, if any
        "polygons": [                  # one entry per polygon (MultiGeometry -> several)
            [outer_ring, hole_1, ...]  # each ring = [(lon, lat), ...], closed
        ],
    }
"""

from __future__ import annotations

import math
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

Ring = list[tuple[float, float]]

# Mean Earth radius (IUGG), metres.
EARTH_RADIUS_M = 6371008.8


def _local(tag: str) -> str:
    """Strip the XML namespace: '{http://www.opengis.net/kml/2.2}Polygon' -> 'Polygon'."""
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element, name: str) -> ET.Element | None:
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _local(c.tag) == name]


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _strip_html(s: str) -> str:
    """Google Earth descriptions are often HTML; keep plain text for the DBF."""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def read_kml_bytes(path: str | Path) -> bytes:
    """Return the KML document bytes from a .kml or .kmz file."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ValueError(f"{path} is a KMZ but contains no .kml file")
            # doc.kml is the conventional root document.
            names.sort(key=lambda n: (Path(n).name.lower() != "doc.kml", n.count("/"), n))
            return z.read(names[0])
    return path.read_bytes()


def _parse_coords(text: str) -> Ring:
    pts: Ring = []
    for tok in text.split():
        parts = tok.split(",")
        if len(parts) < 2:
            continue
        pts.append((float(parts[0]), float(parts[1])))
    # Drop consecutive duplicates.
    dedup: Ring = []
    for p in pts:
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    if dedup and dedup[0] != dedup[-1]:
        dedup.append(dedup[0])
    return dedup


def _ring_from_boundary(boundary: ET.Element) -> Ring | None:
    lr = _child(boundary, "LinearRing")
    if lr is None:
        return None
    ring = _parse_coords(_text(_child(lr, "coordinates")))
    return ring if len(ring) >= 4 else None  # 3 distinct points + closing point


def _polygons_in(geom: ET.Element) -> list[list[Ring]]:
    """Collect polygons from a geometry element (recursing into MultiGeometry)."""
    kind = _local(geom.tag)
    if kind == "Polygon":
        outer_b = _child(geom, "outerBoundaryIs")
        outer = _ring_from_boundary(outer_b) if outer_b is not None else None
        if outer is None:
            return []
        holes = [r for b in _children(geom, "innerBoundaryIs") if (r := _ring_from_boundary(b))]
        return [[outer, *holes]]
    if kind == "MultiGeometry":
        out: list[list[Ring]] = []
        for g in geom:
            out.extend(_polygons_in(g))
        return out
    return []


def _extended_data(pm: ET.Element) -> dict[str, str]:
    data: dict[str, str] = {}
    ed = _child(pm, "ExtendedData")
    if ed is None:
        return data
    for el in ed.iter():
        tag = _local(el.tag)
        if tag == "Data" and el.get("name"):
            data[el.get("name")] = _text(_child(el, "value"))
        elif tag == "SimpleData" and el.get("name"):
            data[el.get("name")] = _text(el)
    return data


def parse_kml(path: str | Path) -> tuple[list[dict], list[str]]:
    """Return (polygon_features, skipped_placemark_descriptions)."""
    root = ET.fromstring(read_kml_bytes(path))
    features: list[dict] = []
    skipped: list[str] = []

    def walk(elem: ET.Element, folders: list[str]) -> None:
        for c in elem:
            tag = _local(c.tag)
            if tag in ("Document", "Folder"):
                name = _text(_child(c, "name"))
                walk(c, folders + [name] if (tag == "Folder" and name) else folders)
            elif tag == "Placemark":
                name = _text(_child(c, "name"))
                polys: list[list[Ring]] = []
                geom_kinds: list[str] = []
                for g in c:
                    if _local(g.tag) in ("Polygon", "MultiGeometry", "Point", "LineString",
                                         "LinearRing", "Model", "Track", "MultiTrack"):
                        geom_kinds.append(_local(g.tag))
                        polys.extend(_polygons_in(g))
                if polys:
                    features.append({
                        "name": name,
                        "description": _strip_html(_text(_child(c, "description"))),
                        "folder": "/".join(folders),
                        "extended": _extended_data(c),
                        "polygons": polys,
                    })
                else:
                    skipped.append(f"{name or '(unnamed)'} [{', '.join(geom_kinds) or 'no geometry'}]")
            else:
                walk(c, folders)

    walk(root, [])
    return features, skipped


# --- geometry helpers ------------------------------------------------------

def signed_area_deg(ring: Ring) -> float:
    """Shoelace area in degree units; > 0 means counter-clockwise."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def ring_area_m2(ring: Ring) -> float:
    """Approximate geodesic area of a ring on a sphere (square metres).

    Uses the spherical-excess line-integral formula; accurate to within a few
    tenths of a percent of the WGS84 ellipsoidal area for typical land parcels.
    """
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        dlon = math.radians(lon2 - lon1)
        # Handle antimeridian crossings.
        if dlon > math.pi:
            dlon -= 2 * math.pi
        elif dlon < -math.pi:
            dlon += 2 * math.pi
        total += dlon * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total) * EARTH_RADIUS_M ** 2 / 2.0


try:  # Exact WGS84 ellipsoidal area when pyproj is installed; spherical fallback otherwise.
    from pyproj import Geod as _Geod

    _GEOD = _Geod(ellps="WGS84")

    def _ring_area(ring: Ring) -> float:
        area, _ = _GEOD.polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])
        return abs(area)
except ImportError:  # pragma: no cover
    _ring_area = ring_area_m2


def polygon_area_m2(polygon: list[Ring]) -> float:
    outer, *holes = polygon
    return max(_ring_area(outer) - sum(_ring_area(h) for h in holes), 0.0)


def feature_area_m2(feature: dict) -> float:
    return sum(polygon_area_m2(p) for p in feature["polygons"])
