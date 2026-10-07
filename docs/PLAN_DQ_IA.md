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

### CNN de shape de curva — 2026-10-07

Se evaluó una CNN 1D con los únicos nodos de curva disponibles, DGS2/DGS10/DGS30
(CMT, no ZC), perturbando el nodo 10Y entre 1 y 8 bp. Frente a 3σ puntual,
recupera el carácter cross-tenor; pero el residuo simple de interpolación
log-tenor logra ~99 % recall con FPR limpia de test 0, mientras CNN promedia
~50 % y varía mucho por seed. **La mejora observada es del control de shape,
no de deep learning**. Sin DGS5, malla ZC bootstrapped ni GBP/SONIA no hay base
para reclamar validación de Svensson o de cobertura entre instrumentos. Detalle:
`docs/hallazgos/2026-10-07-A-dq-curve-cnn1d.md`.

### Gate conforme y espacio nulo — 2026-10-07 (🟡 pendiente de challenge B)

El veredicto anterior sobre la CNN de series se midió mal: el umbral se calibraba
en validación y se congelaba para test, de modo que la CNN operaba al **19,9 %**
de falsas alarmas frente al **9,7 %** del cross-asset, con objetivo 5 % para
ambos. Recall comparado en puntos de operación distintos. Con un **gate
conforme-adaptativo** (ACI) la CNN cumple el presupuesto (FPR 0,053).

Corregido el protocolo, el resultado defendible **no** es que la red gane a los
controles explícitos —en la familia para la que cada control fue diseñado, pierde:
`1-R²` logra 1,000 en `stale`, 0,863 en desfase de calendario, y el residuo
Nelson-Siegel 1,000 en forma de curva—, sino que **la red cubre defectos
analíticamente invisibles para toda la familia de estadísticos baratos**.

Con **seis** familias nunca vistas, a FPR emparejada (azar 0,056): en `sign_flip`
los tres controles baratos son **exactamente ciegos** —`1-R²` porque la regresión
reajusta `β`, 3σ porque usa `|·|`, el vol-ratio porque usa desviaciones típicas—
y la CNN logra **0,998**. En `rescale`, misma invariancia analítica: CNN 0,594
frente a 0,056 / 0,065 / 0,300. Pero **ningún detector domina**: el vol-ratio gana
en empalme de proveedores (0,690) y `1-R²` en desfase de una sesión (0,863).

**Retractado** respecto de la primera versión: con una sola familia no vista se
afirmó que la CNN era el único detector por encima del azar en todas. Con seis es
falso — en `quantize` (pérdida de precisión) **los cuatro** quedan en el azar.

**Y ese hueco resultó ser de REPRESENTACIÓN, no de método.** Rehecha la inyección
sobre **precios crudos** (truncación del tick, con retornos y normalización
recalculados), un control de rejilla de diez líneas sobre el precio logra
**recall 1,000 con FPR 0** en truncaciones de 0,10 $ a 1,00 $, mientras los
cuatro detectores de ventana **siguen en el azar**. Una truncación de hasta 1 $
sobre Brent no deja huella en retornos normalizados por volatilidad y deja huella
total en la retícula del precio. Los cuatro controles de la tabla miran todos la
misma representación, y por eso comparten un espacio nulo entero.

Consecuencia para la arquitectura: **el banco de controles debe cubrir varias
representaciones (precio crudo y retorno normalizado), no solo varios
estadísticos.** La cobertura se gana cambiando de representación antes que
añadiendo capacidad al modelo. Es la misma lección que el `vintage` de B y que el
residuo Nelson-Siegel. Código: `dq_quantize_price_grid.py`.

Autocrítica incluida: leave-one-family-out muestra que buena parte de la ventaja
de la CNN dentro de sus familias de entrenamiento estaba inflada por estar en
distribución (0,865→0,511; 0,797→0,540; 0,998→0,397).

Arquitectura que se deriva: **banco de controles baratos con su espacio nulo
declarado + CNN como red de arrastre de lo no anticipado, bajo un único gate
conforme que impone la tasa de falsas alarmas.** La frase «las redes no baten a
los controles explícitos» queda **imprecisa, no falsa**: es correcta familia a
familia cuando existe control dedicado, e incorrecta como enunciado general. Se
somete a veredicto de B. Detalle: `docs/hallazgos/2026-10-07-A-dq-gate-conforme-espacio-nulo.md`.

La idea YOLO queda como experimento de localización visual, no como sustituto
del control numérico: representar la matriz tiempo×tenor y evaluar cajas de
defectos localizados (recall de eventos, IoU en tiempo-tenor y falsas alarmas
por curva-fecha). Requiere etiquetas alineadas con el evento real, rasterización
congelada y comparación pareada con CNN 1D/residuo/3σ. La prueba YOLO ejecutada
abajo es de log-volatilidad, no valida todavía localización en curvas; ese gate
debe usar defectos reales/sintéticos pareados y controles de shape.

### Localización de spikes en log-volatilidad — 2026-10-07

Primer test YOLO/CNN 1D pareado en ventanas sintéticas mean-reverting: a 2σ,
CNN1D localiza 97,6% frente a 77,6% del 3σ calibrado a 2% FPR en validación;
YOLO logra 92,8%. En test la FPR sube a 4,0% CNN y 4,8% YOLO (3σ queda 0,8%),
así que es evidencia de señal aprendible, no gate operativo superado. YOLO no
mejora la CNN numérica. Repetir con más semillas/ventanas y datos reales antes
de incorporar. Ver `docs/hallazgos/2026-10-07-A-dq-yolo-volatilidad.md`.
