# Reproducing these results

Esta cápsula sigue el formato estándar de **Code Ocean**:

```
.
├── REPRODUCING.md          # este archivo
├── code/                   # código + script de arranque (run)
│   ├── run                 # punto de entrada que ejecuta Code Ocean
│   ├── run.sh              # alias
│   ├── config_codeocean.json
│   ├── LICENSE
│   └── brent_pattern_system/
├── data/                   # datos de entrada (montados en /data, solo lectura)
├── environment/            # Dockerfile (receta del entorno)
│   ├── Dockerfile
│   └── requirements.txt
├── metadata/
│   └── metadata.yml
└── results/                # salidas (se escriben en /results)
```

## Opción A — En Code Ocean (recomendado)

1. Importa este repositorio como **Compute Capsule** (o sube el contenido de
   `code/`, `environment/`, `metadata/`).
2. En la pestaña **Data**, sube los ficheros indicados en `data/README.md` (o
   adjunta el data asset correspondiente). Quedan montados en `/data`.
3. Pulsa **Reproducible Run**. Code Ocean ejecuta `/code/run` y deposita las
   salidas en `/results`.

## Opción B — Local con Docker

Requisitos: Docker.

```bash
# 1) Construir la imagen del entorno
docker build -t brent-capsule ./environment

# 2) Ejecutar montando data (lectura) y results (escritura)
docker run --rm \
  -v "$(pwd)/code":/code \
  -v "$(pwd)/data":/data:ro \
  -v "$(pwd)/results":/results \
  brent-capsule \
  /code/run
```

En Windows (PowerShell), sustituye `$(pwd)` por `${PWD}`.

## Opción C — Local sin Docker

Requisitos: Python 3.11.

```bash
pip install torch==2.2.2 torchvision==0.17.2 --index-url https://download.pytorch.org/whl/cpu
pip install -r environment/requirements.txt

# Ajusta las rutas /data y /results del config o crea enlaces equivalentes:
python -m brent_pattern_system.train_torch --config code/config_codeocean.json
```

(En este caso edita `code/config_codeocean.json` para que `dataset_dir` y los
`*_dir` de salida apunten a carpetas locales en lugar de `/data` y `/results`.)

## Salidas esperadas (`/results`)

- `reports/torch_walkforward_summary.json` — métricas de clasificación balanceadas
  (balanced accuracy, macro-F1, matriz de confusión), regresión y **backtest**
  (Sharpe, PSR, **Deflated Sharpe Ratio**, **PBO/CSCV**).
- `reports/torch_oos_predictions.csv` — predicciones out-of-sample por fold.
- `models/` — un modelo por fold.
- `metadata/` — window_table, metadatos del dataset y plantillas de outliers.

## Notas de reproducibilidad

- Semillas fijadas (`training.seed = 42`, `PYTHONHASHSEED=0`).
- Ejecución en **CPU** y `pretrained_backbone=false` para evitar descargas de red
  (entorno offline determinista). La metodología es idéntica a la configuración GPU
  (`example_config_gpu.json`); solo cambian tamaño de imagen y épocas para que la
  reproducción termine en tiempo razonable en CPU.
- Para el experimento completo (GPU, más épocas, `image_size` mayor), usa
  `example_config_gpu.json` del repositorio principal.

## Referencias metodológicas

Ver `code/brent_pattern_system/` y el documento `BIBLIOGRAFIA.md` del repositorio
principal (López de Prado 2018; Bailey & López de Prado 2012/2014 para PSR/DSR;
Bailey et al. 2014/2017 para PBO/CSCV).
