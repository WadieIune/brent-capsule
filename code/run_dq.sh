#!/usr/bin/env bash
# Pipeline de Data Quality — cápsula Code Ocean.
#
# Reproduce la línea DQ completa de extremo a extremo: detección por
# representación, gate conforme, diagnóstico de distribución, figuras y
# entregables (Excel + Word). Lee de /data y escribe en /results.
#
# El orden importa: `dq_representation_stack` publica los recalls por familia
# que consumen la figura de pipeline y los entregables. Esos pasos NO
# recalculan la detección, solo leen el JSON, de modo que no pueden divergir.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
EXP="applications/experiments"
PANEL="${PANEL:-${ROOT}/data/panel_extendido_2026-09-09.csv}"
# En la cápsula `python` está en el PATH de la imagen; en local se apunta
# al intérprete del venv con  PYTHON=../.venv/bin/python ./run_dq.sh
PY="${PYTHON:-python}"

echo "=================================================================="
echo " Pipeline de Data Quality — gate de dos capas"
echo " Panel: ${PANEL}"
echo "=================================================================="
"${PY}" --version
"${PY}" - <<'PYEOF'
import numpy, pandas, torch, xgboost, seaborn
print(f"numpy {numpy.__version__} | pandas {pandas.__version__} | "
      f"torch {torch.__version__} | xgboost {xgboost.__version__} | "
      f"seaborn {seaborn.__version__}")
print("CUDA disponible:", torch.cuda.is_available())
PYEOF

step () {
  echo "------------------------------------------------------------------"
  echo ">> $1"
  shift
  "${PY}" "$@"
}

# 1-3 · Detección: cada experimento publica su propio summary.json.
step "CNN 1D supervisada frente a controles baratos" \
     "${EXP}/dq_cnn1d_supervised.py" --panel "${PANEL}"
step "Gate conforme-adaptativo y familias no vistas" \
     "${EXP}/dq_conformal_gate.py" --panel "${PANEL}"
step "Pérdida de precisión: control de retícula sobre precios" \
     "${EXP}/dq_quantize_price_grid.py" --panel "${PANEL}"
step "El canal como tercera representación" \
     "${EXP}/dq_channel_representation.py" --panel "${PANEL}"

# 4 · Pila de las cuatro representaciones + combinador. Produce los recalls
#     por familia que consumen los dos pasos siguientes.
step "Vintage + XGBoost combinador (pila de 4 representaciones)" \
     "${EXP}/dq_representation_stack.py" --panel "${PANEL}"

# 5-6 · Diagnóstico y figuras.
step "Distribución de rendimientos frente a la normal" \
     "${EXP}/dq_return_distribution.py" --panel "${PANEL}"
step "Figura de cierre: pipeline Gate A / Gate B" \
     "${EXP}/dq_pipeline_figure.py"

# 7 · Entregables. No recalculan nada: leen los JSON publicados arriba.
step "Entregables para Risk Director (Excel + Word)" \
     "${EXP}/dq_deliverables.py"

echo "------------------------------------------------------------------"
echo "Resultados en results/reports :"
ls -1 "${ROOT}/results/reports" 2>/dev/null || true
echo
echo "Entregables:"
ls -1 "${ROOT}/results/reports/dq_entregables" 2>/dev/null || true
echo "Pipeline DQ completado."
