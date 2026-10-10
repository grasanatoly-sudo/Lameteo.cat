from __future__ import annotations

import json
import math
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


OUT = Path("data/models/ecmwf/v4")
TMP = Path(".tmp_ecmwf_v4")
STEPS = list(range(0, 73, 6))

REGIONS = {
    "catalunya": {"south": 40.0, "west": -1.0, "north": 43.5, "east": 4.0, "factor": 1},
    "peninsula": {"south": 34.5, "west": -10.5, "north": 44.5, "east": 5.0, "factor": 1},
    "mediterrani": {"south": 29.0, "west": -12.0, "north": 48.0, "east": 36.0, "factor": 2},
    "europa": {"south": 30.0, "west": -25.0, "north": 72.0, "east": 45.0, "factor": 2},
}

VARIABLE_META = {
    "temperature_2m": {"label": "Temperatura 2 m", "unit": "°C"},
    "precipitation": {"label": "Precipitació 6 h", "unit": "mm"},
    "wind_10m": {"label": "Vent 10 m", "unit": "km/h"},
    "gust": {"label": "Ratxes", "unit": "km/h"},
    "temperature_850": {"label": "Temperatura 850 hPa", "unit": "°C"},
    "geopotential_500": {"label": "Geopotencial 500 hPa", "unit": "gpm"},
    "cape": {"label": "CAPE (MU)", "unit": "J/kg"},
    "snow": {"label": "Neu 6 h", "unit": "mm e.a."},
}


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalise_lon(lons: np.ndarray) -> np.ndarray:
    return np.where(lons > 180.0, lons - 360.0, lons)


def end_step(gid: int) -> int:
    for key in ("endStep", "forecastTime"):
        try:
            return int(codes_get(gid, key))
        except Exception:
            pass
    raise RuntimeError("GRIB message without forecast step")


def crop_matrix(
    lats: np.ndarray,
    lons: np.ndarray,
    values: np.ndarray,
    cfg: dict,
) -> tuple[list[float], list[float], list[list[float | None]]]:
    mask = (
        (lats >= cfg["south"]) &
        (lats <= cfg["north"]) &
        (lons >= cfg["west"]) &
        (lons <= cfg["east"])
    )
    la = lats[mask]
    lo = lons[mask]
    va = values[mask]

    latitudes = sorted({round(float(v), 6) for v in la}, reverse=True)
    longitudes = sorted({round(float(v), 6) for v in lo})

    lat_idx = {v: i for i, v in enumerate(latitudes)}
    lon_idx = {v: i for i, v in enumerate(longitudes)}
    matrix = [[None for _ in longitudes] for _ in latitudes]

    for lat, lon, value in zip(la, lo, va):
        if not math.isfinite(float(value)):
            continue
        matrix[lat_idx[round(float(lat), 6)]][lon_idx[round(float(lon), 6)]] = float(value)

    factor = int(cfg.get("factor", 1))
    if factor > 1:
        latitudes = latitudes[::factor]
        longitudes = longitudes[::factor]
        matrix = [row[::factor] for row in matrix[::factor]]

    return latitudes, longitudes, matrix


def map_matrix(matrix: list[list[float | None]], fn) -> list[list[float | None]]:
    out = []
    for row in matrix:
        out.append([None if v is None else round(float(fn(float(v))), 2) for v in row])
    return out


def binary_matrix(a, b, fn):
    out = []
    for ra, rb in zip(a, b):
        row = []
        for va, vb in zip(ra, rb):
            if va is None or vb is None:
                row.append(None)
            else:
                row.append(round(float(fn(float(va), float(vb))), 2))
        out.append(row)
    return out


def matrix_minmax(matrix):
    vals = [float(v) for row in matrix for v in row if v is not None and math.isfinite(float(v))]
    if not vals:
        return None, None
    return round(min(vals), 2), round(max(vals), 2)


