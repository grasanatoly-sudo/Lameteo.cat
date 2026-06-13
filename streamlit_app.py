import io
import xml.etree.ElementTree as ET

import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageEnhance

st.set_page_config(page_title="Lameteo.cat · Prova", page_icon="🌦️", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; max-width: 100%;}
.stImage img {border-radius: 22px; border: 1px solid rgba(80,190,255,.28); background:#07111f;}
.small {color:#9fb4cc; font-size:14px;}
.ok {color:#66ffbf; font-weight:800;}
.warn {color:#ffd166; font-weight:800;}
</style>
""", unsafe_allow_html=True)

st.title("🌦️ Lameteo.cat · Visor meteorològic de prova")
st.caption("Radar, satèl·lit i models. Amb fronteres, capes manuals i composició de diverses capes.")

DOMAINS = {
    "Catalunya": {"bbox": "-1.2,39.7,4.2,43.2", "center": "41.65,1.8,7", "size": (1500, 900)},
    "Península Ibèrica": {"bbox": "-10.8,35.0,5.0,44.6", "center": "40.2,-3.5,5", "size": (1500, 900)},
    "Europa": {"bbox": "-13,34,32,72", "center": "48,8,4", "size": (1500, 1150)},
    "Món": {"bbox": "-80,-60,80,80", "center": "20,0,2", "size": (1500, 900)},
}

SAT_LAYERS = {
    "Natural color / RGB": "msg_fes:rgb_natural",
    "Infraroig 10.8": "msg_fes:ir108",
    "Vapor d’aigua 6.2": "msg_fes:wv062",
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
    "Ensemble Z500 mitjana": "z500_mean_public",
    "Ensemble T850 mitjana": "t850_mean_public",
    "Ensemble MSLP mitjana": "msl_mean_public",
    "Ensemble Z500 spread": "z500_spread_public",
    "Ensemble T850 spread": "t850_spread_public",
    "Ensemble MSLP spread": "msl_spread_public",
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
    r = requests.post(
        "https://api.eumetsat.int/token",
        auth=(key, secret),
        data={"grant_type": "client_credentials"},
        timeout=25,
    )
    if not r.ok:
        return None, f"EUMETSAT token error {r.status_code}: {r.text[:250]}"
    return r.json().get("access_token"), None


def wms_getmap(url, layer, bbox, width=1500, height=950, token=None, ecmwf_key=None, transparent="true"):
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
    if ecmwf_key:
        params["token"] = ecmwf_key
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(url, params=params, headers=headers, timeout=45)


def wms_capabilities(url, token=None, ecmwf_key=None):
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetCapabilities"}
    if ecmwf_key:
        params["token"] = ecmwf_key
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(url, params=params, headers=headers, timeout=45)


def extract_layer_names(xml_text, max_layers=500):
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
                if -100 <= x <= width + 100 and -100 <= y <= height + 100:
                    pts.append((x, y))
            if len(pts) > 1:
                draw.line(pts, fill=color, width=line_width, joint="curve")


def add_borders(img, bbox, color=(255, 255, 255, 145), line_width=2):
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


def show_pil_image(img, caption):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    st.image(buf.getvalue(), use_container_width=True, caption=caption)


def show_response_error(r):
    st.error(f"La capa no ha carregat. HTTP {r.status_code}")
    st.code((r.text or "").strip()[:1200])


@st.cache_data(ttl=1800, show_spinner=False)
def get_eumetsat_layers():
    token, err = get_eumetsat_token()
    if err:
        return []
    r = wms_capabilities("https://view.eumetsat.int/geoserver/ows", token=token)
    if not r.ok:
        return []
    return extract_layer_names(r.text, max_layers=500)


@st.cache_data(ttl=1800, show_spinner=False)
def get_ecmwf_layers():
    key = clean_secret("ECMWF_API_KEY")
    r = wms_capabilities("https://eccharts.ecmwf.int/wms/", ecmwf_key=key)
    if not r.ok:
        return []
    return extract_layer_names(r.text, max_layers=500)


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
    c1, c2, c3 = st.columns([1.1, 1.2, 1])
    with c1:
        sat_domain = st.selectbox("Mapa", list(DOMAINS.keys()), index=2, key="sat_domain")
    with c2:
        sat_label = st.selectbox("Variable satèl·lit", list(SAT_LAYERS.keys()), key="sat_layer")
    with c3:
        custom_sat = st.text_input("Capa manual", value="", placeholder="ex: msg_fes:rgb_natural")

    available_sat = get_eumetsat_layers()
    selected_from_cap = st.selectbox("Capes detectades pel compte EUMETSAT", ["-- no usar --"] + available_sat, index=0)
    show_borders_sat = st.checkbox("Mostrar fronteres i línies de costa", value=True, key="sat_borders")

    if selected_from_cap != "-- no usar --":
        layer = selected_from_cap
    else:
        layer = custom_sat.strip() or SAT_LAYERS[sat_label]

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
                    img = add_borders(img, DOMAINS[sat_domain]["bbox"], color=(255, 255, 255, 155), line_width=2)
                show_pil_image(img, f"EUMETSAT · {layer} · {sat_domain}")
            else:
                show_response_error(r)

with tab_ecmwf:
    st.subheader("🌍 Model europeu ECMWF")
    c1, c2 = st.columns([1, 2])
    with c1:
        model_domain = st.selectbox("Mapa", list(DOMAINS.keys()), index=1, key="ecmwf_domain")
    with c2:
        selected_labels = st.multiselect("Capes ECMWF superposades", list(ECMWF_LAYERS.keys()), default=["Pressió nivell del mar"])

    available_model = get_ecmwf_layers()
    selected_caps = st.multiselect("Capes detectades pel compte ECMWF", available_model, default=[])
    custom_model = st.text_input("Capes manuals ECMWF separades per comes", value="", placeholder="ex: msl_public,t850_public,z500_public")
    opacity = st.slider("Opacitat de les capes", 0.15, 1.0, 0.85, 0.05)
    show_borders_model = st.checkbox("Mostrar mapa base amb fronteres", value=True, key="model_borders")

    layer_names = [ECMWF_LAYERS[x] for x in selected_labels]
    layer_names += selected_caps
    if custom_model.strip():
        layer_names += [x.strip() for x in custom_model.split(",") if x.strip()]
    layer_names = list(dict.fromkeys(layer_names))

    width, height = DOMAINS[model_domain]["size"]
    ecmwf_key = clean_secret("ECMWF_API_KEY")
    if not ecmwf_key:
        st.error("Falta ECMWF_API_KEY a Secrets.")
    elif not layer_names:
        st.warning("Tria com a mínim una capa ECMWF.")
    else:
        base = dark_background(width, height)
        if show_borders_model:
            base = add_borders(base, DOMAINS[model_domain]["bbox"], color=(255, 255, 255, 110), line_width=2)
        loaded = []
        captions = []
        for layer in layer_names:
            with st.spinner(f"Carregant ECMWF: {layer}..."):
                r = wms_getmap("https://eccharts.ecmwf.int/wms/", layer, DOMAINS[model_domain]["bbox"], width, height, ecmwf_key=ecmwf_key, transparent="true")
            if r.ok and "image" in r.headers.get("content-type", ""):
                loaded.append(image_from_response(r))
                captions.append(layer)
            else:
                st.warning(f"No carrega: {layer} · HTTP {r.status_code}")
                if "Invalid token" in (r.text or ""):
                    st.error("ECMWF diu Invalid token. Cal revisar la clau ECMWF_API_KEY.")
        if loaded:
            final = compose_layers(base, loaded, [opacity] * len(loaded))
            if show_borders_model:
                final = add_borders(final, DOMAINS[model_domain]["bbox"], color=(255, 255, 255, 160), line_width=2)
            show_pil_image(final, f"ECMWF · {' + '.join(captions)} · {model_domain}")
        else:
            st.error("No s’ha pogut carregar cap capa ECMWF.")

with tab_api:
    st.subheader("🔐 Estat de claus i capes")
    st.write("EUMETSAT_KEY:", "✅ configurada" if has_secret("EUMETSAT_KEY") else "❌ falta")
    st.write("EUMETSAT_SECRET:", "✅ configurada" if has_secret("EUMETSAT_SECRET") else "❌ falta")
    st.write("ECMWF_API_KEY:", "✅ configurada" if has_secret("ECMWF_API_KEY") else "❌ falta")
    st.divider()

    if st.button("Provar GetCapabilities EUMETSAT"):
        token, err = get_eumetsat_token()
        if err:
            st.error(err)
        else:
            r = wms_capabilities("https://view.eumetsat.int/geoserver/ows", token=token)
            st.write("HTTP", r.status_code, r.headers.get("content-type"))
            if r.ok:
                st.code("\n".join(extract_layer_names(r.text, 500)) or r.text[:1500])
            else:
                st.code(r.text[:1500])

    if st.button("Provar GetCapabilities ECMWF"):
        key = clean_secret("ECMWF_API_KEY")
        r = wms_capabilities("https://eccharts.ecmwf.int/wms/", ecmwf_key=key)
        st.write("HTTP", r.status_code, r.headers.get("content-type"))
        if r.ok:
            st.code("\n".join(extract_layer_names(r.text, 500)) or r.text[:1500])
        else:
            st.code(r.text[:1500])

st.info("He afegit més capes EUMETSAT, capes detectades automàticament i correcció perquè ECMWF no peti si una imatge torna amb mida diferent.")
