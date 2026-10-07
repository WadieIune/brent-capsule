# Plan · Data Quality con capa de IA — nuevo foco del paper

- **Autor:** A · **Fecha:** 2026-10-06 · instrucción del MASTER (mismo prompt a A y B).
- **Objetivo:** centrar el paper en la **mejora del Data Quality**, la única vía
  que ha dado valor real, integrando **CNN + XGBoost + modelo generativo** en el
  framework de control ya creado, con **sistema de alertas real** cuyo
  **benchmark es el control típico de 3σ sobre log-rendimientos**.

## Tesis
Los controles estándar (3σ sobre log-rendimientos) **no ven** defectos
estructurales que sí importan para riesgo/capital: rachas estancadas,
**repetidos consecutivos** (≥20 sesiones con rendimiento 0 → P&L mensual
repetido, alerta TRIM), decoplamiento **cross-asset**, y formas imposibles de
**curvas de tipos** (ZC, OIS-RFR). Una capa de IA los detecta a **tasa de falsos
positivos controlada**, mejorando el estado del arte.

## Componentes
1. **Benchmark (a batir):** 3σ sobre log-rendimientos; + controles de cola
   (Hampel/Tukey/iForest) y el control geométrico ya existente.
2. **CNN 1D cross-asset:** revisa una serie **y sus pares correlacionados**
   (control de clustering). Entrada: ventana de la serie + residuo frente a sus
   pares. Detecta anomalías que un control por-serie no ve.
3. **XGBoost** sobre features de DQ (rachas, repetidos, saltos, residuo
   cross-asset, nº de registros, máx/mín).
4. **Modelo generativo:** sintetiza defectos realistas (ground truth) para
   entrenar/validar y para aumentar el test.
5. **Checks TRIM explícitos:** repetidos consecutivos; **≥20 sesiones con
   rendimiento 0** → alerta; repetidos no consecutivos; outliers 3σ; máx/mín; nº
   de registros; precios no positivos.
6. **Shape de curvas de tipos:** la misma CNN controla ZC / OIS-RFR (inversiones
   imposibles, kinks, violaciones de no-arbitraje). Datos disponibles: DGS2/5/10/30,
   SOFR, DFF en el panel.

## Evaluación (estricta, y aquí SÍ hay ground truth)
- **Inyección sintética** de defectos por familia, con verdad conocida →
  **recall / precisión / AUC-PR por familia** frente al benchmark 3σ.
- **A tasa de falsos positivos emparejada** (como en Gate 1 v3).
- **Caso real:** el defecto de EURUSD que atravesó el pipeline, como caso de estudio.
- **Cheap-before-expensive:** primero mostrar que el control **cross-asset
  estadístico** bate a 3σ; la CNN 1D solo se justifica si bate a ese cross-asset.

## Reparto propuesto (B decide como supervisor)
| Pieza | Propuesta |
|---|---|
| Benchmark 3σ + arnés de inyección + métricas (recall/precisión/AUC-PR) | **A** |
| Checks TRIM (repetidos ≥20, rachas, no positivos) | **A** |
| Control cross-asset estadístico (gate barato antes de la CNN) | **A** |
| **CNN 1D** (arquitectura, entrenamiento) | **B** |
| **Modelo generativo** de defectos | **B** |
| Shape de curvas de tipos (ZC/OIS-RFR) | conjunto |
| Auditoría cruzada | conjunto |

## Lo que se conserva
Las patas de riesgo (VaR −22,7 %, supervivencia C-index 0,664, detección AUC
0,97) quedan **documentadas**; la figura de arquitectura es correcta y se le
añade la capa de IA de DQ. Nada de lo cerrado se reabre.

## Primer paso (A, ya en marcha)
Gate barato de DQ: inyección de defectos (rachas/repetidos/saltos/decoplamiento),
**3σ vs TRIM vs cross-asset**, recall/precisión por familia. Si el cross-asset
bate a 3σ donde 3σ es ciego (rachas/repetidos), queda justificada la CNN 1D.
