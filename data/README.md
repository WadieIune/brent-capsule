# /data — Datos de entrada (bundle BRENT)

En Code Ocean este directorio se monta como **`/data`** en modo solo lectura. El
código lo lee mediante `config_codeocean.json` (`series_bundle.dataset_dir = "/data"`).

## Ficheros requeridos

Coloca aquí los siguientes ficheros (generados por `SeriesDownloader_2_features.py`):

```
/data
├── dataset_wide_with_target.csv      # precios + target (BRENT, BRENT_fwd_logret_1, ...)
├── dataset_wide_features_zscore.csv  # features en z-score (canal multivariante)
├── feature_means.csv                 # medias de estandarización
├── feature_stds.csv                  # desviaciones de estandarización
├── X_train.npy                       # split precomputado (opcional pero recomendado)
├── y_train.npy
├── X_test.npy
└── y_test.npy
```

## Serie de precios del Brent (FRED) — `brent_fred_daily.csv`

Serie diaria del **Brent spot** (FRED `DCOILBRENTEU`, la fuente original del
proyecto), columnas `date,BRENT`, del 1987-05-20 al 2026-06-29 (9.922 sesiones).

Es la serie sobre la que se construyen las figuras chartistas del documento
(`docs/CCN_BRENT_canal`) y, en particular, **cubre el trimestre out-of-sample
abril–junio 2026** que no está en el `bundle` (este termina el 2026-03-06). Se usa
FRED como fuente única (train+test) para evitar mezcla de *vintages*.

Reproduce el detector de canal e infiere sobre ella directamente:

```bash
python code/channel_detector.py predict \
    --prices data/brent_fred_daily.csv --out preds.csv
```

Para actualizarla desde el origen:
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU`
(columnas `observation_date,DCOILBRENTEU` → renombrar a `date,BRENT`).

## Qué dato usa cada pata del proyecto

**La cápsula es autocontenida**: los tres experimentos leen exclusivamente
ficheros de este directorio, sin descargas en tiempo de ejecución.

| Pata | Código | Fichero de entrada | Series usadas |
|---|---|---|---|
| 1ª · Detección del canal | `code/channel_detector.py` | `dataset_wide_with_target.csv` + z-score + `.npy` | BRENT + 180 features |
| 2ª · Supervivencia | `code/part2_channel_survival/` | `brent_fred_daily.csv` | BRENT (FRED, 1987–2026) |
| 3ª · Aplicaciones a riesgo | `code/applications/` | `brent_fred_daily.csv` (1 activo) y **`dataset_wide_with_target.csv`** (cartera) | BRENT, WTI, GOLD, SILVER, COPPER, NATGAS |

La cartera multi-commodity de `portfolio_var` **no incorpora datos nuevos**:
toma seis columnas de precios que ya están en `dataset_wide_with_target.csv`
(7.004 filas, 2007-01-02 → 2026-03-06; 6.795 sesiones con las seis series
simultáneamente disponibles). Ese fichero forma parte del *bundle* original de la
cápsula desde la primera versión, por lo que un revisor de la revista reproduce
las tres patas sin acceso a red.

**Resolución de rutas en Code Ocean.** Los módulos localizan el dato subiendo
directorios hasta encontrar `data/`, de modo que funcionan tanto en el repositorio
(`<repo>/data/`) como en el montaje de la cápsula (`/data`, con el código en
`/code`). Verificado sobre un layout `/code`+`/data`+`/results`.

## Cómo cargarlos en Code Ocean

1. En la cápsula, pestaña **Data** → *Add data* y sube los ficheros anteriores, o
2. Adjunta un *Data Asset* existente que contenga esos ficheros.

> Los ficheros están incluidos en el repositorio del proyecto bajo
> `CNN_BRENT_v2/inputs_iniciales/`. Para una reproducción local, copia ese
> contenido a la carpeta `data/` de la cápsula (ver `REPRODUCING.md`).
