# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.9.2] — 2026-08-20

### Changed
- **`DEFAULT_BASE_URL` pasa de la Edge Function de Supabase a
  `https://pudumaps.cl/api`.** Un rewrite en Vercel
  ([pudumaps#254](https://github.com/DanielD-S/pudumaps/pull/254)) proxea
  `/api/v1/*` hacia la misma función. El endpoint de Supabase no se elimina:
  sigue vivo y las instalaciones que lo tengan guardado siguen funcionando.

  El motivo de fondo no es cosmético. Cada instalación guarda la URL en
  `QSettings`/`QgsAuthManager`, así que mientras el default apunte a un
  proyecto Supabase concreto, migrar de proyecto dejaría a todos los usuarios
  apuntando al lugar equivocado sin forma de redirigirlos.
- **Las instalaciones existentes se migran solas.** `normalize_base_url()`
  reescribe las dos URLs que el plugin usó como default históricamente
  (`*.supabase.co/functions/v1/api-v1` y `*.functions.supabase.co/api-v1`) al
  default actual, en `auth.load_credentials()` — el único punto de lectura de
  credenciales, así que cubre todos los caminos. Una URL personalizada (dev,
  self-host, localhost) se devuelve intacta.
- **El campo "Base URL" queda oculto tras una casilla "Avanzado".** Solo le
  sirve a quien apunta a un entorno propio; para el resto era ruido y además
  exponía el endpoint interno. Se abre automáticamente si la URL guardada no
  es la default, para que nadie quede apuntando a otro lado sin verlo.

### Added
- 7 tests para `normalize_base_url`, incluido un guardarraíl que falla si
  alguien vuelve a poner una URL de Supabase como default.

### Verificado en un Qt real
Al contrario de lo que decían las notas de 0.8.7 en adelante, **sí hay QGIS
instalado** en el entorno de desarrollo (3.40.9, Qt 5.15.13 / PyQt 5.15.11).
El diálogo se renderizó fuera de pantalla con el Python de QGIS, en los tres
casos: instalación limpia, instalación migrada desde la URL de Supabase, y
URL personalizada. Eso destapó tres defectos que el código no mostraba:

1. **Campos desalineados.** Con la fila Base URL en su propio `QFormLayout`,
   cada layout calculaba su propia columna de etiquetas y los dos campos no
   coincidían — "API Key:" y "Base URL:" no miden lo mismo. Ahora comparten
   un único `QFormLayout` y se oculta la fila entera, etiqueta incluida.
2. **El diálogo no volvía a encoger.** Al replegar quedaba con el alto de la
   versión desplegada (285 → 311 → 311). `adjustSize()` por sí solo no baja
   de la altura ya alcanzada: hay que reactivar el layout y resetear el alto.
   Ahora hace 285 → 311 → 285.
3. **La casilla quedaba debajo del campo que abre**, lo que se lee al revés.
   Pasó a ser una fila del propio formulario, entre API Key y Base URL.

## [0.9.1] — 2026-08-20

### Fixed
- **El diálogo de Configuración decía que la API requiere plan Pro.** El texto
  de ayuda en `dialogs/settings_dialog.py` seguía diciendo "Requiere plan Pro o
  superior". El acceso a la API se abrió a todos los planes, incluido el
  gratuito, el 2026-08-19 (DanielD-S/pudumaps#249). La v0.8.2 corrigió
  `metadata.txt` y el `README.md`, pero se le escapó este string — que es el
  único de los tres que el usuario ve de verdad, al abrir Complementos →
  Pudumaps → Configuración. Un usuario del plan gratuito leía que necesitaba
  pagar para usar el plugin.

## [0.9.0] — 2026-08-20

### Changed
- **El plugin deja de estar marcado como experimental** (`experimental=False`
  en `metadata.txt`). Hasta 0.8.7 solo era visible en el Administrador de
  Complementos de QGIS con "Mostrar también complementos experimentales"
  activado, y plugins.qgis.org mostraba "This plugin has no public version
  yet" con la tabla de versiones vacía.
- **Sin cambios funcionales respecto de 0.8.7** — el ZIP publicado es
  byte-idéntico al de 0.8.7 salvo `metadata.txt` (verificado comparando
  SHA-256 archivo por archivo: 25 archivos, 1 distinto). El salto de versión
  marca el cambio de estado de publicación, no una funcionalidad nueva.
- Pre-flight: 164 tests en verde, `bandit` 0 issues sobre los 2442 LOC que se
  publican, `metadata.txt` parsea con `configparser`, `LICENSE` presente en el
  ZIP, 0 enums PyQt sin calificar. `ruff` reporta 11 findings cosméticos en el
  código publicado — 2 son falsos positivos obligatorios de la API de QGIS
  (`classFactory`, `initGui` deben ir en camelCase) y el resto son
  modernizaciones de tipado que un `ruff` más nuevo empezó a sugerir; ninguno
  lo mira el scanner de plugins.qgis.org, que corre flake8 + bandit +
  detect-secrets. Se dejan sin tocar a propósito para que el ZIP siga siendo
  byte-idéntico al que ya pasó 5/5 checks.

- **`homepage` pasa de `https://pudumaps.cl` a `https://pudumaps.cl/qgis`.** La
  guía de aprobación de plugins.qgis.org pide que el enlace de homepage lleve a
  una página que describa la funcionalidad del plugin, y dice explícitamente que
  cualquier otro enlace es causa de rechazo. La raíz de pudumaps.cl es la
  pantalla de login; `/qgis` es la página que describe el plugin, sus pasos de
  instalación y la descarga. `tracker` y `repository` ya cumplían.

### Notas de alcance para la primera versión estable
- **Verificado end-to-end contra datos reales:** pull de proyectos y capas,
  incluidas capas externas WMS/ArcGIS del catálogo Capas Oficiales de Chile
  (SERNAGEOMIN, SENAPRED).
- **Menos horas de vuelo:** push y sync bidireccional. El diseño es
  conservador por defecto — `suggested_action_for(CONFLICT)` es `SKIP` y sin
  `last_hash` previo dos lados distintos se clasifican como `CONFLICT`, no
  como sobrescritura silenciosa (ver `sync_manager.py`). Aun así, es la
  superficie con más riesgo de un reporte de bug ahora que el plugin es
  visible sin activar experimentales.
- **No smoke-testeado en un runtime Qt6/PyQt6 real** (no hay QGIS instalado
  en el entorno de desarrollo); arrastra la misma nota que 0.8.7.
- **La próxima versión NO puede ser 0.10.0.** El feed `plugins.xml` elige cuál
  es la "última" versión por comparación de *string*, no numérica (documentado
  en la FAQ de plugins.qgis.org). `"0.10.0" < "0.9.0"` porque `1 < 9`, así que
  publicar 0.10.0 dejaría a QGIS ofreciendo 0.9.0 como la más nueva. Después de
  0.9.0 hay que ir a 0.9.x o saltar a 1.0.0.

## [0.8.7] — 2026-08-19

### Fixed
- **48 issues de compatibilidad Qt6** detectados por el check de plugins.qgis.org
  al subir v0.8.6 (security scan pasó, Qt6 Check no) — enums de PyQt5 sin
  calificar (`QMessageBox.Yes` → `QMessageBox.StandardButton.Yes`, etc.) y
  4 usos de `.exec_()` (removido en PyQt6). Corregidos en 8 archivos:
  `error_utils.py`, `plugin.py`, `ui_helpers.py`,
  `dialogs/{upload,settings,sync,projects}_dialog.py`. Sigue siendo válido
  en PyQt5/Qt5 — la forma calificada nunca fue exclusiva de Qt6.
- **Nota:** no se pudo probar contra un runtime Qt6/PyQt6 real (sin QGIS
  instalado en el entorno de desarrollo) — verificado por sintaxis, bandit,
  ruff y 164 tests, pero es el patrón estándar de migración PyQt5→PyQt6,
  no smoke-testeado end-to-end en Qt6.

## [0.8.6] — 2026-08-19

### Fixed
- **3 hallazgos CRÍTICOS de Bandit bloqueaban el scan de seguridad de
  plugins.qgis.org** (`error_utils.py`, `plugin.py`,
  `project_loader.py`) — su scanner trata `try/except/pass` como
  crítico, a diferencia de `bandit` local (LOW). Fix real: los 3 ahora
  loggean el error en vez de tragárselo en silencio, mismo
  comportamiento best-effort de antes. `bandit`: 0 issues (antes 3).

## [0.8.5] — 2026-08-19

### Fixed
- **Faltaba `LICENSE` dentro del ZIP publicado** — plugins.qgis.org lo
  exige junto a `metadata.txt`. El `LICENSE` (GPL-3.0) vive en la raíz
  del repo; `build.py`/`build.sh` solo empaquetaban `pudumaps_qgis/` y
  nunca lo incluían. Ambos scripts ahora lo copian dentro del paquete
  al construir el ZIP.

## [0.8.4] — 2026-08-19

### Fixed
- **`metadata.txt` rompía el parser INI de plugins.qgis.org al subir el
  ZIP**: `'%' must be followed by '%' or '(', found: '%.'`. El
  changelog de v0.7.6 tenía un `%` suelto ("nubosidad %.") sin escapar
  — `metadata.txt` se lee con `configparser` (formato INI), que trata
  `%` como carácter especial de interpolación. Escapado a `%%`.
  Verificado simulando el mismo parser (`ConfigParser` + resolución de
  cada valor) antes de subir: parsea limpio.

## [0.8.3] — 2026-08-19

### Changed
- Limpieza de código previa a publicar en plugins.qgis.org: 2 imports
  sin usar, 2 f-strings sin placeholder, 3 líneas >100 columnas. Sin
  cambios de comportamiento — verificado con `bandit` (0 issues
  medium/high) y `ruff --select E,F,W` (0 issues).

## [0.8.2] — 2026-08-18

### Changed
- El acceso a la API de Pudumaps ya no requiere plan Pro o superior —
  ahora está disponible en todos los planes, incluido Free. Se
  actualiza `metadata.txt` y `README.md`, que decían lo contrario.

## [0.8.1] — 2026-08-17

### Fixed
- **Capas del catálogo "Capas Oficiales de Chile" (WMS/ArcGIS) quedaban
  invisibles al hacer pull.** Estas capas se guardan en `project_layers`
  con `geojson=null` (el detalle real vive en `layer_type`/`external_url`,
  la web las resuelve en vivo), pero la API v1 nunca exponía esos campos —
  el plugin recibía `geojson=null` para todas y las trataba como
  `FeatureCollection` vacía, así que el canvas quedaba en blanco y sin
  zoom para el proyecto entero, no solo la capa WMS.
- Requiere la migración `20260817190000_api_v1_expose_external_layers` en
  el backend (expone `layer_type`/`external_url`/`metadata` en
  `api_v1_list_layers`/`api_v1_get_layer`).
- `project_loader` ahora crea `QgsRasterLayer` (wms/arcgismapserver) o
  `QgsVectorLayer` (arcgisfeatureserver) para capas externas en vez de
  intentar vectorizar un GeoJSON vacío. `weather` (calculado en el
  navegador, sin servicio geoespacial real) se reporta como no soportado.
- `_zoom_to_group` ya no aborta silenciosamente al toparse con una capa
  raster (`featureCount()` no existe fuera de capas vectoriales).
- Sync y "Subir a Pudumaps" excluyen capas externas — son referencias en
  vivo, no datos locales.

## [0.8.0] — 2026-08-17

Desarrollo del módulo IA cancelado por ahora. Release de hardening enfocada
en dejar el plugin listo para publicación futura.

### Removed
- Módulo IA (`extract_buildings`, `extract_water`, `landcover_classification`,
  `change_detection`, `download_sentinel`) sacado de la UI: sin entrada de
  menú/toolbar, sin panel lateral, sin instalador. Motivo: dependía de un
  instalador pip pesado (~2 GB, PyTorch + geoai-py + GeoAgent) contra el
  Python embebido de QGIS, con una cadena larga de hotfixes de DLL/CRS
  (v0.7.7–v0.7.15) y sin smoke test manual completo de las 5 acciones sobre
  datos chilenos. No es un feature listo para usuarios finales.
- El código (`pudumaps_qgis/ai/`, diálogos `ai_panel.py`,
  `install_ai_dialog.py`, `change_detection_dialog.py`,
  `download_sentinel_dialog.py`) se mantiene en el repo por si se retoma,
  pero `scripts/build.py` y `build.sh` ahora lo excluyen del zip publicado.

### Changed
- El plugin publicado deja de arrastrar la superficie de fallo de
  PyTorch/geoai (conflictos MKL, DLL load failed, pyarrow rompiendo QGIS,
  CRS mal etiquetado). Única dependencia externa: `requests`, ya bundleada
  en QGIS 3.x en todas las plataformas.
- Foco del plugin vuelve a ser exclusivamente sync con Pudumaps: configurar
  API key, abrir proyectos, subir capas y sincronizar cambios bidireccional.

## [0.7.10] — 2026-05-18

Smoke test release. Resuelve los 4 bugs reportados durante validación
manual de 0.7.6/0.7.7/0.7.8 + alinea wrappers con API real de geoai 0.10.

### Fixed
- **DLL load failed en QgsTask** (Windows): warm-up de `import geoai`
  en main thread vía `warm_up_geoai()`. La primera vez por sesión
  bloquea 30-90s con dialog "Cargando módulo IA". Tasks subsiguientes
  vuelan sin re-inicializar DLLs. Causa: PyTorch en Windows no soporta
  inicialización desde threads worker.
- **PyTorch CUDA por default** (Windows sin GPU): el instalador ahora
  fuerza CPU-only desde `https://download.pytorch.org/whl/cpu` antes
  de instalar geoai. Evita el "DLL load failed" cuando pip baja la
  variante CUDA que requiere drivers NVIDIA.
- **Detección de python.exe QGIS** (más robusta que 0.7.8): combina
  `os.__file__` + cadena de fallbacks sobre `sys.prefix`/`exec_prefix`/
  `base_prefix` + layout OSGeo4W. Cubre el caso QGIS-Windows donde
  `sys.prefix` apunta al QGIS root en vez del Python embebido.

### Changed — Rewrite de las 5 acciones IA con APIs reales de geoai 0.10.0
- **`extract_buildings`**: `BuildingFootprintExtractor.process_raster()`
  (no `.predict()`). Produce GeoTIFF intermedio + vectoriza a GeoJSON.
- **`change_detection`**: `ChangeDetection` (clase, no `ChangeDetector`)
  con método `detect_changes(image1_path, image2_path, output_path)`.
  Descarga SAM ViT-H checkpoint (~2.4 GB) la primera vez.
- **`extract_water`**: `CLIPSegmentation.segment_image()` con text prompt
  "water bodies, lakes, rivers, reservoirs". Threshold 0.4. Vectoriza
  máscara con rasterio + shapely.
- **`landcover_classification`** *(marcado experimental)*: usa
  `image_segmentation()` de geoai.hf con default
  `facebook/mask2former-cityscapes` que NO es ideal para landcover
  satelital. Mejora planeada v0.8 con modelo HF de landcover (Prithvi).
- **`download_sentinel`**: reescrito desde cero con `pystac_client` +
  `planetary-computer` (deps de geoai ya instaladas). Query STAC
  `sentinel-2-l2a` en Microsoft Planetary Computer, ordena por menor
  cloud cover, descarga R/G/B (B04/B03/B02) recortadas al bbox con
  rioxarray, apila en GeoTIFF.

### Added — UX polish
- **Barra de progreso real** durante `pip install`: parser de líneas
  pip (`PipProgressParser`) extrae paquete N/M + MB descargados +
  tiempo transcurrido. Cap en 95% hasta ver "Successfully installed".
- **`CREATE_NO_WINDOW`** en subprocess: pip ya no abre ventana cmd
  negra durante la instalación. Si por algún edge case aparece, el
  dialog avisa "no la cierres".
- Tiempo estimado de instalación en el aviso del dialog ("10-30 min,
  ~500 MB de PyTorch").

### Notes
- Pendiente smoke test manual completo de las 5 acciones con datos
  reales. Si alguna API tampoco coincide con lo verificado en el repo
  upstream, fix targeted en 0.7.11.
- Las acciones todavía corren CPU-only — la inferencia puede tomar
  minutos sobre rásters grandes.

## [0.7.8] — 2026-05-18

### Fixed
- **Hotfix más robusto** sobre el de 0.7.7. La estrategia "derivar
  python.exe desde `sys.prefix`" no cubría todas las layouts de
  QGIS-Windows — algunas distribuciones tienen `sys.prefix` apuntando
  al root de QGIS, no al directorio del Python embebido. El usuario
  seguía viendo el mismo error "could not be found".
- **Nueva estrategia primaria**: derivar desde `os.__file__`, que
  SIEMPRE apunta a `<python_root>/Lib/os.py`. Esto es independiente
  de cómo el embebedor de QGIS haya configurado `sys.prefix`.
- Cadena de fallbacks: `os.__file__` → todos los prefijos
  (`prefix`/`exec_prefix`/`base_prefix`) × nombres
  (python.exe/python3.exe/pythonw.exe) → subdirs (Scripts/bin) →
  layout OSGeo4W (`apps/Python*/python.exe`) → último recurso
  `sys.executable`.

### Added
- **Defensa en el instalador**: valida que el python resuelto sea un
  archivo real antes de invocar `subprocess`. Si la detección falla,
  error claro (`No se pudo localizar python.exe…`) en vez del
  críptico "Status 2: File … could not be found".
- **Diagnóstico al inicio del log de pip**:
  `[pudumaps-ai diagnostics]` con `sys.executable`, `sys.prefix`,
  `sys.exec_prefix`, `sys.base_prefix`, `os.__file__`, `resolved_python`.
  Si hay nuevos reportes de bug, traerán este bloque y podremos
  diagnosticar de inmediato qué layout no estamos cubriendo.
- Nueva función `qgis_python_diagnostics()` exportada.
- 2 tests nuevos cubriendo la estrategia `os.__file__` y el contrato
  de `qgis_python_diagnostics()`.

## [0.7.7] — 2026-05-18

### Fixed
- **Hotfix crítico instalador IA en Windows.** En QGIS-Windows
  `sys.executable` apunta al binario GUI (`qgis-bin.exe` o
  `qgis-ltr-bin.exe`), NO a `python.exe`. El instalador 0.7.6 hacía
  `subprocess.run([sys.executable, "-m", "pip", ...])` lo que
  efectivamente **relanzaba QGIS** con los argumentos de pip — y QGIS
  interpretaba el spec `geoai-py==0.10.0` como archivo de proyecto,
  fallando con `Status 2: File … could not be found`.
- `qgis_python_executable()` ahora deriva `python.exe` desde
  `sys.prefix` (que siempre apunta al directorio del Python embebido,
  típicamente `C:\Program Files\QGIS 3.X\apps\PythonXX\`).
- Fallbacks: `python.exe` → `python3.exe` → `Scripts/python.exe` →
  `bin/python.exe` → último recurso `sys.executable` original.
- Linux/macOS sin cambios (`sys.executable` ya es correcto).
- 4 tests nuevos en `test_ai_detection.py` reproduciendo el caso
  Windows con `sys.executable=qgis-ltr-bin.exe` + paths fake.

## [0.7.6] — 2026-05-18

### Added
- **Quinta y última acción del plan IA original**: `download_sentinel.py`
  (`DownloadSentinelTool`):
  - Descarga composición RGB Sentinel-2 sobre bbox + rango de fechas.
  - `input_kind="none"` + `prompt_params` para bbox / fechas / cloud
    cover. Pre-selecciona el extent actual del canvas QGIS
    (reproyectado a EPSG:4326).
  - Llamada geoai aislada en `_run_geoai_download()` (intenta
    `download_sentinel2`, cae a `download_sentinel`).
- **Diálogo** `dialogs/download_sentinel_dialog.py`:
  - Radio buttons: "Usar extent del canvas" vs "Coordenadas custom".
  - 4 `QDoubleSpinBox` para xmin/ymin/xmax/ymax en EPSG:4326.
  - `QDateEdit` con calendario popup para fechas (default últimos 30 días).
  - `QSpinBox` 0-100% para cloud cover (default 20%).
  - Helper `_canvas_bbox_4326()` reproyecta el extent del canvas a
    WGS84 si el proyecto está en otro CRS.
- **Validación defensiva** en la tool antes de tocar la red:
  - bbox inválido (xmin >= xmax / ymin >= ymax).
  - bbox >5° de ancho o alto → rechazado para evitar descargas masivas
    (mensaje sugiere recortar).
  - Fechas invertidas o anteriores al lanzamiento Sentinel-2
    (2015-06-23) → mensaje específico.
  - `cloud_max` fuera de 0-100 → error claro.
- **11 tests nuevos** en `tests/test_ai_tools.py` cubriendo cada
  validación + `AIToolUnavailable` + presencia en registry. También
  un test de cierre que verifica las 5 acciones del plan original.

### Notes — cierre del ciclo IA v0.7.x

Las 5 acciones del plan original están operativas:

| Acción | Versión | Tipo de input | Output |
|---|---|---|---|
| `extract_buildings` | 0.7.2 | Raster RGB | GeoJSON polígonos |
| `extract_water` | 0.7.3 | Raster RGB | GeoJSON polígonos |
| `landcover_classification` | 0.7.4 | Raster RGB | GeoTIFF + leyenda JSON Chile |
| `change_detection` | 0.7.5 | 2 rásters | GeoTIFF máscara binaria |
| `download_sentinel` | 0.7.6 | bbox + fechas | GeoTIFF Sentinel-2 |

Próximo (v0.8.0): **Nivel 2 chilenización** — finetuneo gratis en
Kaggle/Colab de modelos chilenos (`pudumaps/buildings-rural-cl-v1`,
`bosque-nativo-cl-v1`, `tomas-cl-v1`) sobre datasets públicos
(CONAF, MINVU, CBR), publicados en Hugging Face Hub.

Sin `geoai` instalado todo sigue inerte como en versiones anteriores.

## [0.7.5] — 2026-05-18

### Added
- **Cuarta acción IA**: `change_detection.py` (`ChangeDetectionTool`):
  - Compara dos rásters del mismo bbox y distinta fecha, produce
    raster máscara binaria (1 = cambio, 0 = sin cambio).
  - Llamada geoai/torchange aislada en `_run_geoai_change()`. Intenta
    `ChangeDetector`, cae a `detect_changes()` / `change_detection()`
    según versión upstream.
  - Validación de paths (existen, no son iguales) antes de tocar
    geoai, con errores específicos por raster ("antes" / "después").
- **Patrón nuevo del framework** para tools sin capa activa:
  - `AITool.input_kind = "none"` indica al panel que salte la
    validación de la capa activa.
  - `AITool.prompt_params(parent, iface) → Optional[Dict]` permite a
    cualquier tool pedir input vía diálogo propio. Default `{}` deja
    pasar las tools simples (buildings/water/landcover) sin override.
  - `dialogs/ai_panel.py` ejecuta el hook entre validación y task. Si
    devuelve `None` (usuario canceló) la ejecución se aborta limpio.
- **Diálogo de selección** `dialogs/change_detection_dialog.py`:
  - Lista los `QgsRasterLayer` del proyecto con path en disco.
  - Bloquea "Ejecutar" si hay <2 rásters cargados.
  - Pre-selecciona el segundo raster como "después" para acelerar UX.
  - Rechaza la combinación "antes == después".
- 8 tests nuevos en `tests/test_ai_tools.py`:
  - `ChangeDetectionTool` (`input_kind="none"`, output `.tif`,
    validación de params, paths inexistentes, mismo raster, falta de
    geoai, presencia en registry).
  - Default `prompt_params() == {}` para tools simples.

### Notes
- Acción restante: `download_sentinel` (bbox del canvas, sin input
  layer; usa el patrón nuevo). Llega en **0.7.6**.
- El `change_detection_dialog` requiere QGIS runtime y por eso no
  tiene tests unitarios — se cubrirá en el smoke test manual de QA.

## [0.7.4] — 2026-05-18

### Added
- **Tercera acción IA**: `landcover_classification.py`
  (`LandCoverClassificationTool`):
  - Clasifica cada píxel de un raster RGB en categorías de uso de
    suelo (built / forest / water / cropland / shrubland / bare).
  - Produce GeoTIFF categórico + sidecar `<output>.classes.json`
    con la leyenda. La leyenda se re-etiqueta al español + ecorregión
    chilena cuando el bbox cae en Chile.
  - Wrapper aislado en `_run_geoai_landcover()` (intenta
    `LandCoverClassifier`, cae a `classify_landcover()` /
    `predict_landcover()`).
- **Nivel 1 chilenización en código** — nuevo módulo
  `pudumaps_qgis/ai/chile_classes.py`:
  - `ecoregion_for_bbox(bbox)` infiere zona chilena por lat/lon
    (Atacama / Matorral xerófilo / Matorral esclerófilo / Bosque
    templado lluvioso / Bosque siempreverde / Estepa patagónica).
  - `translate_class(name, bbox=...)` mapea nombres genéricos en
    inglés a vocabulario chileno por ecorregión. Sin ML — lookup puro.
  - Fuera de Chile o sin bbox → traducción genérica en español.
- **`AITool.output_suffix`** (default `.geojson`): permite a cada tool
  declarar qué tipo de archivo produce. Buildings/water = `.geojson`,
  landcover = `.tif`. El panel ahora dispatcha
  `QgsVectorLayer`/`QgsRasterLayer` por extensión del output.
- 29 tests nuevos: 20 en `tests/test_chile_classes.py` (ecorregiones
  Santiago/Atacama/Patagonia/Valdivia/Chiloé/fuera de Chile +
  traducciones por zona) + 9 en `tests/test_ai_tools.py`
  (`LandCoverClassificationTool` validación, registro, output_suffix).

### Changed
- `dialogs/ai_panel.py` — `_load_result_as_layer` despacha por
  extensión (`.tif|.tiff|.vrt|.img` → raster, resto → vector).

### Notes
- Acciones restantes: `change_detection` y `download_sentinel` llegan
  en 0.7.5 (rompen el patrón "una sola capa activa de input": una
  necesita selector de 2 rásters, la otra usa el bbox del canvas).
- Sin `geoai` instalado, la nueva acción queda inerte como las otras.

## [0.7.3] — 2026-05-18

### Added
- **Ejecución async** vía `QgsTask`:
  - `pudumaps_qgis/ai/task_runner.py` — `AIToolTask(QgsTask)` envuelve
    `AITool.run()`. Acepta callbacks `on_success` / `on_error` /
    `on_progress`. QGIS gestiona thread, cancelación y la entry del
    panel Tasks.
  - El panel IA ahora dispara la tarea con
    `QgsApplication.taskManager().addTask(task)` en vez de bloquear.
    Aparece toast "en ejecución" y otro al completar.
- **Nueva acción** `extract_water.py` (`ExtractWaterTool`):
  - Wrapper sobre la API de water-body de geoai. Intenta
    `WaterBodyExtractor`, cae a `extract_water()` /
    `extract_water_bodies()` según versión.
  - Mismo contrato que `extract_buildings`: raster ≥3 bandas en disco.
  - Registrada en `_TOOL_CLASSES` después de buildings.
- **Doc Nivel 1 chilenización** (`docs/modelos-chile.md`):
  - Tabla por tool con casos chilenos y cómo rinden hoy (urbanos
    consolidados / históricos / rurales / palafitos / tomas /
    Sentinel vs orto IDE Chile / lagos / ríos andinos / salares).
  - Recomendaciones de input (orto IDE Chile, RGB explícito, recorte).
  - Roadmap v0.8: modelos finetuneados chilenos
    (`pudumaps/buildings-rural-cl-v1`, `bosque-nativo-cl-v1`,
    `tomas-cl-v1`).
- 8 tests nuevos en `tests/test_ai_tools.py` cubriendo
  `ExtractWaterTool` y registro de ambas tools.

### Notes
- Las 3 acciones restantes (`landcover_classification`,
  `change_detection`, `download_sentinel`) llegan en 0.7.4.
- Sin `geoai` instalado, ambas acciones quedan inertes — sigue
  funcionando todo como en 0.7.2.

## [0.7.2] — 2026-05-18

### Added
- **Framework de acciones IA** en `pudumaps_qgis/ai/tools/`:
  - `base.py` — `AITool` abstracto con contrato
    `validate_input(layer) → Optional[str]` y
    `run(raster_path, output_path, params, progress_cb) → str`.
    Helpers `is_available()` / `missing_requirements()` /
    `ensure_available()` para que cada tool declare sus deps.
  - `registry.py` — registro estático `get_tools()` / `get_tool(id)`.
    Agregar una nueva tool = añadir clase a `_TOOL_CLASSES`. No usamos
    descubrimiento dinámico para no pagar costo de importar PyTorch.
  - Excepciones `AIToolError` y `AIToolUnavailable` para distinguir
    fallos recuperables vs. deps faltantes.
- **Primera acción real**: `extract_buildings.py` —
  `ExtractBuildingsTool` envuelve la API de building footprint de
  geoai (intenta `BuildingFootprintExtractor`, cae a
  `extract_buildings()`). Validación: raster con ≥3 bandas y archivo
  en disco. La llamada a geoai está aislada en
  `_run_geoai_buildings()` para que el bump de versión upstream toque
  un solo lugar.
- **Panel lateral** `dialogs/ai_panel.py` (`AIToolsDock`,
  `QDockWidget`):
  - Un botón por tool registrada; deshabilitados si la tool no está
    disponible (con tooltip "Falta instalar: <deps>").
  - Refresh automático tras instalar deps desde el instalador.
  - Resultado se carga como capa vectorial nueva en el proyecto.
- **Entrada de menú** "Panel IA" en `plugin.py` que crea el dock al
  primer click (lazy) y togglea visibilidad en clicks siguientes.
- Tests `tests/test_ai_tools.py` — 17 nuevos cubriendo contrato base,
  registry, validación de input de `ExtractBuildingsTool`,
  `AIToolUnavailable` cuando falta geoai, y rechazo cuando el raster
  no existe.

### Notes
- Las acciones aún corren **síncronas** (bloquean QGIS durante la
  inferencia). Refactor a `QgsTask` viene en 0.7.3 junto con las
  4 acciones restantes (water, landcover, change_detection,
  download_sentinel).
- Sin geoai instalado, el panel y la acción son inertes — el plugin
  sigue funcionando exactamente como 0.7.1.

## [0.7.1] — 2026-05-18

### Added
- Entrada **"Instalar módulo IA…"** en el menú `Pudumaps` y en la
  toolbar, con icono propio (`icons/ai.svg`). Abre el
  `InstallAIDialog` introducido en 0.7.0 — ahora descubrible por el
  usuario sin necesidad de invocarlo desde código.
- `ICON_AI` en `plugin.py` apuntando al nuevo SVG.

### Notes
- Sigue siendo solo infraestructura. Las acciones IA reales (detección
  edificios/agua/landcover/cambios/Sentinel) llegan en 0.7.2.

## [0.7.0] — 2026-05-18

### Added
- Nuevo módulo `pudumaps_qgis.ai` con detección runtime de las
  dependencias opcionales de IA:
  - `is_geoai_available()` / `is_geoagent_available()` vía
    `importlib.util.find_spec` — no levanta el paquete pesado.
  - `geoai_version()` / `geoagent_version()` y los helpers
    `geoai_matches_pin()` / `geoagent_matches_pin()`.
  - Constantes `GEOAI_PINNED_VERSION = "0.10.0"` y
    `GEOAGENT_PINNED_VERSION = "0.4.0"`. Las versiones se bumpean
    manualmente por release del plugin, NUNCA con rango libre, para
    protegernos de bumps rotos o versiones yankeadas upstream.
- `pudumaps_qgis.ai.installer.install_package(...)` — wrapper sobre
  `subprocess.Popen` que invoca `sys.executable -m pip install --user`
  con captura de stdout línea a línea, pin de versión (`==X.Y.Z`),
  extras opcionales, y manejo de timeout. Devuelve `InstallResult`.
- `dialogs/install_ai_dialog.py` — modal Pudumaps con checkboxes para
  cada componente (motor de visión / asistente conversacional),
  prerequisitos (Visual C++ redist en Windows), y `QProgressDialog`
  alimentado por un `QThread` worker para no congelar QGIS.
- Tests `tests/test_ai_detection.py` y `tests/test_ai_installer.py` —
  monkeypatch sobre `importlib` y mock de `subprocess.Popen` para
  validar todo el flujo sin instalar paquetes reales en CI.

### Notes
- Esta release solo prepara la infraestructura. Las acciones IA
  reales (detección de edificios, agua, landcover, change detection,
  descarga Sentinel) llegan en 0.7.1.
- Sin geoai/GeoAgent instalados el plugin sigue funcionando
  exactamente igual que 0.6.0; las features IA quedan latentes.

## [0.6.0] — 2026-05-07

### Security
- Hardening completo según auditoría 2026-05-07 (PR #1). Ver
  `metadata.txt` para detalle de los 8 hallazgos cerrados.

## [0.5.0] — 2026-04-23

### Added
- **Logo oficial Pudumaps** (el pudu con el mapa) integrado como icono
  del plugin en el administrador de QGIS y como header branded en cada
  diálogo del plugin.
- **Iconos SVG específicos por acción** en la toolbar/menú:
  - `settings.svg` — engranaje para Configuración
  - `download.svg` — flecha hacia abajo para Abrir proyecto
  - `upload.svg` — flecha hacia arriba para Subir capa
  - `sync.svg` — flechas circulares para Sincronizar
- `styles.py` — stylesheet QSS con paleta Pudumaps (`#22c55e` verde)
  aplicada a botones primarios, tablas, progress bars y focus rings.
- `ui_helpers.py` — helpers reutilizables para header branded y para
  toast notifications nativas usando `iface.messageBar()`.
- Headers consistentes con logo + título + subtítulo en los 4 diálogos
  principales.

### Changed
- Todos los diálogos (settings, projects, upload, sync) ahora montan
  `apply_pudumaps_style()` y el header branded.
- `metadata.txt` ahora referencia `icons/pudumaps-logo.png` como icono
  principal del plugin (reemplaza el SVG genérico verde).

## [0.4.0] — 2026-04-23

### Added
- **Bidirectional sync** with per-layer conflict detection. The sync
  dialog shows every layer of the project and its current state:
  - `unchanged` — both sides identical (skip)
  - `local_only` — pushable with one click
  - `remote_only` — pullable with one click
  - `conflict` — both sides changed since last sync (user picks which wins)
  - `new_local` — local layer with no remote id yet (uploads as new)
  - `deleted_remote` — layer gone from server (keep local or delete)
- `sync_manager.py` with `canonical_hash()` (SHA-256 of canonical JSON)
  and a pure `classify()` state-machine function.
- `pudumaps/last_hash` custom property persisted on each successful
  pull or push so future syncs have a reference point.
- **Dedup on pull**: if a layer with the same remote `layer_id` already
  exists in the QGIS project, its features are refreshed in place
  instead of creating a duplicate. Solves the two-layers-one-remote
  problem introduced in v0.3 when users pushed then re-opened the project.

### Changed
- "Sincronizar" toolbar action now opens the sync dialog (was a stub).
- Pull stamps `pudumaps/last_hash` on every loaded layer.

## [0.3.0] — 2026-04-23

### Added
- **Upload a QGIS layer to Pudumaps (push)** via two entry points:
  - Right-click on a vector layer in the Layers Panel → *Subir a Pudumaps…*
  - Menu/toolbar action *Subir capa activa a Pudumaps…*
- `UploadLayerDialog`: dropdown of user's projects + *Nuevo…* button to
  create a project inline without leaving QGIS
- `exporter.layer_to_geojson()`: serializes a `QgsVectorLayer` to a
  GeoJSON FeatureCollection with automatic reprojection to EPSG:4326
  when the source CRS is different (PSAD56, UTM19S, etc.)
- Pre-upload validation: 10 MB body cap (matches API limit),
  20,000-feature max (matches `validateGeoJSON` limit)
- Smart dispatch: layers that originated from a Pudumaps pull (detected
  via the `pudumaps/layer_id` custom property) are **updated in place**
  with PATCH instead of duplicating via POST. First-time uploads stamp
  the returned id on the layer so the next upload becomes an update.

### Changed
- Menu/toolbar now has four actions (previously three) — the new
  upload action sits between *Abrir proyecto* and *Sincronizar*.

## [0.2.1] — 2026-04-23

### Fixed
- Polygon/MultiPolygon layers now render correctly. Previously OGR would
  promote single-geometry features to their Multi- variant when reading
  GeoJSON, and the memory layer created with the inferred `Polygon` URI
  would silently reject `MultiPolygon` features on `addFeatures()`,
  resulting in empty-looking layers in QGIS. Now the memory layer uses
  OGR's actual `wkbType` and inherits the CRS from the OGR layer.
- Fallback to OGR-backed layer when the memory provider rejects the
  features anyway (last-resort robustness).

### Added
- Auto-zoom to the combined extent of the loaded group after pull, so
  layers are immediately visible even when they live far from the
  current map viewport (e.g. Los Ríos region while the canvas was
  showing Europe).

## [0.2.0] — 2026-04-23

### Added
- **Open a Pudumaps project as QGIS layers (pull)**
- Projects dialog with list of all your projects (name, description, created)
- Automatic layer group `Pudumaps: <project name>` in the layer tree
- Basic default styling (green points/lines/polygons) applied to each loaded layer
- Progress bar during multi-layer pull
- Remote project/layer ids stamped as custom properties (`pudumaps/layer_id`,
  `pudumaps/project_id`) for future push/sync
- Per-layer error isolation — one failed layer doesn't abort the whole import

### Changed
- "Abrir proyecto" toolbar action now opens the projects dialog instead of
  the "coming soon" placeholder

## [0.1.0] — 2026-04-23

### Added
- Initial plugin skeleton with QGIS 3.22+ LTR support
- Settings dialog with encrypted API key storage (`QgsAuthManager`) and
  plain `QSettings` fallback when no master password is set
- `PudumapsClient` HTTP wrapper (CRUD for projects and layers) with
  automatic retry on 429 respecting `X-RateLimit-Reset`
- Connection test against `GET /v1/projects`
- Toolbar + menu entries: Configuración, Abrir proyecto, Sincronizar
  (last two stubbed — coming in v0.2 and v0.4)
- Build script `scripts/build.sh` producing an installable zip
