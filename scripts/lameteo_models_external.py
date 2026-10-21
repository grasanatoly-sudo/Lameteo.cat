#!/usr/bin/env python3
"""Public NOAA GFS and DWD ICON-EU temperature to Lameteo interactive-grid-v4.

Designed for scheduled GitHub Actions. Does NOT change the existing ECMWF source.
The script only publishes complete model+region files after successful decoding.
"""
from __future__ import annotations

import argparse
import bz2
from datetime import datetime, timedelta, timezone
import tempfile
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode

import numpy as np
import requests

USER_AGENT = 'Lameteo.cat model ingestion (public NOAA/DWD meteorological data)'
S = requests.Session()
S.headers.update({'User-Agent': USER_AGENT})

REGIONS = {
    'catalunya': (40.0, -1.0, 43.5, 4.0),
    'peninsula': (35.0, -10.5, 44.5, 5.0),
    'mediterrani': (30.0, -11.0, 47.0, 35.0),
    'europa': (31.0, -22.0, 69.0, 43.0),
}
# Low-footprint demo run: one field, nine forecast times; more can be added safely.
HOURS = [6, 12, 18, 24, 30, 36, 42, 48]
TARGET_STEP = 0.5
MAX_FILE_BYTES = 8_000_000


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    return t.isoformat(timespec='seconds').replace('+00:00', 'Z')


def get_bytes(url: str, *, headers: dict | None = None, limit: int = MAX_FILE_BYTES) -> bytes:
    for attempt in range(3):
        try:
            r = S.get(url, headers=headers, timeout=(12, 60), stream=True)
            r.raise_for_status()
            chunks, count = [], 0
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                count += len(chunk)
                if count > limit:
                    raise ValueError('Download exceeds size guard')
                chunks.append(chunk)
            return b''.join(chunks)
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError('unreachable')


