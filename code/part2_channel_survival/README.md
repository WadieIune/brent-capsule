# part2_channel_survival — Supervivencia del canal (2ª pata)

Módulo **independiente** que extiende el detector estático de canal
(`../channel_detector.py`) hacia el modelado **dinámico** del canal
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

Q4 (rentabilidad) **sí se contrasta**, en `validation.py --backtest`: es la única
forma de comprobar que la 2ª pata no contradice el resultado de eficiencia de la
1ª (DSR≈0). El veredicto se resume abajo.

## Resultados validados (walk-forward, serie FRED 1987–2026)

Ejecutar `python validation.py` reproduce esta tabla:

| Bloque | Resultado | Baseline | Lectura |
|---|---|---|---|
| **Q2 · discriminación** | XGB-AFT C-index **0.664 ± 0.007** (RSF 0.624, Cox 0.558) | 0.500 | La vida del canal **es** ordenable: se sabe qué canales son frágiles |
| **Q2 · calibración** | MAE: KM **0.019** < Cox 0.034 < XGB-AFT 0.042 | KM marginal | Las covariables aportan *ranking*, no mejor probabilidad absoluta |
| **Q3 · dirección** | AUC **0.766 ± 0.050** | 0.500 | La banda de salida es predecible |
| **Q4 · economía** | Sharpe **−0.48**, retorno **−78%** vs buy&hold +88%, **DSR 0.014**, PBO 0.35 | buy&hold | **Sin edge** |

**Hallazgo central de la 2ª pata:** se acierta el **67.8%** de las direcciones de
ruptura y aun así la estrategia **pierde dinero**. Predecir *por qué banda* sale
el precio no es predecir el beneficio: la asimetría de pagos anula el acierto
direccional. Es el mismo veredicto que la 1ª pata (DSR≈0) obtenido por una vía
independiente, y por eso **refuerza** la coherencia del trabajo en lugar de
contradecirlo.

Implicación de diseño para las aplicaciones: el modelo se usa como **ordenador de
fragilidad** (qué canal aguanta menos) y el **nivel absoluto** de `P(T>k)` se
ancla en Kaplan-Meier, que es lo mejor calibrado.

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

`channel_survival.py` hace la corrida básica (split temporal único) y
`validation.py` la **validación robusta**, que es la que sustenta las cifras del
paper:

| Bloque (`validation.py`) | Qué comprueba |
|---|---|
| `--sensitivity` | ¿Dependen las conclusiones de la definición de ruptura? Rejilla `band_mult × tol_atr × confirm` |
| `--walkforward` | C-index (Cox/RSF/XGB-AFT) y AUC de Q3 en **6 orígenes temporales** expansivos |
| `--calibration` | ¿La `P(T>k)` predicha coincide con la Kaplan-Meier observada? |
| `--backtest` | ¿Hay valor económico? Sharpe/PSR/**DSR**/**PBO** vs buy&hold y costes |

Dos decisiones metodológicas que corrigen la versión inicial:

1. **Censura administrativa** (`administrative_censoring`): un episodio detectado
   antes del corte pero que rompe después usaría información futura (su duración
   y su dirección). Ahora se censura en el corte: solo se sabe que sobrevivió
   hasta ahí. Sin esto hay **fuga temporal** en train.
2. **`CONFIRM = 2`** (antes 1): con una sola sesión fuera de banda, el **23%** de
   los episodios "rompían" el mismo día de la detección — ruido de
   microestructura, no cambio de régimen. Con dos sesiones consecutivas
   desaparecen (0%) y la duración mediana pasa de 5 a **10** sesiones. La tabla
   de sensibilidad completa queda en el Excel para que el lector lo juzgue.

Métricas: **C-index** de Harrell + **Integrated Brier Score** (Q2);
**AUC/F1/precision/recall** vs **tasa base** (Q1/Q3); **Sharpe/PSR/DSR/PBO**
(Q4), con las mismas referencias que la 1ª pata (López de Prado; Bailey et al.).

## Instalación y ejecución (máquina GPU)

```bash
cd code/part2_channel_survival
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# XGBoost en GPU (Cox/RSF en CPU); dataset por defecto = <repo>/data/brent_fred_daily.csv
python channel_survival.py --cutoff 2020-08-20 --gpu

# o CPU puro:
python channel_survival.py --cutoff 2020-08-20

# atajo:
bash run_gpu.sh

# validación robusta (walk-forward + calibración + backtest + sensibilidad):
python validation.py --cutoff 2020-08-20
python validation.py --backtest          # solo un bloque
```

## Salidas (`outputs/`, o `OUT_DIR`)

- `channel_survival.json` — parámetros + métricas de Q1/Q2/Q3.
- `channel_survival_resultados.xlsx` — Excel multi-hoja (resumen, episodios,
  supervivencia, curvas `P(T>k)`, formación, dirección).
- `channel_survival_episodes.csv` — tabla de episodios con features.
- `validation.json` — **manifiesto de harness** (ARF: task/experiment id,
  timestamp, inputs, config, seed, comando, entorno, métricas, decisión).
- `channel_survival_validacion.xlsx` — sensibilidad, walk-forward, calibración y
  backtest en hojas separadas.

## Caveats

- La **dirección de ruptura (Q3)** alcanza AUC 0.77 sin contradecir la
  no-predecibilidad direccional del proyecto: el backtest muestra que ese acierto
  **no es monetizable** (DSR 0.014). Ambas cosas conviven porque la banda de
  salida y el beneficio no son la misma variable.
- La geometría se congela en la detección; el re-ajuste dinámico es ampliación futura.
- ATR es un proxy close-only (FRED da solo cierre); tolerancia aproximada pero
  consistente train/test.
- `patterns_min.py` es copia fiel del etiquetador del proyecto; si este cambia,
  sincronizar el fichero.
