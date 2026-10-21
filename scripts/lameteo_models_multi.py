#!/usr/bin/env python3
"""Additional model fields from NOAA GFS / DWD ICON-EU.

Publishes only validated, complete grids. Individual missing variables never
replace older valid maps with fabricated values.
"""
from __future__ import annotations
import argparse
import bz2
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
import time

import numpy as np
from lameteo_models_external import (
    S, REGIONS, HOURS, decode_grib, find_gfs_run, find_icon_run,
    get_bytes, gfs_idx_url, icon_url, iso, sample_grid
)

# A curated set of fields reliably available in publicly served GRIB archives.
FIELDS = {
    'temperature_2m': ('Temperatura 2 m', '°C', 'temp'),
    'temperature_850': ('Temperatura 850 hPa', '°C', 'temp'),
    'temperature_500': ('Temperatura 500 hPa', '°C', 'temp'),
    'dewpoint_2m': ('Punt de rosada 2 m', '°C', 'temp'),
    'relative_humidity_2m': ('Humitat relativa 2 m', '%', 'identity'),
    'pressure_msl': ('Pressió a nivell del mar', 'hPa', 'pressure'),
    'precipitation': ('Precipitació per interval', 'mm', 'identity'),
    'wind_10m': ('Vent 10 m', 'km/h', 'vector'),
    'wind_850': ('Vent 850 hPa', 'km/h', 'vector'),
    'jet_300': ('Corrent en jet 300 hPa', 'km/h', 'vector'),
    'gust': ('Ratxes de vent', 'km/h', 'wind'),
    'geopotential_500': ('Geopotencial 500 hPa', 'gpm', 'identity'),
    'cape': ('CAPE', 'J/kg', 'identity'),
    'cin': ('Inhibició convectiva', 'J/kg', 'identity'),
    'cloud_cover': ('Nubositat total', '%', 'identity'),
    'cloud_cover_low': ('Núvols baixos', '%', 'identity'),
    'cloud_cover_mid': ('Núvols mitjans', '%', 'identity'),
    'cloud_cover_high': ('Núvols alts', '%', 'identity'),
    'snow_depth': ('Gruix de neu', 'cm', 'snowdepth'),
    'visibility': ('Visibilitat', 'km', 'visibility')
}

# (GRIB index field, level text); fields are matched with full separators.
GFS_SOURCES = {
    'temperature_2m': [('TMP','2 m above ground')],
    'temperature_850': [('TMP','850 mb')],
    'temperature_500': [('TMP','500 mb')],
    'dewpoint_2m': [('DPT','2 m above ground')],
    'relative_humidity_2m': [('RH','2 m above ground')],
    'pressure_msl': [('PRMSL','mean sea level')],
    'precipitation': [('APCP','surface')],
    'wind_10m': [('UGRD','10 m above ground'),('VGRD','10 m above ground')],
    'wind_850': [('UGRD','850 mb'),('VGRD','850 mb')],
    'jet_300': [('UGRD','300 mb'),('VGRD','300 mb')],
    'gust': [('GUST','surface')],
    'geopotential_500': [('HGT','500 mb')],
    'cape': [('CAPE','surface'),('CAPE','180-0 mb above ground')],
    'cin': [('CIN','surface'),('CIN','180-0 mb above ground')],
    'cloud_cover': [('TCDC','entire atmosphere')],
    'cloud_cover_low': [('TCDC','low cloud layer')],
    'cloud_cover_mid': [('TCDC','middle cloud layer')],
    'cloud_cover_high': [('TCDC','high cloud layer')],
    'snow_depth': [('SNOD','surface')],
    'visibility': [('VIS','surface')],
}
ICON_SOURCES = {
    'temperature_2m': ['t_2m'],
    'dewpoint_2m': ['td_2m'],
    'relative_humidity_2m': ['relhum_2m'],
    'pressure_msl': ['pmsl'],
    'precipitation': ['tot_prec'],
    'wind_10m': ['u_10m','v_10m'],
    'gust': ['vmax_10m'],
    'cape': ['cape_ml'],
    'cin': ['cin_ml'],
    'cloud_cover': ['clct'],
    'cloud_cover_low': ['clcl'],
    'cloud_cover_mid': ['clcm'],
    'cloud_cover_high': ['clch'],
    'snow_depth': ['h_snow'],
    'visibility': ['vis'],
}
STEP_HOURS = [6,12,18,24,36,48]
MAX_RANGE = 12_000_000

def indexed_fields(base):
    lines = get_bytes(base+'.idx',limit=2_000_000).decode('utf-8','replace').splitlines()
    result=[]
    for line in lines:
        parts=line.split(':')
        if len(parts)>=6 and parts[1].isdigit():
            result.append((int(parts[1]), parts[3], parts[4], line))
    return result

def gfs_blob(base, fields, name, level):
    for i,(offset,short,lev,desc) in enumerate(fields):
        if short==name and lev==level:
            if i==len(fields)-1:
                raise ValueError('No next GRIB byte offset')
            end=fields[i+1][0]-1
            blob=get_bytes(base,headers={'Range':f'bytes={offset}-{end}'},limit=MAX_RANGE)
            if len(blob)!=(end-offset+1):
                raise ValueError('NOAA did not honor range request')
            return blob
    raise KeyError(f'{name} at {level} missing')

def icon_blob(run, h, variable):
    # For single-level fields DWD uses the same naming convention as T_2M.
    url=('https://opendata.dwd.de/weather/nwp/icon-eu/grib/'
         f'{run:%H}/{variable}/icon-eu_europe_regular-lat-lon_single-level_'
         f'{run:%Y%m%d%H}_{h:03d}_{variable.upper()}.grib2.bz2')
    return bz2.decompress(get_bytes(url,limit=MAX_RANGE))

