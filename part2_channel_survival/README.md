# part2_channel_survival — Supervivencia del canal (2ª pata)

Módulo **independiente** que extiende el detector estático de canal
(`../code/channel_detector.py`) hacia el modelado **dinámico** del canal
("túnel"): una vez detectada la geometría, estimamos su **persistencia**, su
**formación futura** y la **dirección de ruptura**.

Es **autocontenido**: no importa el paquete `brent_pattern_system` ni torch; el
etiquetador débil se vendoriza en `patterns_min.py`. Solo necesita la serie de
precios del Brent, así que se entrena en cualquier máquina (incluida **GPU**) sin
tocar el resto del proyecto.

## Preguntas que responde

| Id | Pregunta | Formulación | Salida |
|----|----------|-------------|--------|
| **Q2** | ¿Cuánto vivirá el canal? | Análisis de supervivencia del episodio | Curva `P(T>5/10/20)` |
| **Q1** | ¿Se formará un canal en los próximos N días? | Clasificación binaria en días sin canal | `P(canal en t+1..t+N)` |
| **Q3** | ¿Por dónde romperá? | Clasificación alcista/bajista en episodios que rompen | `P(ruptura alcista)` |

Q4 (rentabilidad) queda **fuera** por coherencia con el resultado de eficiencia
documentado en `../docs/PROJECT_LEDGER.md` (backtest chartista DSR≈0, sin edge).

## Definición de episodio y ruptura

1. Ventana de 32 días; se confirma canal con el etiquetador débil (`patterns_min`).
2. En la detección se **congela la geometría**: línea central por regresión +
   bandas paralelas a `±BAND_MULT·σ_resid`.
3. Se proyecta hacia delante; hay **ruptura** cuando el cierre supera la banda
   proyectada más `TOL_ATR·ATR` durante `CONFIRM` sesiones (tolerancia anti-ruido).
4. `duration = T` = sesiones hasta la ruptura; episodios vivos al final =
   **censurados por la derecha** (`event=0`). Los episodios son **no solapados**.

## Modelos

- **Kaplan–Meier** — baseline marginal (el "base rate" de esta pata).
- **Cox Proportional Hazards** (`lifelines`, CPU).
- **Random Survival Forest** (`scikit-survival`, CPU).
- **XGBoost-AFT** (`xgboost`, objetivo `survival:aft`, **GPU** con `--gpu`).

> Nota GPU: solo **XGBoost** usa CUDA. Cox y RSF corren en CPU (así son las
> librerías). Con `--gpu` se pasa `device="cuda"` a los estimadores XGBoost.

## Features (geométricas/estadísticas)

`dir_asc, slope_norm, r2, resid_norm, band_width, atr_norm, vol20, last_ret,
accel, n_turn, pos_in_channel`. El embedding del backbone CNN es ampliación futura.

## Evaluación

- **Split temporal** (train ≤ `cutoff` < test).
- **C-index** de Harrell + **Integrated Brier Score** (Q2).
- **AUC/F1/precision/recall/accuracy** vs **tasa base** (Q1/Q3).

## Instalación y ejecución (máquina GPU)

```bash
cd part2_channel_survival
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# XGBoost en GPU (Cox/RSF en CPU); dataset por defecto = ../data/brent_fred_daily.csv
python channel_survival.py --cutoff 2020-08-20 --gpu

# o CPU puro:
python channel_survival.py --cutoff 2020-08-20

# atajo:
bash run_gpu.sh
```

## Salidas (`outputs/`, o `OUT_DIR`)

- `channel_survival.json` — parámetros + métricas de Q1/Q2/Q3.
- `channel_survival_resultados.xlsx` — Excel multi-hoja (resumen, episodios,
  supervivencia, curvas `P(T>k)`, formación, dirección).
- `channel_survival_episodes.csv` — tabla de episodios con features.

## Caveats

- La **dirección de ruptura (Q3)** puede chocar con la no-predecibilidad
  direccional ya documentada; se reporta como hipótesis contrastada (AUC vs base),
  no como afirmación de edge.
- La geometría se congela en la detección; el re-ajuste dinámico es ampliación futura.
- ATR es un proxy close-only (FRED da solo cierre); tolerancia aproximada pero
  consistente train/test.
- `patterns_min.py` es copia fiel del etiquetador del proyecto; si este cambia,
  sincronizar el fichero.
