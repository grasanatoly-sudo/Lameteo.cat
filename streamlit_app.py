import io
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import imageio.v2 as imageio
import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

st.set_page_config(page_title="Lameteo.cat · Prova", page_icon="🌦️", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; max-width: 100%;}
.stImage img {border-radius: 24px; border: 1px solid rgba(80,190,255,.30); background:#07111f;}
.small {color:#9fb4cc; font-size:14px;}
.timebox {padding:14px 18px;border:1px solid rgba(80,190,255,.25);border-radius:16px;background:rgba(40,120,200,.12);margin:10px 0 18px 0;}
.stDownloadButton button {border-radius:999px; font-weight:800;}
[data-baseweb="tab"] {font-weight:800;}
</style>
""", unsafe_allow_html=True)

st.title("🌦️ Lameteo.cat · Visor meteorològic de prova")
st.caption("Radar, satèl·lit i models. Amb fronteres, capes manuals, composició, llegenda ECMWF i exportació MP4.")

# Format 16:9 perquè el mapa es vegi molt més professional i no quedi tan panoràmic.
DOMAINS = {
    "Catalunya": {"bbox": "-1.2,39.7,4.2,43.2", "center": "41.65,1.8,7", "size": (1920, 1080)},
    "Península Ibèrica": {"bbox": "-10.8,35.0,5.0,44.6", "center": "40.2,-3.5,5", "size": (1920, 1080)},
    "Europa": {"bbox": "-13,34,32,72", "center": "48,8,4", "size": (1920, 1080)},
    "Món": {"bbox": "-80,-60,80,80", "center": "20,0,2", "size": (1920, 1080)},
}

# Capes fixes típiques. Si alguna no existeix al compte, es pot buscar a "Capes detectades".
SAT_LAYERS = {
    "Natural color / RGB": "msg_fes:rgb_natural",
    "Natural color millorat": "msg_fes:rgb_natural_enhanced",
    "Airmass RGB": "msg_fes:rgb_airmass",
    "Dust RGB / pols": "msg_fes:rgb_dust",
    "Day microphysics": "msg_fes:rgb_day_microphysics",
    "Night microphysics": "msg_fes:rgb_night_microphysics",
    "Severe storms RGB": "msg_fes:rgb_severe_storms",
    "Cloud phase RGB": "msg_fes:rgb_cloud_phase",
    "Cloud type": "msg_fes:cloud_type",
    "Cloud top temperature": "msg_fes:ctth_temperature",
    "Cloud top height": "msg_fes:ctth_height",
    "Infraroig 10.8": "msg_fes:ir108",
    "Vapor d’aigua 6.2": "msg_fes:wv062",
    "Vapor d’aigua 7.3": "msg_fes:wv073",
    "Visible 0.6": "msg_fes:vis006",
    "Visible 0.8": "msg_fes:vis008",
    "NIR 1.6": "msg_fes:nir016",
    "IR 3.9": "msg_fes:ir039",
    "IR 8.7": "msg_fes:ir087",
    "IR 9.7": "msg_fes:ir097",
    "IR 12.0": "msg_fes:ir120",
    "IR 13.4": "msg_fes:ir134",
    "Capa manual": "manual",
}

ECMWF_LAYERS = {
    "Pressió nivell del mar": "msl_public",
    "Temperatura 850 hPa": "t850_public",
    "Geopotencial 500 hPa": "z500_public",
    "Vent 850 hPa": "ws850_public",
    "Vent 10 m": "10u_public",
    "Temperatura 2 m": "2t_public",
    "Precipitació total": "tp_public",
    "Neu": "sf_public",
    "CAPE": "cape_public",
    "Humitat relativa 700 hPa": "r700_public",
    "Ensemble Z500 mitjana": "z500_mean_public",
    "Ensemble T850 mitjana": "t850_mean_public",
    "Ensemble MSLP mitjana": "msl_mean_public",
    "Ensemble Z500 spread": "z500_spread_public",
    "Ensemble T850 spread": "t850_spread_public",
    "Ensemble MSLP spread": "msl_spread_public",
}

LAYER_TITLES = {
    "msl_public": "Pressió a nivell del mar",
    "t850_public": "Temperatura a 850 hPa",
    "z500_public": "Geopotencial a 500 hPa",
    "ws850_public": "Vent a 850 hPa",
    "10u_public": "Vent a 10 metres",
    "2t_public": "Temperatura a 2 metres",
    "tp_public": "Precipitació total",
    "sf_public": "Neu acumulada",
    "cape_public": "CAPE",
    "r700_public": "Humitat relativa a 700 hPa",
    "z500_mean_public": "Ensemble · Z500 mitjana",
    "t850_mean_public": "Ensemble · T850 mitjana",
    "msl_mean_public": "Ensemble · MSLP mitjana",
    "z500_spread_public": "Ensemble · Z500 spread",
    "t850_spread_public": "Ensemble · T850 spread",
    "msl_spread_public": "Ensemble · MSLP spread",
}

LEGEND_PRESETS = {
    "t850_public": {"unit": "°C", "values": [-52, -44, -36, -28, -20, -12, -4, 0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48],
                    "colors": ["#bd44d6", "#812cb2", "#2d1838", "#3100b8", "#004ee8", "#00c8ff", "#1df7ff", "#25e857", "#b6ff00", "#ffff78", "#fff000", "#ffb000", "#ff7b00", "#ff2300", "#e60000", "#9b0024", "#e900a8", "#ff7cff", "#ffc7ff"]},
    "2t_public": {"unit": "°C", "values": [-20, -16, -12, -8, -4, 0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48],
                  "colors": ["#4b0082", "#0038ff", "#00a8ff", "#00fff0", "#3cff7a", "#b8ff00", "#ffff66", "#ffd400", "#ff9a00", "#ff5a00", "#ff0000", "#c40000", "#8b0000", "#b00080", "#ff4edb", "#ffc2ff", "#ffffff"]},
    "msl_public": {"unit": "hPa", "values": [960, 970, 980, 990, 1000, 1010, 1020, 1030, 1040, 1050],
                   "colors": ["#5b2b83", "#2148a8", "#208ad6", "#24c6d8", "#7ce56a", "#f0e95a", "#ffb13b", "#f06a2e", "#d92b2b"]},
    "z500_public": {"unit": "dam", "values": [500, 516, 532, 548, 564, 580, 596],
                    "colors": ["#2b4c7e", "#397dbc", "#43b7c2", "#84d65a", "#f0df4c", "#f28d35", "#c9412f"]},
    "ws850_public": {"unit": "km/h", "values": [0, 20, 40, 60, 80, 100, 120, 140],
                     "colors": ["#e9f7ff", "#8fd3ff", "#23a3ff", "#22d45a", "#ffd21f", "#ff7a1a", "#e60000", "#9d00ff"]},
    "tp_public": {"unit": "mm", "values": [0, 1, 2, 5, 10, 20, 50, 100],
                  "colors": ["#f7f7f7", "#b6e6ff", "#55bfff", "#1380ff", "#00b050", "#ffe600", "#ff8c00", "#d00000"]},
    "cape_public": {"unit": "J/kg", "values": [0, 100, 250, 500, 1000, 1500, 2000, 3000],
                    "colors": ["#eeeeee", "#bfffbf", "#78e65a", "#d6f000", "#ffd000", "#ff8900", "#e00000", "#8b0000"]},
}


def clean_secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "")).strip().replace("\t", "").replace("\n", "")
    except Exception:
        return ""


def has_secret(name: str) -> bool:
    return bool(clean_secret(name))


@st.cache_data(ttl=3300, show_spinner=False)
def get_eumetsat_token():
    key = clean_secret("EUMETSAT_KEY")
    secret = clean_secret("EUMETSAT_SECRET")
    if not key or not secret:
        return None, "Falten EUMETSAT_KEY i/o EUMETSAT_SECRET a Secrets."
    r = requests.post("https://api.eumetsat.int/token", auth=(key, secret), data={"grant_type": "client_credentials"}, timeout=25)
    if not r.ok:
        return None, f"EUMETSAT token error {r.status_code}: {r.text[:250]}"
    return r.json().get("access_token"), None


def wms_getmap(url, layer, bbox, width=1500, height=950, token=None, ecmwf_key=None, transparent="true", extra_params=None):
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "SRS": "EPSG:4326",
        "BBOX": bbox,
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": "image/png",
        "TRANSPARENT": transparent,
    }
    if extra_params:
        params.update({k: v for k, v in extra_params.items() if v not in (None, "")})
    if ecmwf_key:
        params["token"] = ecmwf_key
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(url, params=params, headers=headers, timeout=60)


def wms_capabilities(url, token=None, ecmwf_key=None):
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetCapabilities"}
    if ecmwf_key:
        params["token"] = ecmwf_key
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(url, params=params, headers=headers, timeout=45)


def wms_legend(layer, ecmwf_key=None):
    # Intent real: ECMWF WMS GetLegendGraphic. Si no torna imatge clara, fem llegenda local amb valors.
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetLegendGraphic", "LAYER": layer, "FORMAT": "image/png"}
    if ecmwf_key:
        params["token"] = ecmwf_key
    try:
        r = requests.get("https://eccharts.ecmwf.int/wms/", params=params, timeout=30)
        if r.ok and "image" in r.headers.get("content-type", "") and len(r.content) > 500:
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            if img.width > 20 and img.height > 10:
                return img
    except Exception:
        pass
    return None


def extract_layer_names(xml_text, max_layers=700):
    names = []
    try:
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            if elem.tag.endswith("Name") and elem.text:
                txt = elem.text.strip()
                if txt and txt not in names and (":" in txt or txt.endswith("_public")):
                    names.append(txt)
            if len(names) >= max_layers:
                break
    except Exception:
        return []
    return names


@st.cache_data(ttl=86400, show_spinner=False)
def load_borders_geojson():
    url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def lonlat_to_px(lon, lat, bbox, width, height):
    minlon, minlat, maxlon, maxlat = [float(x) for x in bbox.split(",")]
    x = (lon - minlon) / (maxlon - minlon) * width
    y = (maxlat - lat) / (maxlat - minlat) * height
    return x, y


def draw_geometry(draw, geom, bbox, width, height, color, line_width):
    if geom.get("type") == "Polygon":
        polygons = [geom.get("coordinates", [])]
    elif geom.get("type") == "MultiPolygon":
        polygons = geom.get("coordinates", [])
    else:
        return
    for poly in polygons:
        for ring in poly:
            pts = []
            for lon, lat, *_ in ring:
                x, y = lonlat_to_px(lon, lat, bbox, width, height)
                if -150 <= x <= width + 150 and -150 <= y <= height + 150:
                    pts.append((x, y))
            if len(pts) > 1:
                draw.line(pts, fill=color, width=line_width, joint="curve")


def add_borders(img, bbox, color=(255, 255, 255, 155), line_width=2):
    try:
        data = load_borders_geojson()
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for feat in data.get("features", []):
            draw_geometry(draw, feat.get("geometry", {}), bbox, img.width, img.height, color, line_width)
        return Image.alpha_composite(img.convert("RGBA"), overlay)
    except Exception:
        return img.convert("RGBA")


def dark_background(width, height):
    return Image.new("RGBA", (width, height), (6, 17, 32, 255))


def image_from_response(r):
    return Image.open(io.BytesIO(r.content)).convert("RGBA")


def normalize_layer(layer_img, size):
    layer_img = layer_img.convert("RGBA")
    if layer_img.size != size:
        layer_img = layer_img.resize(size, Image.Resampling.LANCZOS)
    return layer_img


def compose_layers(base, layers, opacities):
    canvas = base.convert("RGBA")
    for layer_img, opacity in zip(layers, opacities):
        layer_img = normalize_layer(layer_img, canvas.size)
        if opacity < 1:
            alpha = layer_img.getchannel("A")
            alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
            layer_img.putalpha(alpha)
        canvas = Image.alpha_composite(canvas, layer_img)
    return canvas


def get_font(size=34, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def readable_title(layers):
    if len(layers) == 1:
        return LAYER_TITLES.get(layers[0], layers[0])
    first = LAYER_TITLES.get(layers[0], layers[0])
    return f"{first} + {len(layers) - 1} capa/es"


def make_local_legend(layer, width=620, height=170):
    preset = LEGEND_PRESETS.get(layer)
    if not preset:
        return None
    colors = [tuple(int(c.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) for c in preset["colors"]]
    values = preset["values"]
    unit = preset["unit"]
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    f_title = get_font(26)
    f_val = get_font(18, False)
    draw.text((0, 0), f"Escala · {unit}", font=f_title, fill=(255, 255, 255, 255))
    gx, gy, gw, gh = 18, 52, width - 36, 42
    for x in range(gw):
        t = x / max(gw - 1, 1)
        idx = min(int(t * (len(colors) - 1)), len(colors) - 2)
        local = t * (len(colors) - 1) - idx
        c0, c1 = colors[idx], colors[idx + 1]
        col = tuple(int(c0[j] * (1 - local) + c1[j] * local) for j in range(3))
        draw.line((gx + x, gy, gx + x, gy + gh), fill=col + (255,))
    draw.rectangle((gx, gy, gx + gw, gy + gh), outline=(255, 255, 255, 210), width=2)
    # valors cada pocs ticks
    tick_count = min(len(values), 10)
    if tick_count >= 2:
        for i in range(tick_count):
            pos = int(i * (len(values) - 1) / (tick_count - 1))
            x = gx + int(pos / max(len(values) - 1, 1) * gw)
            draw.line((x, gy + gh, x, gy + gh + 8), fill=(255, 255, 255, 220), width=2)
            txt = str(values[pos])
            draw.text((x - 18, gy + gh + 12), txt, font=f_val, fill=(235, 235, 235, 245))
    return img


def add_map_badges(img, title, valid_text, run_text, layers_text, legend_img=None, legend_layer=None):
    canvas = img.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    pad = 34
    font_title = get_font(58)
    font_med = get_font(31)
    font_small = get_font(24, bold=False)

    # Caixa de títol més professional, però no tapa mig mapa.
    box_w = min(canvas.width - 2 * pad, 1180)
    box_h = 205
    x0, y0 = pad, pad
    draw.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=28, fill=(4, 13, 28, 226), outline=(100, 210, 255, 190), width=3)
    draw.text((x0 + 34, y0 + 22), title, font=font_title, fill=(255, 255, 255, 255))
    draw.text((x0 + 34, y0 + 98), f"Vàlid: {valid_text}", font=font_med, fill=(185, 235, 255, 255))
    draw.text((x0 + 34, y0 + 145), f"Run: {run_text} · Capes: {layers_text[:95]}", font=font_small, fill=(235, 242, 248, 245))

    # Llegenda real si existeix; si no, escala local amb valors segons producte.
    if legend_img is None and legend_layer:
        legend_img = make_local_legend(legend_layer)
    if legend_img:
        leg = legend_img.convert("RGBA")
        max_w = min(720, canvas.width // 2)
        scale = min(max_w / leg.width, 260 / leg.height, 3.0)
        leg = leg.resize((max(1, int(leg.width * scale)), max(1, int(leg.height * scale))), Image.Resampling.LANCZOS)
        leg_pad = 22
        lx = canvas.width - leg.width - 2 * leg_pad - pad
        ly = canvas.height - leg.height - 2 * leg_pad - pad
        draw.rounded_rectangle((lx, ly, lx + leg.width + 2 * leg_pad, ly + leg.height + 2 * leg_pad), radius=24, fill=(4, 13, 28, 226), outline=(255, 255, 255, 150), width=2)
        draw.text((lx + leg_pad, ly + 10), "Llegenda", font=get_font(26), fill=(255, 255, 255, 245))
        overlay.alpha_composite(leg, (lx + leg_pad, ly + leg_pad + 30))
    return Image.alpha_composite(canvas, overlay)


def image_to_png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def show_pil_image(img, caption, key_prefix):
    png = image_to_png_bytes(img)
    st.image(png, use_container_width=True, caption=caption)
    st.download_button("⬇️ Descarregar PNG en alta qualitat", png, file_name=f"lameteo_{key_prefix}.png", mime="image/png", key=f"download_png_{key_prefix}")


def show_response_error(r):
    st.error(f"La capa no ha carregat. HTTP {r.status_code}")
    st.code((r.text or "").strip()[:1200])


def rounded_model_run():
    now = datetime.now(timezone.utc)
    hour = (now.hour // 6) * 6
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def model_time_label(dt):
    dies = ["dilluns", "dimarts", "dimecres", "dijous", "divendres", "dissabte", "diumenge"]
    return f"{dies[dt.weekday()]} {dt.strftime('%d/%m %H:%M')} UTC"


@st.cache_data(ttl=1800, show_spinner=False)
def get_eumetsat_layers():
    token, err = get_eumetsat_token()
    if err:
        return []
    r = wms_capabilities("https://view.eumetsat.int/geoserver/ows", token=token)
    if not r.ok:
        return []
    return extract_layer_names(r.text, max_layers=700)


@st.cache_data(ttl=1800, show_spinner=False)
def get_ecmwf_layers():
    key = clean_secret("ECMWF_API_KEY")
    r = wms_capabilities("https://eccharts.ecmwf.int/wms/", ecmwf_key=key)
    if not r.ok:
        return []
    return extract_layer_names(r.text, max_layers=700)


def render_ecmwf_frame(layer_names, model_domain, forecast_hour, opacity, show_borders=True, show_overlay=True):
    model_run = rounded_model_run()
    valid_time = model_run + timedelta(hours=forecast_hour)
    time_iso = valid_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    width, height = DOMAINS[model_domain]["size"]
    ecmwf_key = clean_secret("ECMWF_API_KEY")
    base = dark_background(width, height)
    loaded = []
    captions = []
    extra = {"TIME": time_iso}
    for layer in layer_names:
        r = wms_getmap("https://eccharts.ecmwf.int/wms/", layer, DOMAINS[model_domain]["bbox"], width, height, ecmwf_key=ecmwf_key, transparent="true", extra_params=extra)
        if r.ok and "image" in r.headers.get("content-type", ""):
            loaded.append(image_from_response(r))
            captions.append(layer)
        else:
            # Fallback sense TIME, per capes que no accepten aquest paràmetre.
            r2 = wms_getmap("https://eccharts.ecmwf.int/wms/", layer, DOMAINS[model_domain]["bbox"], width, height, ecmwf_key=ecmwf_key, transparent="true")
            if r2.ok and "image" in r2.headers.get("content-type", ""):
                loaded.append(image_from_response(r2))
                captions.append(layer)
    if not loaded:
        return None, [], valid_time, model_run, time_iso
    final = compose_layers(base, loaded, [opacity] * len(loaded))
    if show_borders:
        final = add_borders(final, DOMAINS[model_domain]["bbox"], color=(255, 255, 255, 185), line_width=2)
    if show_overlay:
        legend = wms_legend(captions[0], ecmwf_key=ecmwf_key)
        final = add_map_badges(final, readable_title(captions), model_time_label(valid_time), model_run.strftime('%d/%m %H UTC'), " + ".join(captions), legend_img=legend, legend_layer=captions[0])
    return final, captions, valid_time, model_run, time_iso


def make_mp4(frames, fps=2):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()
    rgb_frames = [frame.convert("RGB") for frame in frames]
    imageio.mimsave(tmp.name, rgb_frames, fps=fps, codec="libx264", quality=9, macro_block_size=16)
    with open(tmp.name, "rb") as f:
        data = f.read()
    os.unlink(tmp.name)
    return data


tab_radar, tab_sat, tab_ecmwf, tab_api = st.tabs(["🌧️ Radar", "🛰️ Satèl·lit EUMETSAT", "🌍 Model europeu ECMWF", "🔐 Estat APIs"])

with tab_radar:
    st.subheader("🌧️ Radar de pluja en directe")
    domain = st.selectbox("Zona del radar", list(DOMAINS.keys()), index=0, key="radar_domain")
    loc = DOMAINS[domain]["center"]
    components.html(f'''
    <iframe
    src="https://www.rainviewer.com/map.html?loc={loc}&oFa=0&oC=1&oU=0&oCS=1&oF=0&oAP=1&c=1&o=83&lm=1&layer=radar&sm=1&sn=1"
    style="width:100%;height:790px;border:0;border-radius:22px;overflow:hidden;">
    </iframe>
    ''', height=820)

with tab_sat:
    st.subheader("🛰️ Satèl·lit EUMETSAT")
    st.markdown("<div class='timebox'>🕒 Satèl·lit: última imatge disponible del servei EUMETSAT WMS.</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.1, 1.2, 1])
    with c1:
        sat_domain = st.selectbox("Mapa", list(DOMAINS.keys()), index=1, key="sat_domain")
    with c2:
        sat_label = st.selectbox("Variable satèl·lit", list(SAT_LAYERS.keys()), key="sat_layer")
    with c3:
        custom_sat = st.text_input("Capa manual", value="", placeholder="ex: msg_fes:rgb_natural", key="sat_manual")

    available_sat = get_eumetsat_layers()
    selected_from_cap = st.selectbox("Capes detectades pel compte EUMETSAT", ["-- no usar --"] + available_sat, index=0, key="sat_capabilities")
    show_borders_sat = st.checkbox("Mostrar fronteres i línies de costa", value=True, key="sat_borders")

    layer = selected_from_cap if selected_from_cap != "-- no usar --" else (custom_sat.strip() or SAT_LAYERS[sat_label])
    if layer == "manual":
        st.warning("Escriu el nom exacte d’una capa EUMETSAT a 'Capa manual'.")
    else:
        width, height = DOMAINS[sat_domain]["size"]
        token, err = get_eumetsat_token()
        if err:
            st.error(err)
        else:
            with st.spinner("Carregant imatge EUMETSAT..."):
                r = wms_getmap("https://view.eumetsat.int/geoserver/ows", layer, DOMAINS[sat_domain]["bbox"], width, height, token=token, transparent="false")
            if r.ok and "image" in r.headers.get("content-type", ""):
                img = image_from_response(r)
                if show_borders_sat:
                    img = add_borders(img, DOMAINS[sat_domain]["bbox"], color=(255, 255, 255, 175), line_width=2)
                show_pil_image(img, f"EUMETSAT · {layer} · {sat_domain} · última imatge disponible", key_prefix=f"sat_{sat_domain}_{layer}".replace(":", "_").replace(" ", "_"))
            else:
                show_response_error(r)

with tab_ecmwf:
    st.subheader("🌍 Model europeu ECMWF")
    model_run = rounded_model_run()
    forecast_hour = st.slider("Línia temporal del model · hora de previsió", 0, 120, 0, 3, key="ecmwf_time")
    valid_time = model_run + timedelta(hours=forecast_hour)
    time_iso = valid_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    st.markdown(
        f"<div class='timebox'>🕒 Run aproximat ECMWF: <b>{model_run.strftime('%d/%m %H UTC')}</b> · "
        f"Previsió: <b>+{forecast_hour} h</b> · Vàlid per: <b>{model_time_label(valid_time)}</b></div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1, 2])
    with c1:
        model_domain = st.selectbox("Mapa", list(DOMAINS.keys()), index=2, key="ecmwf_domain")
    with c2:
        selected_labels = st.multiselect("Capes ECMWF superposades", list(ECMWF_LAYERS.keys()), default=["Temperatura 850 hPa"], key="ecmwf_layers")

    available_model = get_ecmwf_layers()
    selected_caps = st.multiselect("Capes detectades pel compte ECMWF", available_model, default=[], key="ecmwf_capabilities")
    custom_model = st.text_input("Capes manuals ECMWF separades per comes", value="", placeholder="ex: msl_public,t850_public,z500_public", key="ecmwf_manual")
    opacity = st.slider("Opacitat de les capes", 0.15, 1.0, 0.9, 0.05, key="ecmwf_opacity")
    show_borders_model = st.checkbox("Mostrar mapa base amb fronteres", value=True, key="model_borders")
    show_overlay_text = st.checkbox("Mostrar títol, data i llegenda dins del mapa", value=True, key="model_overlay")

    layer_names = [ECMWF_LAYERS[x] for x in selected_labels]
    layer_names += selected_caps
    if custom_model.strip():
        layer_names += [x.strip() for x in custom_model.split(",") if x.strip()]
    layer_names = list(dict.fromkeys(layer_names))

    ecmwf_key = clean_secret("ECMWF_API_KEY")
    if not ecmwf_key:
        st.error("Falta ECMWF_API_KEY a Secrets.")
    elif not layer_names:
        st.warning("Tria com a mínim una capa ECMWF.")
    else:
        with st.spinner("Carregant mapa ECMWF en alta resolució..."):
            final, captions, valid_time, model_run, time_iso = render_ecmwf_frame(layer_names, model_domain, forecast_hour, opacity, show_borders_model, show_overlay_text)
        if final:
            cap = f"ECMWF · {' + '.join(captions)} · {model_domain} · Vàlid: {model_time_label(valid_time)} · TIME={time_iso}"
            key_base = f"ecmwf_{model_domain}_{forecast_hour}_{'_'.join(captions)}".replace(":", "_").replace(" ", "_").replace("/", "_")
            show_pil_image(final, cap, key_prefix=key_base)

            st.divider()
            st.subheader("🎬 Exportar vídeo MP4")
            v1, v2, v3 = st.columns(3)
            with v1:
                start_h = st.number_input("Inici", min_value=0, max_value=120, value=0, step=3, key="video_start")
            with v2:
                end_h = st.number_input("Final", min_value=0, max_value=120, value=48, step=3, key="video_end")
            with v3:
                step_h = st.selectbox("Salt entre mapes", [3, 6, 12], index=1, key="video_step")
            fps = st.slider("Velocitat del vídeo", 1, 6, 2, key="video_fps")
            if st.button("🎥 Generar MP4 dels mapes", key="generate_mp4"):
                if end_h < start_h:
                    st.error("El final ha de ser més gran que l'inici.")
                else:
                    hours = list(range(int(start_h), int(end_h) + 1, int(step_h)))
                    frames = []
                    progress = st.progress(0)
                    for i, h in enumerate(hours):
                        img, _, _, _, _ = render_ecmwf_frame(layer_names, model_domain, h, opacity, show_borders_model, True)
                        if img:
                            frames.append(img)
                        progress.progress((i + 1) / len(hours))
                    if len(frames) >= 2:
                        mp4 = make_mp4(frames, fps=fps)
                        st.download_button("⬇️ Descarregar vídeo MP4", mp4, file_name="lameteo_ecmwf_animacio.mp4", mime="video/mp4", key="download_mp4_final")
                        st.success("Vídeo creat correctament.")
                    else:
                        st.error("No hi ha prou fotogrames per crear el vídeo.")
        else:
            st.error("No s’ha pogut carregar cap capa ECMWF.")

with tab_api:
    st.subheader("🔐 Estat de claus i capes")
    st.write(f"EUMETSAT_KEY: {'✅ configurada' if has_secret('EUMETSAT_KEY') else '❌ falta'}")
    st.write(f"EUMETSAT_SECRET: {'✅ configurada' if has_secret('EUMETSAT_SECRET') else '❌ falta'}")
    st.write(f"ECMWF_API_KEY: {'✅ configurada' if has_secret('ECMWF_API_KEY') else '❌ falta'}")
    st.divider()
    if st.button("Provar GetCapabilities EUMETSAT", key="cap_sat_btn"):
        token, err = get_eumetsat_token()
        if err:
            st.error(err)
        else:
            r = wms_capabilities("https://view.eumetsat.int/geoserver/ows", token=token)
            st.write("HTTP", r.status_code)
            st.code(r.text[:3000])
    if st.button("Provar GetCapabilities ECMWF", key="cap_ecmwf_btn"):
        key = clean_secret("ECMWF_API_KEY")
        r = wms_capabilities("https://eccharts.ecmwf.int/wms/", ecmwf_key=key)
        st.write("HTTP", r.status_code)
        st.code(r.text[:3000])
    st.info("Actualitzat: més capes de satèl·lit, més variables ECMWF, llegendes més grans amb valors i exportació PNG/MP4.")