def cleaned_grid(blob, region):
    lats,lons,values=decode_grib(blob)
    out_lats,out_lons,vals=sample_grid(lats,lons,values,REGIONS[region])
    # The existing temperature reader subtracts 273.15, so restore generic units here.
    return out_lats,out_lons,vals+273.15

def transform(values, mode):
    if mode=='temp': return np.round(values-273.15,2)
    if mode=='pressure': return np.round(values/100,2)
    if mode=='wind': return np.round(values*3.6,2)
    if mode=='snowdepth': return np.round(values*100,2)
    if mode=='visibility': return np.round(values/1000,2)
    return np.round(values,2)

def construct_payload(model,region,variable,run,frames,lats,lons):
    label,unit,_=FIELDS[variable]
    source=('NOAA / NCEP · GFS 0.25°' if model=='gfs'
            else 'DWD · ICON-EU · CC BY 4.0')
    values=[float(v) for frame in frames.values() for row in frame['values']
            for v in row if v is not None and math.isfinite(v)]
    return {
        'ok':True,'mode':'interactive-grid-v4','source':source,
        'model':model.upper().replace('_','-'),'variable':variable,'label':label,
        'unit':unit,'region':region,'run':iso(run),
        'generated_at':iso(datetime.now(timezone.utc)),
        'resolution_deg':.5,
        'bounds':{'south':lats[-1], 'west':lons[0], 'north':lats[0], 'east':lons[-1]},
        'steps':STEP_HOURS,'latitudes':lats,'longitudes':lons,
        'frames':frames,
        'overall_min':round(min(values),2) if values else None,
        'overall_max':round(max(values),2) if values else None
    }

def frame_of(array,run,h):
    if not np.isfinite(array).any():raise ValueError('No finite values')
    a=np.where(np.isfinite(array),array,np.nan)
    return {'valid_time':iso(run+timedelta(hours=h)),
            'min':round(float(np.nanmin(a)),2),
            'max':round(float(np.nanmax(a)),2),
            'values':[[None if not np.isfinite(v) else float(v) for v in row]
                      for row in a]}

def sources(model,variable):
    return GFS_SOURCES[variable] if model=='gfs' else ICON_SOURCES[variable]

def get_model_run(model):
    return find_gfs_run() if model=='gfs' else find_icon_run()

def fetch_required(model,run,h,variable,cache):
    specs=sources(model,variable)
    arrays={}
    if model=='gfs':
        base=gfs_idx_url(run,h)
        if 'idx' not in cache:
            cache['idx']=indexed_fields(base)
        if variable=='cape' or variable=='cin':
            got=None
            for spec in specs:
                try: got=gfs_blob(base,cache['idx'],*spec);break
                except KeyError: pass
            if got is None: raise KeyError(variable)
            arrays['scalar']=got
        else:
            for i,spec in enumerate(specs):
                arrays[str(i)]=gfs_blob(base,cache['idx'],*spec)
    else:
        for i,spec in enumerate(specs):
            arrays[str(i)]=icon_blob(run,h,spec)
    return arrays

def generate(model,run,variable,out):
    mode=FIELDS[variable][2]
    frame_map={region:{} for region in REGIONS}
    axis_map={}
    prev_tot={}
    for h in STEP_HOURS:
        cache={}
        blobs=fetch_required(model,run,h,variable,cache)
        for region in REGIONS:
            layers=[cleaned_grid(blob,region) for blob in blobs.values()]
            lats,lons,first=layers[0]
            if len(layers)==2:
                # Wind derived from actual U/V components, not an angle approximation.
                values=np.hypot(layers[0][2],layers[1][2])*3.6
            else:
                values=transform(first,mode)
            if variable=='precipitation' and model=='icon_eu':
                # DWD TOT_PREC is cumulative since initialization.
                this_total=np.asarray(values)
                prev=prev_tot.get(region)
                values=np.maximum(0,this_total-prev) if prev is not None else np.maximum(0,this_total)
                prev_tot[region]=this_total
            axis_map[region]=(lats,lons)
            frame_map[region][str(h)]=frame_of(values,run,h)
        print(model,variable,'+',h,'h',flush=True)
    for region in REGIONS:
        lats,lons=axis_map[region]
        payload=construct_payload(model,region,variable,run,frame_map[region],lats,lons)
        path=out/model/'v4'/f'{variable}_{region}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
        tmp.replace(path)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path('data/models'))
    parser.add_argument('--models',nargs='+',choices=['gfs','icon_eu'],default=['gfs','icon_eu'])
    parser.add_argument('--variables',nargs='+',default=None)
    args=parser.parse_args()
    success=[]
    for model in args.models:
        try:
            run=get_model_run(model)
        except Exception as err:
            print('Run unavailable:',model,err,file=sys.stderr)
            continue
        available=GFS_SOURCES if model=='gfs' else ICON_SOURCES
        variables=[v for v in available if args.variables is None or v in args.variables]
        done=[]
        for var in variables:
            try:
                generate(model,run,var,args.out)
                done.append(var)
            except Exception as err:
                print('Variable unavailable:',model,var,type(err).__name__,err,file=sys.stderr,flush=True)
        if done:success.append({'id':model,'run':iso(run),'variables':done,'regions':list(REGIONS)})
    if not success:raise SystemExit('No complete datasets generated — existing files retained')
    manifest={'schema':2,'generated_at':iso(datetime.now(timezone.utc)),'models':success}
    (args.out/'external-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PUBLISHED:',json.dumps(manifest,ensure_ascii=False))
if __name__=='__main__':
    main()
