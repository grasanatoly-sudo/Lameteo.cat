import io, os, re, tempfile, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import imageio.v2 as imageio
import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

st.set_page_config(page_title="Lameteo.cat · Visor", page_icon="🌦️", layout="wide")
st.markdown('''
<style>
.block-container{padding-top:1.1rem;max-width:100%}.stImage img{border-radius:28px;border:1px solid rgba(80,190,255,.32);background:#07111f}.timebox{padding:15px 18px;border:1px solid rgba(80,190,255,.25);border-radius:18px;background:rgba(40,120,200,.12);margin:10px 0 18px 0}.stDownloadButton button,.stButton button{border-radius:999px;font-weight:800}[data-baseweb="tab"]{font-weight:850}div[data-testid="stCaptionContainer"]{color:#aab8c9}
</style>
''', unsafe_allow_html=True)
st.title("🌦️ Lameteo.cat · Visor meteorològic de prova")
st.caption("Radar, satèl·lit i models. Mapes 16:9, fronteres, composició de capes, llegendes grans i exportació PNG/MP4.")

DOMAINS={
 "Catalunya":{"bbox":"-1.2,39.7,4.2,43.25","center":"41.65,1.8,7","size":(1920,1080)},
 "Península Ibèrica":{"bbox":"-10.8,35.0,5.0,44.6","center":"40.2,-3.5,5","size":(1920,1080)},
 "Europa":{"bbox":"-13,34,32,72","center":"48,8,4","size":(1920,1080)},
 "Món":{"bbox":"-80,-60,80,80","center":"20,0,2","size":(1920,1080)},
}
SAT_LAYERS={
 "RGB natural":"msg_fes:rgb_natural","RGB natural millorat":"msg_fes:rgb_natural_enhanced","Airmass RGB · masses d’aire":"msg_fes:rgb_airmass","Dust RGB · pols en suspensió":"msg_fes:rgb_dust","Severe storms RGB · tempestes fortes":"msg_fes:rgb_severe_storms","Day microphysics · boira/núvols baixos":"msg_fes:rgb_day_microphysics","Night microphysics · nit/boira":"msg_fes:rgb_night_microphysics","Cloud phase RGB · fase dels núvols":"msg_fes:rgb_cloud_phase","Cloud type · tipus de núvol":"msg_fes:cloud_type","Cloud mask · núvol/no núvol":"msg_fes:cloud_mask","Cloud top temperature · cim del núvol":"msg_fes:ctth_temperature","Cloud top height · alçada del núvol":"msg_fes:ctth_height","Vapor d’aigua 6.2":"msg_fes:wv062","Vapor d’aigua 7.3":"msg_fes:wv073","Infraroig 10.8":"msg_fes:ir108","Infraroig 12.0":"msg_fes:ir120","IR 3.9 · nit/focs/núvols baixos":"msg_fes:ir039","IR 8.7":"msg_fes:ir087","IR 9.7 · ozó":"msg_fes:ir097","Visible 0.6":"msg_fes:vis006","Visible 0.8":"msg_fes:vis008","NIR 1.6 · neu/gel/núvol":"msg_fes:nir016","Capa manual":"manual"}
ECMWF_LAYERS={
 "Temperatura 850 hPa":"t850_public","Temperatura 2 m":"2t_public","Temperatura 500 hPa":"t500_public","Pressió nivell del mar":"msl_public","Geopotencial 500 hPa":"z500_public","Vorticitat 500 hPa":"vo500_public","Vorticitat + geopotencial 500 hPa":"z500_vo_public","Vent 850 hPa":"ws850_public","Vent 500 hPa":"ws500_public","Jet / vent 300 hPa":"ws300_public","Vent 10 m":"10u_public","Precipitació total":"tp_public","Precipitació 6 h":"tp6_public","Neu acumulada":"sf_public","CAPE":"cape_public","Humitat relativa 700 hPa":"r700_public","Humitat relativa 850 hPa":"r850_public","Aigua precipitable":"tcwv_public","Ensemble Z500 mitjana":"z500_mean_public","Ensemble T850 mitjana":"t850_mean_public","Ensemble MSLP mitjana":"msl_mean_public","Ensemble Z500 spread":"z500_spread_public","Ensemble T850 spread":"t850_spread_public","Ensemble MSLP spread":"msl_spread_public"}