def decode_grib(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import eccodes
    with tempfile.TemporaryFile(mode='w+b') as stream:
        stream.write(data)
        stream.seek(0)
        handle = eccodes.codes_grib_new_from_file(stream)
        if handle is None:
            raise ValueError('No GRIB message found')
        try:
            ni, nj = int(eccodes.codes_get(handle, 'Ni')), int(eccodes.codes_get(handle, 'Nj'))
            v = np.asarray(eccodes.codes_get_array(handle, 'values'), dtype='float64').reshape((nj, ni))
            lat = np.asarray(eccodes.codes_get_array(handle, 'latitudes'), dtype='float64').reshape((nj, ni))
            lon = np.asarray(eccodes.codes_get_array(handle, 'longitudes'), dtype='float64').reshape((nj, ni))
            missing = float(eccodes.codes_get(handle, 'missingValue'))
            v[(~np.isfinite(v)) | (np.abs(v - missing) < 0.001) | (v > 1e10)] = np.nan
        finally:
            eccodes.codes_release(handle)
    lat_axis = lat[:, 0]
    lon_axis = np.where(lon[0, :] > 180, lon[0, :] - 360, lon[0, :])
    # A GRIB regular lat/lon field should have constant rows and columns.
    if np.max(np.abs(lat - lat_axis[:, None])) > 0.02:
        raise ValueError('Unexpected latitude layout for regular lat-lon GRIB')
    if np.max(np.abs(np.where(lon > 180, lon - 360, lon) - lon_axis[None, :])) > 0.02:
        raise ValueError('Unexpected longitude layout for regular lat-lon GRIB')
    rows = np.argsort(lat_axis)[::-1]
    cols = np.argsort(lon_axis)
    return lat_axis[rows], lon_axis[cols], v[rows][:, cols]


def sample_grid(lat: np.ndarray, lon: np.ndarray, values_k: np.ndarray,
                bounds: tuple[float, float, float, float], step: float = TARGET_STEP):
    south, west, north, east = bounds
    output_lat = np.round(np.arange(north, south - 0.001, -step), 4)
    output_lon = np.round(np.arange(west, east + 0.001, step), 4)
    if output_lat.size < 2 or output_lon.size < 2:
        raise ValueError('Invalid geographic region')
    # Bilinear interpolation by nearest bracketing source grid cells.
    src_lat = lat[::-1]
    ascending_data = values_k[::-1, :]
    if output_lat.max() > src_lat.max() or output_lat.min() < src_lat.min():
        raise ValueError('Region exceeds data latitude bounds')
    if output_lon.max() > lon.max() or output_lon.min() < lon.min():
        raise ValueError('Region exceeds data longitude bounds')
    iy = np.clip(np.searchsorted(src_lat, output_lat, side='right') - 1, 0, len(src_lat) - 2)
    ix = np.clip(np.searchsorted(lon, output_lon, side='right') - 1, 0, len(lon) - 2)
    wy = (output_lat - src_lat[iy]) / (src_lat[iy + 1] - src_lat[iy])
    wx = (output_lon - lon[ix]) / (lon[ix + 1] - lon[ix])
    a = ascending_data[np.ix_(iy, ix)]
    b = ascending_data[np.ix_(iy, ix + 1)]
    c = ascending_data[np.ix_(iy + 1, ix)]
    d = ascending_data[np.ix_(iy + 1, ix + 1)]
    result_k = ((1 - wy[:, None]) * ((1 - wx[None, :]) * a + wx[None, :] * b)
                + wy[:, None] * ((1 - wx[None, :]) * c + wx[None, :] * d))
    return output_lat.tolist(), output_lon.tolist(), np.round(result_k - 273.15, 2)


def gfs_idx_url(run: datetime, h: int) -> str:
    date, cycle = run.strftime('%Y%m%d'), run.strftime('%H')
    return f'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{date}/{cycle}/atmos/gfs.t{cycle}z.pgrb2.0p25.f{h:03d}'


def gfs_field(base: str) -> bytes:
    listing = get_bytes(base + '.idx', limit=2_000_000).decode('utf-8', 'replace').splitlines()
    fields = []
    for line in listing:
        parts = line.split(':')
        if len(parts) > 5:
            try:
                fields.append((int(parts[1]), ':'.join(parts[3:])))
            except ValueError:
                pass
    for i, (start, desc) in enumerate(fields):
        if ':TMP:2 m above ground:' in ':' + desc + ':':
            # Byte ranges are inclusive, stopping before the next field.
            if i + 1 == len(fields):
                raise ValueError('TMP field has no following offset')
            end = fields[i + 1][0] - 1
            data = get_bytes(base, headers={'Range': f'bytes={start}-{end}'})
            if len(data) != end - start + 1:
                raise ValueError('HTTP range not honored by data service')
            return data
    raise ValueError('GFS 2m temperature not found in index')


def find_gfs_run():
    now = now_utc()
    cycle = now.replace(minute=0, second=0, microsecond=0)
    cycle = cycle - timedelta(hours=cycle.hour % 6)
    for back in range(0, 31, 6):
        run = cycle - timedelta(hours=back)
        try:
            get_bytes(gfs_idx_url(run, HOURS[-1]) + '.idx', limit=2_000_000)
            return run
        except Exception as exc:
            print('GFS candidate not ready:', iso(run), str(exc)[:130], flush=True)
    raise RuntimeError('No published GFS run with all forecast steps')


def find_icon_run():
    # DWD directory contains the active run. Validate availability of +48 h.
    dates = []
    for cycle in (0, 6, 12, 18):
        directory = f'https://opendata.dwd.de/weather/nwp/icon-eu/grib/{cycle:02d}/t_2m/'
        try:
            page = get_bytes(directory, limit=100_000).decode('utf-8', 'replace')
            matches = re.findall(r'(20\d{8})_048_T_2M\.grib2\.bz2', page, re.I)
            for timestamp in matches:
                run = datetime.strptime(timestamp, '%Y%m%d%H').replace(tzinfo=timezone.utc)
                if abs((now_utc() - run).total_seconds()) < 60 * 60 * 42:
                    dates.append(run)
        except Exception as exc:
            print('ICON index unavailable:', directory, str(exc)[:130], flush=True)
    if not dates:
        raise RuntimeError('No ICON-EU run with +48 h detected')
    return max(dates)


def icon_url(run: datetime, h: int) -> str:
    return ('https://opendata.dwd.de/weather/nwp/icon-eu/grib/'
            f'{run:%H}/t_2m/icon-eu_europe_regular-lat-lon_single-level_'
            f'{run:%Y%m%d%H}_{h:03d}_T_2M.grib2.bz2')


def load_model(model: str):
    run = find_gfs_run() if model == 'gfs' else find_icon_run()
    source = 'NOAA / NCEP · GFS 0.25°' if model == 'gfs' else 'DWD · ICON-EU · CC BY 4.0'
    collected = {r: None for r in REGIONS}
    for h in HOURS:
        if model == 'gfs':
            blob = gfs_field(gfs_idx_url(run, h))
        else:
            blob = bz2.decompress(get_bytes(icon_url(run, h)))
        lat, lon, grid = decode_grib(blob)
        for region, bounds in REGIONS.items():
            lats, lons, values = sample_grid(lat, lon, grid, bounds)
            if collected[region] is None:
                collected[region] = {'ok': True, 'mode': 'interactive-grid-v4',
                    'source': source, 'model': model.upper().replace('_', '-'),
                    'variable': 'temperature_2m', 'label': 'Temperatura 2 m', 'unit': '°C',
                    'region': region, 'run': iso(run), 'generated_at': iso(now_utc()),
                    'resolution_deg': TARGET_STEP, 'bounds': {'south': lats[-1], 'west': lons[0],
                    'north': lats[0], 'east': lons[-1]}, 'steps': HOURS,
                    'latitudes': lats, 'longitudes': lons, 'frames': {}}
            frame = {
                'valid_time': iso(run + timedelta(hours=h)),
                'min': float(np.nanmin(values)), 'max': float(np.nanmax(values)),
                'values': [[None if not np.isfinite(v) else float(v) for v in row] for row in values]
            }
            collected[region]['frames'][str(h)] = frame
        print(model, iso(run), 'forecast', h, 'ready', flush=True)
    return collected


def write_model(out: Path, model: str, data: dict):
    for region, payload in data.items():
        path = out / model / 'v4' / f'temperature_2m_{region}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement after all forecast hours pass, no partial run.
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
        temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path('data/models'))
    parser.add_argument('--models', nargs='+', choices=('gfs', 'icon_eu'), default=['gfs', 'icon_eu'])
    args = parser.parse_args()
    successes = []
    for model in args.models:
        try:
            payload = load_model(model)
            write_model(args.out, model, payload)
            successes.append({'id': model, 'run': payload['catalunya']['run'],
                              'variables': ['temperature_2m'], 'regions': list(REGIONS)})
        except Exception as exc:
            print(f'ERROR {model}: {exc}', file=sys.stderr, flush=True)
    if not successes:
        raise SystemExit('No complete model datasets generated; existing files unchanged')
    manifest = {'schema': 1, 'generated_at': iso(now_utc()), 'models': successes}
    (args.out / 'external-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # A partial success is visible in logs but never fabricated in manifest.
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
