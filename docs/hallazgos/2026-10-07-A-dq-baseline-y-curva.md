# Hallazgo · (b) baseline cross-asset para la CNN de B · (a) control de forma de curva

- **Autor:** A · **Fecha:** 2026-10-07.

## (b) Baseline cross-asset con el protocolo EXACTO de la CNN 1D supervisada de B
`dq_cross_asset_baseline.py` — universo de 6 commodities, umbral calibrado en
VALIDACIÓN (no en test), recall en test, FP objetivo 5 %. **Es el número que la
CNN supervisada debe BATIR.**

| Objetivo | decoupling | stale | reversible_jump | FP test real |
|---|---|---|---|---|
| GOLD | 0,975 | 1,00 | 0,892 | 0,14 |
| SILVER | 0,986 | 1,00 | 0,897 | 0,08 |
| WTI | 0,745 | 1,00 | 0,583 | 0,02 |
| BRENT | 0,691 | 1,00 | 0,452 | 0,00 |
| COPPER | 0,350 | 1,00 | 0,284 | 0,04 |
| NATGAS | 0,062 | 1,00 | 0,064 | 0,05 |
| **mediana** | **0,718** | **1,00** | **0,517** | — |

Lectura: stale = control universal (1,0). decoupling depende del par (GOLD/SILVER
~0,98; NATGAS 0,06). La CNN tiene margen real **solo donde el cross-asset es débil
(COPPER, NATGAS)**; donde es fuerte, el listón es ~0,98. Nota: el FP realizado en
test se desvía del objetivo (umbral de val no transfiere perfecto); se reporta.

## (a) Control de FORMA de curva — NO demostrado con 3 nodos CMT
`dq_curve_shape.py` — curva [DGS2, DGS10, DGS30], ajuste lineal, residuo cross-tenor.

| Defecto | 3σ por nodo | forma cross-tenor |
|---|---|---|
| kink (quote grande) | **1,00** | 0,45 |
| inversión (quote grande) | **1,00** | 0,95 |
| nodo estancado (8 d) | 0,00 | 0,025 |

**Veredicto honesto: el control de forma NO bate a los controles por nodo con este
dato.** Los quotes grandes los caza el 3σ; el nodo estancado lo pierden ambos
(3σ por retorno 0; forma porque la variación normal del *butterfly* 2s10s30s supera
la distorsión de 8 días) y lo cazaría el **TRIM a 20 días**. Con solo **3 nodos
CMT muy correlacionados** no hay margen para la forma.

**Conclusión:** la detección de forma para curvas es una extensión **prometedora
pero NO demostrada** con el panel actual; exige una curva real multi-tenor (1m–30y)
y construcción ZC (bootstrapping, convenciones — caveat de B). No se vende como
resultado; queda como línea de trabajo con requisitos claros.