TITLES={"t850_public":"Temperatura a 850 hPa","2t_public":"Temperatura a 2 metres","t500_public":"Temperatura a 500 hPa","msl_public":"Pressió a nivell del mar","z500_public":"Geopotencial a 500 hPa","vo500_public":"Vorticitat a 500 hPa","z500_vo_public":"Vorticitat + geopotencial a 500 hPa","ws850_public":"Vent a 850 hPa","ws500_public":"Vent a 500 hPa","ws300_public":"Jet stream / vent a 300 hPa","10u_public":"Vent a 10 metres","tp_public":"Precipitació total","tp6_public":"Precipitació acumulada 6 h","sf_public":"Neu acumulada","cape_public":"CAPE","r700_public":"Humitat relativa a 700 hPa","r850_public":"Humitat relativa a 850 hPa","tcwv_public":"Aigua precipitable"}
LEGENDS={
 "t850_public":("°C",[-52,-48,-44,-40,-36,-32,-28,-24,-20,-16,-12,-8,-4,0,4,8,12,16,20,24,28,32,36,40,44,48],["#c64adf","#a736c9","#682b7f","#291637","#3600b7","#5d00e8","#004cff","#008cff","#00c8ff","#23f8ff","#27e85f","#96ff00","#d9ff00","#ffff70","#fff000","#ffd200","#ffae00","#ff8200","#ff5500","#ff2600","#e60000","#a10020","#78002b","#e500a0","#ff65ff","#ffc7ff"]),
 "2t_public":("°C",[-28,-24,-20,-16,-12,-8,-4,0,4,8,12,16,20,24,28,32,36,40,44,48],["#4b0082","#3800b8","#0038ff","#007cff","#00b8ff","#00fff0","#36ff80","#94ff00","#dfff00","#ffff66","#ffd700","#ffb000","#ff8000","#ff4a00","#ff0000","#c40000","#850000","#bb0088","#ff5be0","#ffc4ff"]),
 "t500_public":("°C",[-48,-44,-40,-36,-32,-28,-24,-20,-16,-12,-8,-4,0,4],["#2c0057","#3b00a7","#004eff","#009fff","#00f0ff","#00d080","#7bff00","#ffff3d","#ffc000","#ff7a00","#f00000","#a00000","#7a0040","#ff6ee8"]),
 "msl_public":("hPa",[960,970,980,990,1000,1010,1020,1030,1040,1050],["#5b2b83","#2941a5","#208ad6","#24c6d8","#7ce56a","#f0e95a","#ffb13b","#f06a2e","#d92b2b","#9d001f"]),
 "z500_public":("dam",[500,516,532,548,564,580,596],["#2b4c7e","#397dbc","#43b7c2","#84d65a","#f0df4c","#f28d35","#c9412f"]),
 "ws850_public":("km/h",[0,20,40,60,80,100,120,140,160],["#f4fbff","#b9e8ff","#69c8ff","#2394ff","#22d45a","#ffd21f","#ff7a1a","#e60000","#9d00ff"]),
 "ws500_public":("km/h",[0,30,60,90,120,150,180,210],["#f4fbff","#b9e8ff","#3aaeff","#00ce75","#fff000","#ff8a00","#e00000","#8b00ff"]),
 "ws300_public":("km/h",[0,40,80,120,160,200,240,280],["#f4fbff","#9fe0ff","#1b85ff","#00bf60","#ffe000","#ff7200","#d00000","#8800ff"]),
 "tp_public":("mm",[0,1,2,5,10,20,50,100,150,200],["#f7f7f7","#b6e6ff","#55bfff","#1380ff","#0047c7","#00b050","#ffe600","#ff8c00","#d00000","#8b0000"]),
 "cape_public":("J/kg",[0,100,250,500,1000,1500,2000,3000,4000],["#eeeeee","#bfffbf","#78e65a","#d6f000","#ffd000","#ff8900","#e00000","#8b0000","#ff00ff"]),
 "sf_public":("cm",[0,1,2,5,10,20,40,80],["#f7f7f7","#d9f7ff","#a6e8ff","#69c8ff","#3498db","#7b68ee","#8a2be2","#ff69b4"]),
 "r700_public":("%",[0,10,20,30,40,50,60,70,80,90,100],["#7b3f00","#b26b00","#e0a000","#ffe466","#d0ff80","#80f0ff","#30b8ff","#0060d0","#001b80","#6000a0","#c000ff"]),
 "r850_public":("%",[0,10,20,30,40,50,60,70,80,90,100],["#7b3f00","#b26b00","#e0a000","#ffe466","#d0ff80","#80f0ff","#30b8ff","#0060d0","#001b80","#6000a0","#c000ff"]),
 "tcwv_public":("mm",[0,5,10,15,20,25,30,40,50,60],["#fff8dc","#ffe08a","#ffc857","#9be564","#00c2a8","#0096c7","#4361ee","#3a0ca3","#7209b7","#f72585"]),
}

