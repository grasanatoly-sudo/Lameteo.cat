from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)
from ecmwf.opendata import Client


OUT = Path("data/models/ecmwf/temperature_2m_catalunya.json")
TMP = Path("temperature_2m_ecmwf.grib2")

# Catalunya + a small surrounding margin.
SOUTH, WEST, NORTH, EAST = 40.0, -1.0, 43.5, 4.0

# First production milestone: +0 to +72 h, every 6 h.
STEPS = list(range(0, 73, 6))


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_longitudes(lons: np.ndarray) -> np.ndarray:
    return np.where(lons > 180.0, lons - 360.0, lons)


def read_frame(gid: int) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    step = int(codes_get(gid, "forecastTime"))
    lats = np.asarray(codes_get_array(gid, "latitudes"), dtype=np.float64)
    lons = normalize_longitudes(
        np.asarray(codes_get_array(gid, "longitudes"), dtype=np.float64)
    )
    values_k = np.asarray(codes_get_array(gid, "values"), dtype=np.float64)
    values_c = values_k - 273.15

    mask = (
        (lats >= SOUTH)
        & (lats <= NORTH)
        & (lons >= WEST)
        & (lons <= EAST)
    )
    return step, lats[mask], lons[mask], values_c[mask]


def matrix_from_points(
    lats: np.ndarray,
    lons: np.ndarray,
    values: np.ndarray,
) -> tuple[list[float], list[float], list[list[float | None]]]:
    latitudes = sorted({round(float(v), 6) for v in lats}, reverse=True)
    longitudes = sorted({round(float(v), 6) for v in lons})

    lat_index = {v: i for i, v in enumerate(latitudes)}
    lon_index = {v: i for i, v in enumerate(longitudes)}

    matrix: list[list[float | None]] = [
        [None for _ in longitudes] for _ in latitudes
    ]

    for lat, lon, value in zip(lats, lons, values):
        la = round(float(lat), 6)
        lo = round(float(lon), 6)
        matrix[lat_index[la]][lon_index[lo]] = round(float(value), 1)

    return latitudes, longitudes, matrix


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    client = Client(
        source="ecmwf",
        model="ifs",
        resol="0p25",
        infer_stream_keyword=True,
    )

    result = client.retrieve(
        type="fc",
        stream="oper",
        param="2t",
        step=STEPS,
        target=str(TMP),
    )

    run = result.datetime
    if run.tzinfo is None:
        run = run.replace(tzinfo=timezone.utc)

    frames: dict[str, dict] = {}
    canonical_lats: list[float] | None = None
    canonical_lons: list[float] | None = None
    overall_values: list[float] = []

    with TMP.open("rb") as f:
        while True:
            gid = codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                step, lats, lons, values = read_frame(gid)
                latitudes, longitudes, matrix = matrix_from_points(lats, lons, values)

                if canonical_lats is None:
                    canonical_lats = latitudes
                    canonical_lons = longitudes
                elif latitudes != canonical_lats or longitudes != canonical_lons:
                    raise RuntimeError("ECMWF grid changed between forecast steps.")

                finite = values[np.isfinite(values)]
                overall_values.extend(float(v) for v in finite)

                frames[str(step)] = {
                    "valid_time": iso_utc(run + timedelta(hours=step)),
                    "min_c": round(float(np.nanmin(values)), 1),
                    "max_c": round(float(np.nanmax(values)), 1),
                    "values": matrix,
                }
            finally:
                codes_release(gid)

    missing = [step for step in STEPS if str(step) not in frames]
    if missing:
        raise RuntimeError(f"Missing forecast steps in GRIB: {missing}")

    payload = {
        "ok": True,
        "source": "ECMWF Open Data · IFS",
        "model": "ECMWF IFS",
        "variable": "temperature_2m",
        "label": "Temperatura 2 m",
        "unit": "°C",
        "run": iso_utc(run),
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "resolution_deg": 0.25,
        "bounds": {
            "south": SOUTH,
            "west": WEST,
            "north": NORTH,
            "east": EAST,
        },
        "steps": STEPS,
        "latitudes": canonical_lats,
        "longitudes": canonical_lons,
        "frames": frames,
        "overall_min_c": round(min(overall_values), 1),
        "overall_max_c": round(max(overall_values), 1),
        "attribution": "ECMWF IFS Open Data · CC BY 4.0",
        "licence_url": "https://apps.ecmwf.int/datasets/licences/general/",
    }

    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    if TMP.exists():
        TMP.unlink()

    print(
        f"Wrote {OUT} · run {payload['run']} · "
        f"{len(STEPS)} frames · {len(canonical_lats or [])}×{len(canonical_lons or [])} grid"
    )


if __name__ == "__main__":
    main()