def read_grib(path: Path):
    with path.open("rb") as f:
        while True:
            gid = codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                short = str(codes_get(gid, "shortName"))
                step = end_step(gid)
                try:
                    level = int(codes_get(gid, "level"))
                except Exception:
                    level = None
                lats = np.asarray(codes_get_array(gid, "latitudes"), dtype=np.float64)
                lons = normalise_lon(np.asarray(codes_get_array(gid, "longitudes"), dtype=np.float64))
                values = np.asarray(codes_get_array(gid, "values"), dtype=np.float64)
                yield short, step, level, lats, lons, values
            finally:
                codes_release(gid)


def new_store():
    return {region: {} for region in REGIONS}


def add_direct(store, step, lats, lons, values, converter=lambda x: x):
    for region, cfg in REGIONS.items():
        latitudes, longitudes, matrix = crop_matrix(lats, lons, values, cfg)
        store[region][step] = {
            "latitudes": latitudes,
            "longitudes": longitudes,
            "values": map_matrix(matrix, converter),
        }


def retrieve(client, target: Path, *, param, step=STEPS, levelist=None, date=None, time=None):
    kwargs = {
        "type": "fc",
        "stream": "oper",
        "param": param,
        "step": step,
        "target": str(target),
    }
    if levelist is not None:
        kwargs["levelist"] = levelist
    if date is not None:
        kwargs["date"] = date
    if time is not None:
        kwargs["time"] = time
    return client.retrieve(**kwargs)


def finalise(variable: str, stores: dict, run: datetime, extra_frame_fields=None):
    meta = VARIABLE_META[variable]
    for region, frames_in in stores.items():
        if not frames_in:
            continue
        steps = sorted(int(s) for s in frames_in)
        latitudes = frames_in[steps[0]]["latitudes"]
        longitudes = frames_in[steps[0]]["longitudes"]
        frames = {}
        all_values = []

        for step in steps:
            item = frames_in[step]
            matrix = item["values"]
            mn, mx = matrix_minmax(matrix)
            for row in matrix:
                all_values.extend(float(v) for v in row if v is not None and math.isfinite(float(v)))
            frame = {
                "valid_time": iso_utc(run + timedelta(hours=step)),
                "min": mn,
                "max": mx,
                "values": matrix,
            }
            if extra_frame_fields:
                frame.update(extra_frame_fields(region, step, item))
            frames[str(step)] = frame

        cfg = REGIONS[region]
        payload = {
            "ok": True,
            "mode": "interactive-grid-v4",
            "source": "ECMWF Open Data · IFS",
            "model": "ECMWF IFS",
            "variable": variable,
            "label": meta["label"],
            "unit": meta["unit"],
            "region": region,
            "run": iso_utc(run),
            "generated_at": iso_utc(datetime.now(timezone.utc)),
            "resolution_deg": round(0.25 * int(cfg.get("factor", 1)), 2),
            "bounds": {k: cfg[k] for k in ("south", "west", "north", "east")},
            "steps": steps,
            "latitudes": latitudes,
            "longitudes": longitudes,
            "frames": frames,
            "overall_min": round(min(all_values), 2) if all_values else None,
            "overall_max": round(max(all_values), 2) if all_values else None,
            "attribution": "ECMWF IFS Open Data · CC BY 4.0",
        }
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / f"{variable}_{region}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{target}: {len(steps)} frames, {len(latitudes)}x{len(longitudes)}")


def process_direct(client, run, variable, param, converter=lambda x: x, levelist=None, accepted=None, steps=STEPS):
    path = TMP / f"{variable}.grib2"
    retrieve(
        client, path, param=param, step=steps, levelist=levelist,
        date=run.strftime("%Y%m%d"), time=run.hour,
    )
    store = new_store()
    accepted = set(accepted or ([param] if isinstance(param, str) else param))
    for short, step, level, lats, lons, values in read_grib(path):
        if short not in accepted:
            continue
        add_direct(store, step, lats, lons, values, converter)
    finalise(variable, store, run)
    path.unlink(missing_ok=True)