def clean_secret(n):
    try: return str(st.secrets.get(n,"")).strip().replace("\t","").replace("\n","")
    except Exception: return ""
def has_secret(n): return bool(clean_secret(n))
@st.cache_data(ttl=3300, show_spinner=False)
def get_eumetsat_token():
    key,sec=clean_secret("EUMETSAT_KEY"),clean_secret("EUMETSAT_SECRET")
    if not key or not sec: return None,"Falten EUMETSAT_KEY i/o EUMETSAT_SECRET a Secrets."
    r=requests.post("https://api.eumetsat.int/token",auth=(key,sec),data={"grant_type":"client_credentials"},timeout=25)
    if not r.ok: return None,f"EUMETSAT token error {r.status_code}: {r.text[:250]}"
    return r.json().get("access_token"),None

def wms_getmap(url,layer,bbox,width=1920,height=1080,token=None,ecmwf_key=None,transparent="true",extra=None):
    p={"SERVICE":"WMS","VERSION":"1.1.1","REQUEST":"GetMap","LAYERS":layer,"STYLES":"","SRS":"EPSG:4326","BBOX":bbox,"WIDTH":str(width),"HEIGHT":str(height),"FORMAT":"image/png","TRANSPARENT":transparent}
    if extra: p.update({k:v for k,v in extra.items() if v not in (None,"")})
    if ecmwf_key: p["token"]=ecmwf_key
    h={}
    if token: h["Authorization"]=f"Bearer {token}"
    return requests.get(url,params=p,headers=h,timeout=75)

def wms_capabilities(url,token=None,ecmwf_key=None):
    p={"SERVICE":"WMS","VERSION":"1.1.1","REQUEST":"GetCapabilities"}
    if ecmwf_key: p["token"]=ecmwf_key
    h={}
    if token: h["Authorization"]=f"Bearer {token}"
    return requests.get(url,params=p,headers=h,timeout=45)
@st.cache_data(ttl=3600,show_spinner=False)
def wms_legend_bytes(layer,ecmwf_key=None):
    for p in [
        {"SERVICE":"WMS","VERSION":"1.1.1","REQUEST":"GetLegendGraphic","LAYER":layer,"FORMAT":"image/png","WIDTH":"900"},
        {"SERVICE":"WMS","VERSION":"1.3.0","REQUEST":"GetLegendGraphic","LAYER":layer,"FORMAT":"image/png"},
        {"REQUEST":"GetLegendGraphic","LAYER":layer,"FORMAT":"image/png"}]:
        if ecmwf_key: p["token"]=ecmwf_key
        try:
            r=requests.get("https://eccharts.ecmwf.int/wms/",params=p,timeout=30)
            if r.ok and "image" in r.headers.get("content-type","") and len(r.content)>350:
                im=Image.open(io.BytesIO(r.content)).convert("RGBA")
                if im.width>30 and im.height>8:
                    b=io.BytesIO(); im.save(b,format="PNG"); return b.getvalue()
        except Exception: pass
    return b""
