import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Lameteo.cat · Prova", page_icon="🌦️", layout="wide")

st.title("🌦️ Lameteo.cat · Prova")
st.caption("App de prova per configurar APIs, radar, satèl·lit i models.")

st.subheader("🌧️ Radar de pluja en directe")
components.html('''
<iframe 
src="https://www.rainviewer.com/map.html?loc=41.65,1.8,7&oFa=0&oC=1&oU=0&oCS=1&oF=0&oAP=1&c=1&o=83&lm=1&layer=radar&sm=1&sn=1"
style="width:100%;height:760px;border:0;border-radius:22px;overflow:hidden;">
</iframe>
''', height=790)

st.info("Quan aquesta app funcioni, després hi posarem Secrets i activarem EUMETSAT/ECMWF amb APIs.")