def process_accum(client, run, variable, param):
    path = TMP / f"{variable}.grib2"
    retrieve(
        client, path, param=param, step=STEPS,
        date=run.strftime("%Y%m%d"), time=run.hour,
    )
    cumulative = new_store()
    for short, step, level, lats, lons, values in read_grib(path):
        if short != param:
            continue
        for region, cfg in REGIONS.items():
            latitudes, longitudes, matrix = crop_matrix(lats, lons, values, cfg)
            cumulative[region][step] = {
                "latitudes": latitudes,
                "longitudes": longitudes,
                "values": map_matrix(matrix, lambda x: x * 1000.0),  # m -> mm water equivalent
            }

    interval = new_store()
    for region in REGIONS:
        prev = None
        for step in sorted(cumulative[region]):
            item = cumulative[region][step]
            current = item["values"]
            if prev is None:
                inc = map_matrix(current, lambda x: max(0.0, x))
            else:
                inc = binary_matrix(current, prev, lambda a, b: max(0.0, a - b))
            interval[region][step] = {
                "latitudes": item["latitudes"],
                "longitudes": item["longitudes"],
                "values": inc,
            }
            prev = current
    finalise(variable, interval, run)
    path.unlink(missing_ok=True)


def process_wind(client, run):
    path = TMP / "wind_10m.grib2"
    retrieve(
        client, path, param=["10u", "10v"], step=STEPS,
        date=run.strftime("%Y%m%d"), time=run.hour,
    )
    components = {region: {} for region in REGIONS}
    for short, step, level, lats, lons, values in read_grib(path):
        if short not in {"10u", "10v"}:
            continue
        key = "u" if short == "10u" else "v"
        for region, cfg in REGIONS.items():
            latitudes, longitudes, matrix = crop_matrix(lats, lons, values, cfg)
            components[region].setdefault(step, {
                "latitudes": latitudes, "longitudes": longitudes
            })[key] = matrix

    store = new_store()
    for region in REGIONS:
        for step, item in components[region].items():
            if "u" not in item or "v" not in item:
                continue
            speed = binary_matrix(item["u"], item["v"], lambda u, v: math.hypot(u, v) * 3.6)
            store[region][step] = {
                "latitudes": item["latitudes"],
                "longitudes": item["longitudes"],
                "values": speed,
                "u": map_matrix(item["u"], lambda x: x),
                "v": map_matrix(item["v"], lambda x: x),
            }

    def extra(region, step, item):
        return {"u": item["u"], "v": item["v"]}

    finalise("wind_10m", store, run, extra)
    path.unlink(missing_ok=True)


def process_gust(client, run):
    path = TMP / "gust.grib2"
    gust_steps = STEPS[1:]
    retrieve(
        client, path, param="10fg", step=gust_steps,
        date=run.strftime("%Y%m%d"), time=run.hour,
    )
    store = new_store()
    for short, step, level, lats, lons, values in read_grib(path):
        if not short.startswith("10fg"):
            continue
        add_direct(store, step, lats, lons, values, lambda x: x * 3.6)
    finalise("gust", store, run)
    path.unlink(missing_ok=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    client = Client(source="ecmwf", model="ifs", resol="0p25", infer_stream_keyword=True)

    # Resolve one single forecast run and pin all subsequent requests to it.
    probe = TMP / "probe.grib2"
    result = client.retrieve(type="fc", stream="oper", param="2t", step=0, target=str(probe))
    run = result.datetime
    if run.tzinfo is None:
        run = run.replace(tzinfo=timezone.utc)
    probe.unlink(missing_ok=True)
    print("Using ECMWF run", iso_utc(run))

    process_direct(client, run, "temperature_2m", "2t", lambda x: x - 273.15)
    process_accum(client, run, "precipitation", "tp")
    process_wind(client, run)
    process_gust(client, run)
    process_direct(client, run, "temperature_850", "t", lambda x: x - 273.15, levelist=850, accepted=["t"])
    process_direct(client, run, "geopotential_500", "gh", lambda x: x, levelist=500, accepted=["gh"])
    process_direct(client, run, "cape", "mucape", lambda x: x, accepted=["mucape"])
    process_accum(client, run, "snow", "sf")

    manifest = {
        "ok": True,
        "source": "ECMWF Open Data · IFS",
        "run": iso_utc(run),
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "variables": list(VARIABLE_META),
        "regions": list(REGIONS),
        "horizon_hours": 72,
        "step_hours": 6,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
