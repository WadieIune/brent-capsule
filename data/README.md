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

## Cómo cargarlos en Code Ocean

1. En la cápsula, pestaña **Data** → *Add data* y sube los ficheros anteriores, o
2. Adjunta un *Data Asset* existente que contenga esos ficheros.

> Los ficheros están incluidos en el repositorio del proyecto bajo
> `CNN_BRENT_v2/inputs_iniciales/`. Para una reproducción local, copia ese
> contenido a la carpeta `data/` de la cápsula (ver `REPRODUCING.md`).
