# Hallazgo · WP-RD1 multiactivo (EXPLORATORIO) — positivo APARENTE, confundido por carga

- **Autor:** A · **Fecha:** 2026-10-06 · **EXPLORATORIO**, no confirmatorio.
- **Reproducción:** `code/applications/experiments/_wprd1_multi/wprd1_multi_explor.py`,
  `results/reports/wprd1_multi_explor.json`.

## Qué salió
Cesta 1/N de 6 commodities (panel extendido), evento = caída de cartera a 10
sesiones bajo el peor decil de FIT purgado. En el punto nominal FA=15/año:

| Política | Recall | FA/año **real** |
|---|---|---|
| vol_cartera | 1,000 | **20,4** |
| combinación | 0,857 | **18,7** |
| régimen_brent | 0,821 | 12,9 |
| calendario | 0,643 | 13,8 |
| superv_brent | 0,429 | 11,6 |

Contraste bruto: combinación − calendario = +0,214, IC95 [0,036, 0,321].

## Por qué NO es un positivo
El contraste **no está a igual tasa de falsas alarmas**: combinación 18,7 vs
calendario 13,8; vol_cartera logra recall 1,0 solo porque dispara a 20,4 FA/año.
Es el **mismo confound de carga desigual** que invalidó el Gate 1 v2 (challenge de
B). Más alertas → más recall, trivialmente. Sin la comparación **emparejada por
FA** (interpolación de la curva, como en v3) este +0,214 **no acredita señal**.

## Lectura honesta
- **Inconcluso, probablemente negativo.** En Brent, el positivo aparente de v2
  desapareció al emparejar FA (v3). Es esperable que aquí pase lo mismo.
- `superv_brent` 0,429 es **la peor** señal: la supervivencia sigue sin aportar.
- Representación del WTI negativo (suelo −95 %) es provisional; afecta al evento.

## Qué falta (confirmatorio, tras freeze de B)
Emparejar FA por interpolación; agregación de señales por contribución al riesgo
**train-only**; representación definitiva del WTI negativo; nulo con política
propia. Hasta eso, **sin claims** de valor multiactivo, capital, alpha ni Sharpe.
