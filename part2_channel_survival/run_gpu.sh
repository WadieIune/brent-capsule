#!/usr/bin/env bash
# part2_channel_survival — atajo de entrenamiento en GPU.
# Crea (si no existe) un venv local, instala dependencias y ejecuta el módulo con
# XGBoost en GPU. Cox y RSF corren en CPU (así son las librerías).
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"
CUTOFF="${CUTOFF:-2020-08-20}"

if [ ! -d "$VENV" ]; then
  echo "[run_gpu] creando venv en $VENV"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "[run_gpu] instalando dependencias"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "[run_gpu] verificando GPU de XGBoost"
python - <<'PY'
try:
    import xgboost as xgb
    print("xgboost", xgb.__version__)
except Exception as e:
    print("xgboost no disponible:", e)
PY

echo "[run_gpu] ejecutando (cutoff=$CUTOFF, --gpu)"
python channel_survival.py --cutoff "$CUTOFF" --gpu

echo "[run_gpu] hecho. Salidas en outputs/"
