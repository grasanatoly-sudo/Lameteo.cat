"""Descarrega geometries oficials ICGC en GeoJSON per al visor Lameteo.cat.

Fonts ArcGIS REST:
- Comarques 1:250.000 (divisions_administratives_wfs/MapServer/11).
- Perímetre de Catalunya 1:500.000 (divisions_administratives_wms/MapServer/23).
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import mapping, shape


OUT = Path("data/cartography")
SOURCE = "https://geoserveis.icgc.cat/vector01/rest/services/"


def round_coordinates(value):
    """Preserve topology while avoiding needlessly precise coordinate strings."""
    if isinstance(value, (list, tuple)) and value:
        if isinstance(value[0], (int, float)):
            return [round(float(value[0]), 5), round(float(value[1]), 5)]
        return [round_coordinates(item) for item in value]
    return value


def simplify_collection(features: list[dict], tolerance: float) -> list[dict]:
    optimized = []
    for feature in features:
        geometry = shape(feature["geometry"])
        simple = geometry.simplify(tolerance, preserve_topology=True)
        item = dict(feature)
        item["geometry"] = mapping(simple)
        item["geometry"]["coordinates"] = round_coordinates(item["geometry"]["coordinates"])
        optimized.append(item)
    return optimized


def download_layer(service: str, layer: int, target: Path, minimum: int, tolerance: float) -> None:
    url = (
        f"{SOURCE}{service}/MapServer/{layer}/query?"
        + urlencode({
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        })
    )
    request = Request(
        url,
        headers={
            "Accept": "application/geo+json, application/json",
            "User-Agent": "Lameteo.cat GIS data updater (https://lameteo.cat)",
        },
    )
    with urlopen(request, timeout=50) as response:
        data = json.load(response)

    if data.get("type") != "FeatureCollection":
        raise RuntimeError(f"{target.name}: unexpected ICGC response {str(data)[:200]}")
    features = data.get("features")
    if not isinstance(features, list) or len(features) < minimum:
        raise RuntimeError(f"{target.name}: too few features: {len(features or [])}")
    if not all(f.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"} for f in features):
        raise RuntimeError(f"{target.name}: contains unexpected geometry types")

    data["features"] = simplify_collection(features, tolerance)
    OUT.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Saved {target}: {len(features)} features, {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    download_layer(
        "divisions_administratives_wfs", 11,
        OUT / "icgc_comarques_250k.geojson", 35, 0.0009,
    )
    download_layer(
        "divisions_administratives_wms", 23,
        OUT / "icgc_catalunya_500k.geojson", 1, 0.0007,
    )
