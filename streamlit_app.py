import xml.etree.ElementTree as ET

import requests
import streamlit as st
import streamlit.components.v1 as components

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
st.caption("Radar, satèl·lit i models. Ara el satèl·lit usa WMS 1.1.1 per evitar el problema de coordenades.")

DOMAINS = {
    "Catalunya": {"bbox": "-1.2,39.7,4.2,43.2", "center": "41.65,1.8,7", "size": (1400, 900)},
    "Península Ibèrica": {"bbox": "-10.8,35.0,5.0,44.6", "center": "40.2,-3.5,5", "size": (1500, 900)},
    "Europa": {"bbox": "-13,34,32,72", "center": "48,8,4", "size": (1500, 1150)},
    "Món": {"bbox": "-80,-60,80,80", "center": "20,0,2", "size": (1500, 900)},
}

SAT_LAYERS = {
    "Natural color / RGB": "msg_fes:rgb_natural",
    "Infraroig 10.8": "msg_fes:ir108",
    "Airmass RGB": "msg_fes:airmass",
    "Dust RGB": "msg_fes:dust",
    "Vapor d’aigua 6.2": "msg_fes:wv062",
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


def wms_getmap(url, layer, bbox, width=1500, height=950, token=None, ecmwf_key=None, transparent="false"):
    # WMS 1.1.1 + SRS EPSG:4326 manté BBOX en ordre lon,lat.
    # Això evita que Europa surti desplaçada cap a Aràbia o altres zones.
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
        # Provem el paràmetre token perquè alguns WMS d'ECMWF el demanen així.
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


def extract_layer_names(xml_text, max_layers=120):
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


def show_response_error(r):
    st.error(f"La capa no ha carregat. HTTP {r.status_code}")
    st.code((r.text or "").strip()[:1200])


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

    layer = custom_sat.strip() or SAT_LAYERS[sat_label]
    width, height = DOMAINS[sat_domain]["size"]
    token, err = get_eumetsat_token()
    if err:
        st.error(err)
    else:
        with st.spinner("Carregant imatge EUMETSAT..."):
            r = wms_getmap("https://view.eumetsat.int/geoserver/ows", layer, DOMAINS[sat_domain]["bbox"], width, height, token=token, transparent="false")
        if r.ok and "image" in r.headers.get("content-type", ""):
            st.image(r.content, use_container_width=True, caption=f"EUMETSAT · {layer} · {sat_domain}")
        else:
            show_response_error(r)

with tab_ecmwf:
    st.subheader("🌍 Model europeu ECMWF")
    c1, c2, c3 = st.columns([1.1, 1.2, 1])
    with c1:
        model_domain = st.selectbox("Mapa", list(DOMAINS.keys()), index=1, key="ecmwf_domain")
    with c2:
        model_label = st.selectbox("Variable ECMWF", list(ECMWF_LAYERS.keys()), key="ecmwf_layer")
    with c3:
        custom_model = st.text_input("Capa manual ECMWF", value="", placeholder="ex: msl_public")

    layer = custom_model.strip() or ECMWF_LAYERS[model_label]
    width, height = DOMAINS[model_domain]["size"]
    ecmwf_key = clean_secret("ECMWF_API_KEY")
    if not ecmwf_key:
        st.error("Falta ECMWF_API_KEY a Secrets.")
    else:
        with st.spinner("Carregant imatge ECMWF..."):
            r = wms_getmap("https://eccharts.ecmwf.int/wms/", layer, DOMAINS[model_domain]["bbox"], width, height, ecmwf_key=ecmwf_key, transparent="true")
        if r.ok and "image" in r.headers.get("content-type", ""):
            st.image(r.content, use_container_width=True, caption=f"ECMWF · {layer} · {model_domain}")
        elif r.status_code == 403 and "Invalid token" in (r.text or ""):
            st.error("ECMWF diu: Invalid token. La clau ECMWF que hi ha a Secrets no és vàlida per ecCharts WMS, o s’ha copiat malament.")
            st.warning("Revisa ECMWF_API_KEY a Streamlit Secrets. Si acaba de ser creada, genera’n una nova i enganxa-la sense espais ni tabuladors.")
            st.code((r.text or "").strip()[:1200])
        else:
            show_response_error(r)

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
                layers = extract_layer_names(r.text)
                st.write("Primeres capes trobades:")
                st.code("\n".join(layers[:120]) or r.text[:1500])
            else:
                st.code(r.text[:1500])

    if st.button("Provar GetCapabilities ECMWF"):
        key = clean_secret("ECMWF_API_KEY")
        r = wms_capabilities("https://eccharts.ecmwf.int/wms/", ecmwf_key=key)
        st.write("HTTP", r.status_code, r.headers.get("content-type"))
        if r.ok:
            layers = extract_layer_names(r.text)
            st.write("Primeres capes trobades:")
            st.code("\n".join(layers[:120]) or r.text[:1500])
        else:
            st.code(r.text[:1500])

st.info("Satèl·lit corregit: ara utilitza WMS 1.1.1 per evitar coordenades mal interpretades. ECMWF necessita una clau vàlida per ecCharts WMS.")
