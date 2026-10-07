# Hallazgo · DQ-IA gate barato — dónde se bate a 3σ (y dónde se justifica la CNN)

- **Autor:** A · **Fecha:** 2026-10-06 · nuevo foco DQ (instrucción MASTER).
- **Reproducción:** `code/applications/experiments/dq_ia_gate.py`, `results/reports/dq_ia_gate.json`.
- **Ground truth por inyección** (aquí SÍ hay verdad conocida); FP emparejada al 1 %.

## Recall por familia (BRENT + pares, FP=1 %)
| Familia | 3σ (benchmark) | TRIM repetidos | cross-asset lineal |
|---|---|---|---|
| stale (racha estancada) | **0,00** | **1,00** | 0,04 |
| repetidos ≥20 (P&L mensual) | **0,00** | **1,00** | 0,02 |
| salto imposible | 0,95 | 0,00 | 0,97 |
| decoplamiento cross-asset | 0,03 | 0,00 | 0,13 |

## Lectura (afina la contribución del paper)
1. **3σ es ciego** a stale, repetidos y decoplamiento (recall ~0). Es el hueco real
   del estado del arte; con saltos sí funciona (0,95).
2. **El check TRIM de repetidos consecutivos cierra stale/repetidos (recall 1,0)**
   donde 3σ da 0. Es determinista, barato y aplica directamente la regla **≥20
   sesiones con rendimiento 0 → alerta**. **Ahí no hace falta CNN.**
3. **El cross-asset lineal cheap apenas aporta** (stale 0,04; decoplamiento 0,13).
   Por tanto la **CNN 1D cross-asset solo se justifica para DECOPLAMIENTO**, que es
   donde 3σ y el control cheap son débiles y hay recorrido real.

## Autocrítica (límite de este gate)
Mi cross-asset es una regresión lineal **por día**; el decoplamiento es un defecto
de **ventana**. Un detector a nivel de ventana/episodio (residuo sostenido) o
no lineal rendiría más. La CNN 1D debe batir a un **cross-asset reforzado**, no a
esta primera versión débil, para acreditar valor.

## Consecuencia para el reparto
- **TRIM / estructural (A):** ya bate a 3σ en stale/repetidos — pieza cerrada de valor.
- **Cross-asset / CNN 1D (B):** enfocar en **decoplamiento** (correlación rota),
  con baseline cross-asset reforzado y evaluación a nivel de ventana.
