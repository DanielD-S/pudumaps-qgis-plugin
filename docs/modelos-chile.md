# Modelos IA en Chile — guía de uso

Los modelos pre-entrenados de [geoai-py](https://github.com/opengeos/geoai) están entrenados mayoritariamente sobre imagen NAIP de EE.UU. Esto significa que **rinden distinto en Chile** según el tipo de terreno, la resolución de la imagen y el modelo específico.

Esta página resume **qué funciona bien hoy** con los pesos de fábrica y **qué requiere finetuning** (planeado para v0.8, Nivel 2 del roadmap IA).

> **Tip**: las pruebas iniciales conviene hacerlas con **ortofoto del IDE Chile** (https://www.ide.cl) o del IGM en lugar de imagen Sentinel cruda. Los modelos de geoai esperan resoluciones submétricas similares a NAIP, no Sentinel-2 a 10 m/px.

---

## Detectar edificaciones (`extract_buildings`)

| Caso | Rinde | Notas |
|---|---|---|
| Zonas urbanas consolidadas (Las Condes, Providencia, Maipú) | ✅ Bien | Ortofoto IDE Chile ≤1 m/px. Detecta >90% de edificaciones. |
| Centros históricos (Valparaíso, Castro) | ⚠️ Regular | Techos irregulares y muy pegados confunden al modelo. Revisar manualmente. |
| Zonas rurales modernas (parcelas Maule, Ñuble) | ⚠️ Regular | Casas aisladas con techo claro: OK. Galpones agrícolas: detecta como edificio (esperado). |
| Casas de adobe / quincha rural | ❌ Falla | Modelo entrenado en techos asfálticos USA no las reconoce. Requiere finetuning. |
| Palafitos (Chiloé, Quellón) | ❌ Falla | Geometría sobre agua confunde la máscara. Caso específico chileno. |
| Mediaguas / construcciones precarias | ❌ Falla | Tamaño y forma fuera del dominio de entrenamiento. |
| Tomas / campamentos | ❌ Falla | Densidad y materiales diferentes. **Planeado v0.8** como modelo propio (`pudumaps/tomas-cl-v1`). |
| Imagen Sentinel-2 (10 m/px) | ⚠️ Solo edificios grandes | Detecta solo edificaciones >200 m² (galpones, hospitales, fábricas). Para vivienda usar ortofoto. |

---

## Detectar cuerpos de agua (`extract_water`)

| Caso | Rinde | Notas |
|---|---|---|
| Lagos cordilleranos (Llanquihue, Ranco, Todos los Santos) | ✅ Bien | Sentinel-2 RGB funciona. Bordes precisos. |
| Embalses centrales (Rapel, Colbún, Cogotí) | ✅ Bien | Niveles bajos: detecta correctamente la superficie remanente. |
| Ríos anchos (Bío-Bío, Maule en su desembocadura) | ✅ Bien | A 10 m/px detecta el cauce principal. |
| Ríos angostos (Aconcagua, Itata aguas arriba) | ⚠️ Parcial | A 10 m/px pierde tramos <30 m de ancho. Usar ortofoto. |
| Ríos trenzados andinos (Baker, Pascua) | ⚠️ Parcial | Geometría compleja con islas no siempre se separa bien. |
| Salares con espejo de agua (Surire, Huasco lagunas) | ✅ Bien | Detecta solo la laguna superficial, no la costra. Esperado. |
| Salar de Atacama (costra seca) | ❌ No aplica | No es agua superficial; ignorar. |
| Glaciares andinos | ❌ Falla | Modelo separa "agua líquida" vs "hielo" mal. Usar índice NDSI clásico. |
| Bofedales | ❌ Falla | Detecta solo si tienen lámina de agua visible. Para bofedales sin espejo usar NDVI/NDWI. |

---

## ¿Qué viene en v0.8 (Nivel 2)?

Modelos finetuneados específicos para Chile, entrenados gratis en Kaggle Free Tier sobre datasets públicos:

| Modelo | Dataset de entrenamiento | Casos que mejora |
|---|---|---|
| `pudumaps/buildings-rural-cl-v1` | CBR de municipios + orto IGM | Casas de adobe, palafitos, mediaguas |
| `pudumaps/bosque-nativo-cl-v1` | CONAF Catastro Bosque Nativo | Distinguir bosque nativo vs plantación pino/eucalipto |
| `pudumaps/tomas-cl-v1` | MINVU Catastro de Campamentos | Detección automática de tomas (uso MINVU/municipal) |

Los pesos se publicarán en Hugging Face Hub bajo licencia MIT/CC-BY-SA. El plugin los descargará automáticamente como alternativa a los modelos USA de geoai.

---

## Recomendaciones de input

1. **Usar ortofoto IDE Chile o IGM** en vez de Sentinel cruda cuando se pueda — los modelos de geoai esperan resolución submétrica.
2. **Componer RGB explícitamente** antes de pasar a la tool si tu raster Sentinel viene con bandas separadas: la mayoría de modelos espera tres bandas en orden R, G, B.
3. **Recortar al área de interés** antes de procesar: rásters >2000×2000 px se procesan en tiles automáticamente, pero la inferencia toma minutos en CPU. En GPU es razonable.
4. **Validar manualmente** una muestra antes de usar la salida en producción: los modelos no son infalibles y la calidad varía por zona del país.

---

## ¿Encontraste un caso que rinde distinto a lo documentado?

Abre un issue en https://github.com/DanielD-S/pudumaps-qgis-plugin/issues con:

- Tool usada (`extract_buildings`, `extract_water`, ...)
- Tipo de imagen (Sentinel/Landsat/orto IDE/orto privada) y resolución
- Zona geográfica (comuna o coordenadas aproximadas)
- Captura del resultado vs. verdad terreno

Esto alimenta directamente el dataset que usaremos en v1.0 (active learning) para mejorar los modelos chilenos.