def wms_legend(layer,ecmwf_key=None):
    data=wms_legend_bytes(layer,ecmwf_key)
    if not data: return None
    try: return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception: return None

def extract_layer_names(xml,max_layers=900):
    names=[]
    try:
        root=ET.fromstring(xml)
        for e in root.iter():
            if e.tag.endswith("Name") and e.text:
                t=e.text.strip()
                if t and t not in names and (":" in t or t.endswith("_public")): names.append(t)
            if len(names)>=max_layers: break
    except Exception: return []
    return sorted(names)
@st.cache_data(ttl=86400,show_spinner=False)
def load_borders_geojson():
    r=requests.get("https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson",timeout=30); r.raise_for_status(); return r.json()
def lonlat_to_px(lon,lat,bbox,w,h):
    a,b,c,d=[float(x) for x in bbox.split(",")]
    return (lon-a)/(c-a)*w,(d-lat)/(d-b)*h
def draw_geom(draw,geom,bbox,w,h,color,lw):
    polys=[geom.get("coordinates",[])] if geom.get("type")=="Polygon" else geom.get("coordinates",[]) if geom.get("type")=="MultiPolygon" else []
    for poly in polys:
        for ring in poly:
            pts=[]
            for lon,lat,*_ in ring:
                x,y=lonlat_to_px(lon,lat,bbox,w,h)
                if -250<=x<=w+250 and -250<=y<=h+250: pts.append((x,y))
            if len(pts)>1: draw.line(pts,fill=color,width=lw,joint="curve")
