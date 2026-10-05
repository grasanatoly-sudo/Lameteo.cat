# ECMWF interactive · Catalunya

Pipeline per al visor interactiu de **Lameteo.cat Models**.

## Fase actual

- Model: ECMWF IFS Open Data
- Resolució: 0,25°
- Variable: temperatura a 2 m
- Zona: Catalunya i entorn
- Horitzó: +0 a +72 h, cada 6 h
- Sortida: `data/models/ecmwf/temperature_2m_catalunya.json`

El fitxer JSON conté la graella real d'ECMWF en °C, les hores vàlides i les metadades del run. El frontend de Lameteo.cat el representarà sobre un mapa Leaflet interactiu.

## Automatització

GitHub Actions actualitza la graella quatre vegades al dia, un cop la nova sortida d'ECMWF ja sol estar disponible.

## Font i llicència

Dades: ECMWF IFS Open Data. Reutilització sota CC BY 4.0 amb atribució.
