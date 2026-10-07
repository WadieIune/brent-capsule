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

## Estado de integración — propuesta A, 2026-10-07

- `dq_daily_monitor` incorpora ahora un benchmark causal de **3σ sobre
  log-rendimientos**: media y desviación móvil de 60 sesiones, desplazadas una
  sesión para excluir el retorno evaluado. Se conserva el antiguo cuantil 99,9 %
  solo como diagnóstico histórico, no como benchmark principal.
- El monitor alerta una vez al alcanzar **20 log-rendimientos exactamente cero
  consecutivos**. Es un flag de revisión TRIM, no una orden de borrar/imputar: el
  patrón por sí solo no demuestra que una cotización repetida sea falsa.
- La salida distingue `layer=benchmark` de `layer=trim`; ambas quedan en el
  ledger auditable. Los demás controles existentes se mantienen como capa de
  revisión y tampoco convierten automáticamente un shock de mercado en error.
- **CNN, XGBoost y VAE aún no están integrados en la ruta operativa DQ.** La CNN
  disponible se entrenó para riesgo, el XGBoost localizado es de supervivencia y
  el VAE modela ventanas de retornos Brent. Su reutilización como detector DQ no
  está justificada sin etiquetas de defectos ni validación por familias. El gate
  sintético y el detector cross-asset barato son el siguiente paso; la CNN 1D
  solo avanza si añade valor frente a ellos a carga de falsas alarmas emparejada.
- **Curvas ZC/OIS-RFR quedan como extensión separada.** No tratar DGS2/5/10/30,
  SOFR y DFF como nodos de una misma curva sin resolver antes tenor, instrumento,
  calendario, timestamp y convenciones de construcción.

Esta integración de reglas es una propuesta en rama, pendiente de challenge de B;
no cambia el veredicto del paper ni constituye aún una comparación de desempeño.

### Prototipo CNN supervisado — 2026-10-07

Se añadió una prueba separada en `dq_cnn1d_supervised.py`; **no** está conectada
al monitor operativo. Los pares de Brent se seleccionan con correlaciones de
train; WTI se representa con Δprecio para preservar el settlement negativo. En
inyecciones sintéticas OOS 2024-2026, la CNN gana ~10 pp de recall en saltos
reversibles frente a `1−R²`, pero pierde en desacoplamiento/stale y su FPR OOS
media es ~19,9 % frente a ~9,7 % del control estadístico. **No pasa el gate
operativo.** Tres semillas y 124 ventanas solapadas; ver
`docs/hallazgos/2026-10-07-A-dq-cnn1d-supervisada.md`.

El flujo de producto conserva detección de canales y supervivencia después del
gate DQ; no se usan como etiquetas de calidad. Las salidas de calidad deben
identificar ventanas observables y procedencia antes de que canales/supervivencia
o Risk Director consuman la serie. XGBoost DQ y un generador de defectos siguen
pendientes; el VAE Brent actual no equivale a un modelo generativo de corrupción.