def add_borders(img,bbox,color=(255,255,255,205),lw=2):
    try:
        ov=Image.new("RGBA",img.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
        for f in load_borders_geojson().get("features",[]): draw_geom(d,f.get("geometry",{}),bbox,img.width,img.height,color,lw)
        return Image.alpha_composite(img.convert("RGBA"),ov)
    except Exception: return img.convert("RGBA")
def img_from_response(r): return Image.open(io.BytesIO(r.content)).convert("RGBA")
def dark_bg(w,h): return Image.new("RGBA",(w,h),(5,14,29,255))
def norm(im,size):
    im=im.convert("RGBA")
    return im.resize(size,Image.Resampling.LANCZOS) if im.size!=size else im
def compose(base,layers,opacity):
    can=base.convert("RGBA")
    for im in layers:
        im=norm(im,can.size)
        if opacity<1:
            a=ImageEnhance.Brightness(im.getchannel("A")).enhance(opacity); im.putalpha(a)
        can=Image.alpha_composite(can,im)
    return can
def font(s=34,b=True):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try: return ImageFont.truetype(p,s)
        except Exception: pass
    return ImageFont.load_default()
def local_legend(layer,width=850,height=220):
    if layer not in LEGENDS: return None
    unit,vals,cols=LEGENDS[layer]; cols=[tuple(int(c.lstrip('#')[i:i+2],16) for i in (0,2,4)) for c in cols]
    im=Image.new("RGBA",(width,height),(0,0,0,0)); d=ImageDraw.Draw(im); ft=font(34); fv=font(24,False)
    d.text((0,0),f"Escala · {unit}",font=ft,fill=(255,255,255,255)); gx,gy,gw,gh=22,72,width-44,54
    for x in range(gw):
        t=x/max(gw-1,1); i=min(int(t*(len(cols)-1)),len(cols)-2); u=t*(len(cols)-1)-i
        col=tuple(int(cols[i][j]*(1-u)+cols[i+1][j]*u) for j in range(3)); d.line((gx+x,gy,gx+x,gy+gh),fill=col+(255,))
    d.rectangle((gx,gy,gx+gw,gy+gh),outline=(255,255,255,230),width=3)
    ticks=vals if len(vals)<=13 else [vals[round(i*(len(vals)-1)/12)] for i in range(13)]
    for v in ticks:
        idx=vals.index(v); x=gx+int(idx/max(len(vals)-1,1)*gw); d.line((x,gy+gh,x,gy+gh+13),fill=(255,255,255,235),width=3)
        txt=str(v); bb=d.textbbox((0,0),txt,font=fv); d.text((x-(bb[2]-bb[0])//2,gy+gh+18),txt,font=fv,fill=(245,245,245,250))
    return im
def trim(im):
    if im is None: return None
    im=im.convert("RGBA"); bb=im.getbbox(); return im.crop(bb) if bb else im
def title_for(layers):
    if len(layers)==1: return TITLES.get(layers[0],layers[0])
    return TITLES.get(layers[0],layers[0])+" + "+" + ".join(TITLES.get(x,x) for x in layers[1:3])+(f" + {len(layers)-3} capes" if len(layers)>3 else "")
def add_badges(img,title,valid,run,layers,legend=None,legend_layer=None,product="Lameteo.cat · ECMWF"):
    can=img.convert("RGBA"); ov=Image.new("RGBA",can.size,(0,0,0,0)); d=ImageDraw.Draw(ov); pad=42
    d.rectangle((0,0,can.width,225),fill=(0,0,0,75)); d.rectangle((0,can.height-185,can.width,can.height),fill=(0,0,0,55))
    bw=min(can.width-2*pad,1240); bh=235; x0=y0=pad
    d.rounded_rectangle((x0,y0,x0+bw,y0+bh),radius=32,fill=(4,12,26,224),outline=(79,210,255,205),width=3)
    d.text((x0+35,y0+24),product,font=font(30),fill=(130,220,255,255)); d.text((x0+35,y0+70),title,font=font(66),fill=(255,255,255,255))
    d.text((x0+35,y0+154),f"Vàlid: {valid}",font=font(34),fill=(195,238,255,255)); d.text((x0+35,y0+200),f"Run: {run} · {layers[:90]}",font=font(25,False),fill=(235,242,248,245))
    if legend is None and legend_layer: legend=local_legend(legend_layer)
    legend=trim(legend)
    if legend:
        leg=legend.convert("RGBA"); scale=min(min(780,can.width//2)/leg.width,250/leg.height,3.0)
        leg=leg.resize((max(1,int(leg.width*scale)),max(1,int(leg.height*scale))),Image.Resampling.LANCZOS)
        lp=28; lx=can.width-leg.width-2*lp-pad; ly=can.height-leg.height-2*lp-pad-38
        d.rounded_rectangle((lx,ly,lx+leg.width+2*lp,ly+leg.height+2*lp+46),radius=28,fill=(4,12,26,228),outline=(255,255,255,175),width=2)
        d.text((lx+lp,ly+14),"Llegenda oficial / escala",font=font(32),fill=(255,255,255,250)); ov.alpha_composite(leg,(lx+lp,ly+lp+44))
    return Image.alpha_composite(can,ov)
def png_bytes(im):
    b=io.BytesIO(); im.save(b,format="PNG",optimize=True); return b.getvalue()
def safe(s): return re.sub(r"[^A-Za-z0-9_]+","_",s)[:170]
def show_image(im,cap,key):
    data=png_bytes(im); st.image(data,use_container_width=True,caption=cap); st.download_button("⬇️ Descarregar PNG en alta qualitat",data,file_name=f"lameteo_{safe(key)}.png",mime="image/png",key=f"download_{safe(key)}")
def show_error(r): st.error(f"La capa no ha carregat. HTTP {r.status_code}"); st.code((r.text or "").strip()[:1200])
def rounded_run():
    now=datetime.now(timezone.utc); h=(now.hour//6)*6; return now.replace(hour=h,minute=0,second=0,microsecond=0)
def time_label(dt):
    dies=["dilluns","dimarts","dimecres","dijous","divendres","dissabte","diumenge"]; return f"{dies[dt.weekday()]} {dt.strftime('%d/%m %H:%M')} UTC"
@st.cache_data(ttl=1800,show_spinner=False)
def eum_layers():
    tok,err=get_eumetsat_token()
    if err: return []
    r=wms_capabilities("https://view.eumetsat.int/geoserver/ows",token=tok)
    return extract_layer_names(r.text) if r.ok else []
@st.cache_data(ttl=1800,show_spinner=False)
def ecmwf_layers():
    key=clean_secret("ECMWF_API_KEY"); r=wms_capabilities("https://eccharts.ecmwf.int/wms/",ecmwf_key=key)
    return extract_layer_names(r.text) if r.ok else []
def suggestions(av,kws):
    out=[]
    for kw in kws:
        for x in av:
            if kw.lower() in x.lower() and x not in out: out.append(x)
    return out[:100]
def render_ecmwf(layers,domain,hour,opacity,borders=True,overlay=True):
    run=rounded_run(); valid=run+timedelta(hours=hour); iso=valid.strftime("%Y-%m-%dT%H:%M:%SZ"); w,h=DOMAINS[domain]["size"]; key=clean_secret("ECMWF_API_KEY")
    loaded=[]; caps=[]; extra={"TIME":iso}
    for layer in layers:
        r=wms_getmap("https://eccharts.ecmwf.int/wms/",layer,DOMAINS[domain]["bbox"],w,h,ecmwf_key=key,transparent="true",extra=extra)
        if not (r.ok and "image" in r.headers.get("content-type","")):
            r=wms_getmap("https://eccharts.ecmwf.int/wms/",layer,DOMAINS[domain]["bbox"],w,h,ecmwf_key=key,transparent="true")
        if r.ok and "image" in r.headers.get("content-type",""):
            loaded.append(img_from_response(r)); caps.append(layer)
    if not loaded: return None,[],valid,run,iso
    final=compose(dark_bg(w,h),loaded,opacity)
    if borders: final=add_borders(final,DOMAINS[domain]["bbox"])
    if overlay: final=add_badges(final,title_for(caps),time_label(valid),run.strftime("%d/%m %H UTC"),"Capes: "+" + ".join(caps),wms_legend(caps[0],key),caps[0])
    return final,caps,valid,run,iso
def make_mp4(frames,fps=2):
    tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".mp4"); tmp.close()
    imageio.mimsave(tmp.name,[f.convert("RGB") for f in frames],fps=fps,codec="libx264",quality=10,macro_block_size=16)
    data=open(tmp.name,"rb").read(); os.unlink(tmp.name); return data

tab_radar,tab_sat,tab_ecmwf,tab_api=st.tabs(["🌧️ Radar","🛰️ Satèl·lit EUMETSAT","🌍 Model europeu ECMWF","🔐 Estat APIs"])
with tab_radar:
    st.subheader("🌧️ Radar de pluja en directe"); domain=st.selectbox("Zona del radar",list(DOMAINS),index=0,key="radar_domain"); loc=DOMAINS[domain]["center"]
    components.html(f'''<iframe src="https://www.rainviewer.com/map.html?loc={loc}&oFa=0&oC=1&oU=0&oCS=1&oF=0&oAP=1&c=1&o=83&lm=1&layer=radar&sm=1&sn=1" style="width:100%;height:790px;border:0;border-radius:24px;overflow:hidden;"></iframe>''',height=820)
with tab_sat:
    st.subheader("🛰️ Satèl·lit EUMETSAT"); st.markdown("<div class='timebox'>🕒 Satèl·lit: última imatge disponible del servei EUMETSAT WMS. Prova Severe storms, Airmass, Dust i Microphysics per veure tempestes, pols i núvols baixos.</div>",unsafe_allow_html=True)
    c1,c2,c3=st.columns([1.1,1.2,1])
    with c1: sat_domain=st.selectbox("Mapa",list(DOMAINS),index=1,key="sat_domain")
    with c2: sat_label=st.selectbox("Variable satèl·lit",list(SAT_LAYERS),key="sat_layer")
    with c3: custom_sat=st.text_input("Capa manual",value="",placeholder="ex: msg_fes:rgb_natural",key="sat_manual")
    av=eum_layers(); sug=suggestions(av,["rgb","severe","micro","dust","airmass","cloud","ctth","ir","wv","vis","nir"])
    cap=st.selectbox("Capes detectades pel compte EUMETSAT",["-- no usar --"]+sug+[x for x in av if x not in sug],index=0,key="sat_capabilities")
    borders=st.checkbox("Mostrar fronteres i línies de costa",True,key="sat_borders"); enhance=st.checkbox("Millorar contrast i nitidesa",True,key="sat_enhance")
    layer=cap if cap!="-- no usar --" else (custom_sat.strip() or SAT_LAYERS[sat_label])
    if layer=="manual": st.warning("Escriu el nom exacte d’una capa EUMETSAT a 'Capa manual'.")
    else:
        w,h=DOMAINS[sat_domain]["size"]; tok,err=get_eumetsat_token()
        if err: st.error(err)
        else:
            with st.spinner("Carregant imatge EUMETSAT..."): r=wms_getmap("https://view.eumetsat.int/geoserver/ows",layer,DOMAINS[sat_domain]["bbox"],w,h,token=tok,transparent="false")
            if r.ok and "image" in r.headers.get("content-type",""):
                im=img_from_response(r)
                if enhance: im=ImageEnhance.Sharpness(ImageEnhance.Contrast(im).enhance(1.1)).enhance(1.25)
                if borders: im=add_borders(im,DOMAINS[sat_domain]["bbox"],(255,255,255,180),2)
                show_image(im,f"EUMETSAT · {layer} · {sat_domain} · última imatge disponible",f"sat_{sat_domain}_{layer}")
            else: show_error(r)
with tab_ecmwf:
    st.subheader("🌍 Model europeu ECMWF"); run=rounded_run(); fh=st.slider("Línia temporal del model · hora de previsió",0,120,0,3,key="ecmwf_time"); valid=run+timedelta(hours=fh)
    st.markdown(f"<div class='timebox'>🕒 Run aproximat ECMWF: <b>{run.strftime('%d/%m %H UTC')}</b> · Previsió: <b>+{fh} h</b> · Vàlid per: <b>{time_label(valid)}</b></div>",unsafe_allow_html=True)
    c1,c2=st.columns([1,2])
    with c1: model_domain=st.selectbox("Mapa",list(DOMAINS),index=2,key="ecmwf_domain")
    with c2: labels=st.multiselect("Capes ECMWF superposades",list(ECMWF_LAYERS),default=["Temperatura 850 hPa"],key="ecmwf_layers")
    avm=ecmwf_layers(); sug=suggestions(avm,["t850","z500","msl","tp","cape","wind","ws","vo","vort","jet","snow","humidity","r700","2t"])
    caps=st.multiselect("Capes detectades pel compte ECMWF",sug+[x for x in avm if x not in sug],default=[],key="ecmwf_capabilities")
    custom=st.text_input("Capes manuals ECMWF separades per comes",value="",placeholder="ex: msl_public,t850_public,z500_public",key="ecmwf_manual")
    opacity=st.slider("Opacitat de les capes",0.15,1.0,0.9,0.05,key="ecmwf_opacity")
    borders=st.checkbox("Mostrar mapa base amb fronteres",True,key="model_borders"); overlay=st.checkbox("Mostrar títol, data i llegenda dins del mapa",True,key="model_overlay")
    st.caption("Les fletxes de vent reals només surten si la capa ECMWF escollida ja les porta. Per dibuixar fletxes pròpies caldria carregar dades vectorials/GRIB, no només una imatge WMS.")
    layers=[ECMWF_LAYERS[x] for x in labels]+caps+([x.strip() for x in custom.split(",") if x.strip()] if custom.strip() else [])
    layers=list(dict.fromkeys(layers)); key=clean_secret("ECMWF_API_KEY")
    if not key: st.error("Falta ECMWF_API_KEY a Secrets.")
    elif not layers: st.warning("Tria com a mínim una capa ECMWF.")
    else:
        with st.spinner("Carregant mapa ECMWF en alta resolució..."): final,captions,valid,run,iso=render_ecmwf(layers,model_domain,fh,opacity,borders,overlay)
        if final:
            show_image(final,f"ECMWF · {' + '.join(captions)} · {model_domain} · Vàlid: {time_label(valid)} · TIME={iso}",f"ecmwf_{model_domain}_{fh}_{'_'.join(captions)}")
            st.divider(); st.subheader("🎬 Exportar vídeo MP4")
            a,b,c=st.columns(3)
            with a: start=st.number_input("Inici",0,120,0,3,key="video_start")
            with b: end=st.number_input("Final",0,120,48,3,key="video_end")
            with c: step=st.selectbox("Salt entre mapes",[3,6,12],index=1,key="video_step")
            fps=st.slider("Velocitat del vídeo",1,6,2,key="video_fps")
            if st.button("🎥 Generar MP4 dels mapes",key="generate_mp4"):
                if end<start: st.error("El final ha de ser més gran que l'inici.")
                else:
                    hrs=list(range(int(start),int(end)+1,int(step))); frames=[]; prog=st.progress(0)
                    for i,hour in enumerate(hrs):
                        im,_,_,_,_=render_ecmwf(layers,model_domain,hour,opacity,borders,True)
                        if im: frames.append(im)
                        prog.progress((i+1)/len(hrs))
                    if len(frames)>=2:
                        mp4=make_mp4(frames,fps=fps); st.download_button("⬇️ Descarregar vídeo MP4",mp4,file_name="lameteo_ecmwf_animacio.mp4",mime="video/mp4",key="download_mp4_final"); st.success("Vídeo creat correctament.")
                    else: st.error("No hi ha prou fotogrames per crear el vídeo.")
        else: st.error("No s’ha pogut carregar cap capa ECMWF.")
with tab_api:
    st.subheader("🔐 Estat de claus i capes"); st.write(f"EUMETSAT_KEY: {'✅ configurada' if has_secret('EUMETSAT_KEY') else '❌ falta'}"); st.write(f"EUMETSAT_SECRET: {'✅ configurada' if has_secret('EUMETSAT_SECRET') else '❌ falta'}"); st.write(f"ECMWF_API_KEY: {'✅ configurada' if has_secret('ECMWF_API_KEY') else '❌ falta'}")
    st.divider()
    if st.button("Provar GetCapabilities EUMETSAT",key="cap_sat_btn"):
        tok,err=get_eumetsat_token()
        if err: st.error(err)
        else:
            r=wms_capabilities("https://view.eumetsat.int/geoserver/ows",token=tok); st.write("HTTP",r.status_code); st.code(r.text[:5000])
    if st.button("Provar GetCapabilities ECMWF",key="cap_ecmwf_btn"):
        k=clean_secret("ECMWF_API_KEY"); r=wms_capabilities("https://eccharts.ecmwf.int/wms/",ecmwf_key=k); st.write("HTTP",r.status_code); st.code(r.text[:5000])
    st.info("Actualitzat: més capes EUMETSAT, més productes ECMWF, capes detectades, títol i llegenda més grans, PNG/MP4 i avís sobre fletxes de vent reals.")
