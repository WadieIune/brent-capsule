# Reproducing these results

Esta cápsula sigue el formato estándar de **Code Ocean**:

```
.
├── REPRODUCING.md          # este archivo
├── code/                   # código + script de arranque (run)
│   ├── run                 # punto de entrada que ejecuta Code Ocean
│   ├── run.sh              # alias
│   ├── config_codeocean.json   # config CPU reproducible (JSON)
│   ├── config_codeocean.yaml   # misma config en YAML (recomendado)
│   ├── config_gpu.yaml         # config para ejecución en GPU
│   ├── LICENSE
│   └── brent_pattern_system/
├── data/                   # datos de entrada (montados en /data, solo lectura)
├── environment/            # Dockerfile (receta del entorno)
│   ├── Dockerfile
│   └── requirements.txt
├── metadata/
│   └── metadata.yml        # descriptor de la CÁPSULA (no del experimento)
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

## Ejecución en GPU

La configuración se selecciona con la variable de entorno `CONFIG` (por defecto
se usa la CPU reproducible). Para el régimen largo en GPU:

```bash
CONFIG=/code/config_gpu.yaml /code/run
# o directamente:
python -m brent_pattern_system.train_torch --config code/config_gpu.yaml
```

`config_gpu.yaml` activa AMP (mixed precision), cuDNN benchmark, más épocas,
`image_size` 160, walk-forward de 5 folds y `pretrained_backbone: true`.

## Salidas esperadas (`/results`)

- **`reports/brent_resultados.xlsx`** — libro Excel para presentación académica
  con hojas: `00_Resumen`, `01_Configuracion` (todos los parámetros del
  experimento), `02_Entorno`, `03_Clasificacion`, `04_Clasif_PorClase`,
  `05_MatrizConfusion`, `06_Regresion`, `07_Backtest`, `08_Backtest_Robustez`
  (DSR/PBO), `09_SharpePorFold`, `10_Folds`, `11_Predicciones_OOS`.
- **`reports/run_manifest.json`** — registro de reproducibilidad: configuración
  resuelta + entorno (versiones, commit de git, timestamp, semilla).
- `reports/torch_walkforward_summary.json` — métricas de clasificación balanceadas
  (balanced accuracy, macro-F1, matriz de confusión), regresión y **backtest**
  (Sharpe, PSR, **Deflated Sharpe Ratio**, **PBO/CSCV**).
- `reports/torch_oos_predictions.csv` — predicciones out-of-sample por fold.
- `models/` — un modelo por fold.
- `metadata/` — window_table, metadatos del dataset y plantillas de outliers.

> Si `openpyxl` no estuviera instalado, el Excel se degrada automáticamente a
> `reports/excel_csv_fallback/*.csv` (una hoja por CSV) sin abortar el run.

## Configuración vs. metadatos (separación limpia)

Para evitar duplicidad y ambigüedad se mantiene una separación de
responsabilidades:

- **`metadata/metadata.yml`** — descriptor de la **cápsula** Code Ocean (título,
  autores, descripción, tags, licencia). Sigue el esquema de Code Ocean; **no**
  contiene hiperparámetros del experimento.
- **`code/config_codeocean.{json,yaml}` y `code/config_gpu.yaml`** — configuración
  del **experimento** (única fuente de verdad de todo lo asumido/parametrizado).
- **`results/run_manifest.json` + hoja `01_Configuracion` del Excel** — *snapshot*
  de la configuración efectivamente ejecutada junto al entorno; es el registro
  que una revista puede usar para **validar la reproducibilidad**.

## Notas de reproducibilidad

- Semillas fijadas (`training.seed = 42`, `PYTHONHASHSEED=0`).
- Ejecución en **CPU** y `pretrained_backbone=false` para evitar descargas de red
  (entorno offline determinista). La metodología es idéntica a la configuración GPU
  (`example_config_gpu.json`); solo cambian tamaño de imagen y épocas para que la
  reproducción termine en tiempo razonable en CPU.
- Para el experimento completo (GPU, más épocas, `image_size` mayor), usa
  `code/config_gpu.yaml`.
- Todos los parámetros del experimento quedan volcados en el Excel
  (`01_Configuracion`) y en `run_manifest.json`, de modo que cualquier resultado
  es trazable a la configuración exacta que lo produjo.

## Referencias metodológicas

Ver `code/brent_pattern_system/` y el documento `BIBLIOGRAFIA.md` del repositorio
principal (López de Prado 2018; Bailey & López de Prado 2012/2014 para PSR/DSR;
Bailey et al. 2014/2017 para PBO/CSCV).
