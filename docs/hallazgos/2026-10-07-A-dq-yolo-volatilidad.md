# Hallazgo · localización de spikes con CNN 1D y YOLO

- **Autor:** A · **Fecha:** 2026-10-07 · exploratorio, pendiente de challenge.
- **Código:** `code/applications/experiments/dq_yolo_volatility_spikes.py`.
- **Reporte/pesos:** `results/reports/dq_yolo_volatility/`.
- **Tarea:** localizar errores puntuales en ventanas de log-volatilidad
  mean-reverting; no clasificar dirección de canal.

## Protocolo

Se generaron ventanas sintéticas AR(1) de longitud 128 con parámetro de
reversión y volatilidad de innovación aleatorios. La corrupción es una
perturbación aislada de 1, 2, 3, 4, 5 u 8 desviaciones estacionarias. Train usa
1.200 ventanas limpias/corruptas con amplitudes 2–6σ; validation, 400 ventanas;
test, 250 ventanas limpias más 250 por amplitud. Un YOLO11n preentrenado en COCO
se ajustó 4 épocas (mAP50 0,995 en validation al mejor checkpoint); la CNN 1D
numérica, 15 épocas. Augmentations geométricas/color se desactivaron para no
alterar tiempo ni escala. Los umbrales de CNN, YOLO y máximo del 3σ causal se
fijaron usando solo ventanas limpias de validation al 2% FPR.

En test, la localización cuenta como acierto si el máximo score o centro de caja
queda a ±3 sesiones del spike. El 3σ fijo también se reporta como referencia,
pero su FPR por ventana no está emparejada con los modelos.

## Resultado preliminar

| Amplitud | CNN 1D | YOLO | 3σ recalibrado (2% val FPR) |
|---:|---:|---:|---:|
| 1σ | 0,248 | 0,264 | 0,156 |
| 2σ | **0,976** | 0,928 | 0,776 |
| 3σ | **1,000** | 0,972 | 0,848 |
| 4σ | **1,000** | 0,984 | 0,848 |
| 5σ | **1,000** | 0,960 | 0,848 |
| 8σ | **1,000** | 0,960 | 0,848 |

La FPR limpia OOS fue **4,0% CNN**, **4,8% YOLO** y **0,8% para 3σ
recalibrado**; el 3σ literal de umbral 3 tuvo FPR **46% por ventana**. Por
tanto, la señal de recall favorece a la CNN a partir de 2σ, pero CNN/YOLO no
mantienen el objetivo OOS del 2% en esta muestra (250 ventanas); esto todavía
no es victoria operativa a carga de alarmas igualada. YOLO localiza el objeto,
pero no mejora a la CNN numérica aquí.

## Lectura y siguiente gate

Este resultado indica que la CNN 1D supervisada puede aprender la morfología de
un spike breve que el control 3σ calibrado pierde. También es coherente con la
CNN productiva EfficientNet que detecta canales: la arquitectura tiene capacidad
útil cuando objetivo, representación y etiquetas encajan. Pero su AUC de canal
no valida este detector DQ, y el test actual es enteramente sintético.

Antes de reclamar mejora: repetir 3–5 semillas, ampliar validation/test y ajustar
umbrales de forma conservadora para cumplir FPR OOS; probar con defectos reales
fechados, y comparar también contra Hampel/rolling MAD/3σ de innovaciones con la
misma carga de revisión. Para curvas, el residuo Nelson-Siegel y CNN supervisada
son otro problema y otro benchmark. YOLO queda como localizador explicable, no
como modelo primario mientras no añada recall o reduzca tiempo de revisión.
