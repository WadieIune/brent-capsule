# Plan · Data Quality con capa de IA — nuevo foco del paper

- **Autor:** A · **Fecha:** 2026-10-06 · instrucción del MASTER (mismo prompt a A y B).
- **Objetivo central (MASTER, 2026-10-07):** diseñar y evaluar un framework
  escalable de Data Quality para millones de series financieras y múltiples
  tipologías/asset classes, mejorando y automatizando controles con métodos
  contrastados de ML/deep learning. La capa estadística existente es el
  benchmark; la **segunda capa automática e inteligente** incluye canal,
  supervivencia como representación, XGBoost, CNN y alertas trazables para el
  Risk Director. Ninguna herramienta se presupone ganadora.
- **Alcance:** la escala de millones de series es el destino arquitectónico, no
  algo demostrado por los pilotos. Hay que probar transferencia entre familias,
  capacidad operativa, coste, latencia, drift y calibración. Capital/riesgo es
  impacto downstream posible, no el criterio principal ni una prueba de Basilea.
- **No objetivo:** alpha, rentabilidad o recomendación de posición.

## Tesis (actualizada por el MASTER, 2026-10-07)
El framework tiene dos capas: (1) controles estadísticos/deterministas actuales
como benchmark y primera barrera; (2) controles automáticos e inteligentes que
combinan nuevas representaciones y modelos para ampliar cobertura, automatizar
el triage y entregar alertas accionables al Risk Director. La segunda capa debe
ser medible, auditable y complementaria, no una caja negra que reemplace los
controles base. Los controles estándar (3σ sobre log-rendimientos) pueden no
ver defectos estructurales relevantes: rachas estancadas,
**repetidos consecutivos** (>=20 sesiones con rendimiento 0, alerta TRIM),
desacoplamiento cross-asset, spikes, splits/restatements y formas imposibles de
curvas (ZC, OIS-RFR). XGBoost y canal/supervivencia pertenecen a la segunda
capa; CNN y modelos generativos se evalúan como herramientas complementarias.
Solo se automatizan alertas si comparación temporal pareada demuestra calidad
aceptable a una tasa de falsos positivos controlada. No son señales de trading.

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
7. **DQ en espacio de canal (hipótesis nueva, no validada):** comparar controles
   de precio/retorno y cross-asset con residuos proyectados, geometría,
   asignación de régimen y duración/supervivencia calculadas *as-of*. Recomputar
   todo tras inyectar defectos con etiqueta conocida y medir el sesgo en las
   métricas de riesgo; no optimizar P&L ni llamarlo alpha.

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
Los trabajos anteriores de riesgo/supervivencia quedan como antecedentes
separados. Sus resultados no son métricas de éxito del framework DQ actual; la
figura anterior centrada en capital queda fuera del material de este paper.

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

### YOLO focalizado en spikes leves entre tenors — piloto 2026-10-07

Se ejecutó el test solicitado sobre pares de curvas suaves, residuo primario vs
referencia en 32 tenors log-espaciados, perturbaciones de 0,5–4 bp y etiquetas
bbox de tenor. En RTX 5060, tras corregir una fuga visual en el renderer,
YOLO alcanza recall localizado 0,144 a 0,5 bp y 0,578 a 1 bp (FPR test 1,4 %).
El residuo local logra 0,140 y 0,794 (FPR 2 %); residuo pareado 0,330 y 0,996
(FPR 3 %); CNN1D 0,290 y 0,978 (FPR 4,4 %). A 2 bp los métodos numéricos/CNN
alcanzan 1,0, YOLO 0,658. **YOLO aún no supera los controles de shape**; queda
como herramienta de localización visual hasta repetir multi-semilla y con curvas
reales. La fuga encontrada y métricas completas: `docs/hallazgos/2026-10-07-A-dq-yolo-spikes-tenor.md`.

### Encuadre del paper: DQ en representación de canal — 2026-10-07

Canal/supervivencia y XGBoost son componentes de la **segunda capa automática
e inteligente** para el Risk Director, no el framework completo. La capa 1
mantiene controles estadísticos/deterministas como benchmark; la capa 2 combina
representaciones, modelos y alertas trazables para extender cobertura y
automatizar triage. La validación primaria es DQ (detección, FPR, transferencia,
calibración y utilidad operativa). Distorsión del canal es una métrica
complementaria, no el objetivo central. Diseño:
`docs/PROPUESTA_DQ_REPRESENTACION_CANAL.md`.

El **piloto exploratorio** (`dq_channel_representation.py`) tenía 124 ventanas
solapadas, calibración sobre el test y proxies de canal. La primera corrida
confirmatoria inicial ya cierra esos puntos: 71 ventanas disjuntas OOS desde
2020-09-21, umbrales congelados de 19 ventanas limpias de validación, CNN1D y
XGBoost DQ y extracción completa de episodios con XGB-AFT congelado.
Código/resultados en
`code/applications/experiments/dq_channel_confirmatory.py` y
`results/reports/dq_channel_confirmatory/summary.json`; lectura en
`docs/hallazgos/2026-10-07-A-dq-canal-confirmatorio.md`.

No es una victoria de IA: el FPR test de CNN/XGBoost es 0/71, pero hay solo 19
observaciones limpias para calibrar; controles de canal superan 5% (ruptura
8.45%, geometría 12.68%, oscilación 7.04%), y CNN/XGBoost tienen recall débil
fuera de familias concretas. La corrida cierra brechas metodológicas del piloto
del canal, pero **no valida aún la segunda capa como framework multi-serie**.
Siguiente evidencia: benchmark multi-tipología, transferencia por activo/fuente,
volumen de alertas, calibración y coste/latencia a escala; challenge de B.

### Pila de 4 representaciones + XGBoost combinador — 2026-10-07 (🟡 pendiente de challenge B)

Cerradas las dos piezas que quedaban abiertas. Detalle y límites:
`docs/hallazgos/2026-10-07-A-dq-pila-cuatro-representaciones.md`.

**Vintage cierra `source_switch`, pero solo con restatement.** Comparando serie
recibida contra snapshot almacenado, vintage logra **1,000** en seis de las siete
familias cuando el defecto reescribe historia publicada — incluido
`source_switch`, que era el hueco abierto. Cuando el defecto solo toca el dato
**fresco** posterior al snapshot, vintage queda **exactamente en el azar en las
siete**: es ciego por construcción, no por falta de potencia. Es el control más
potente del banco dentro de su subespacio y no cubre nada fuera de él.

**XGBoost como combinador PIERDE contra la unión de controles gateados.** Con la
CNN entrenada en train, el combinador en validación y evaluación en test: unión
de los 9 controles con umbral conforme propio **0,606** de recall medio frente a
**0,539** del combinador, y la unión casi iguala al oráculo inalcanzable de
«mejor control por familia» (0,630). Salvedad declarada: la unión gasta 1,6× el
presupuesto de alarmas (FPR 0,083 vs 0,051) y no se consigue bajarla al 5 % por
el suelo de α del ACI y las 236 ventanas de calibración.

Dos celdas son concluyentes al margen del presupuesto: en `quantize|restated` el
control de retícula da **1,000** y el combinador **0,462**, con leave-one-family-out
en **0,048** = azar — **el modelo aprendido destruye un control analíticamente
perfecto**, aun siendo la retícula su feature más importante. Y en
`source_switch|fresh` el combinador da **0,435**, el mejor de todo, con el
presupuesto más apretado de los tres.

Regla con mecanismo: **el combinador ayuda cuando ningún control es decisivo y
estorba cuando uno lo es.** Arquitectura que se deriva: **unión de controles
gateados como esqueleto + combinador como canal adicional** para las familias
donde todos los controles son débiles. Eso es literalmente «ML que apoya a los
controles estadísticos», no que los reemplaza.

### Disclaimer de capital y prioridad de medición

Se retiran del paper y del resumen ejecutivo todos los porcentajes de «capital
evitado» construidos con cartera equiponderada, nominal base 100, impacto `k·VaR`
o prevalencia uniforme de defectos. No son estimaciones reales ni sustentan una
conclusión sobre capital; no citarlos como resultado. El cálculo previo queda
solo como artefacto exploratorio no validado y se marca como retirado en
`docs/hallazgos/2026-10-07-A-dq-capital-valor-anadido.md`.

La comparación principal pasa a la **distribución de rendimientos**: forma
empírica frente a una normal ajustada, curtosis/asimetría, frecuencia observada
fuera de ±3σ y comparación con el 0,27% teórico gaussiano. Es una descripción de
la distribución, no un umbral productivo ni prueba de calidad por sí sola. El
valor añadido de IA se medirá por detección con defectos etiquetados, FPR/recall
por tipología y mejoras de alertas en test temporal. Capital solo se menciona
como posible consecuencia aguas abajo, sin cuantificarlo sin posiciones,
notional y metodología de cartera validados.

### Distribución de rendimientos: lo que queda en pie — 2026-10-07

Diagnóstico descriptivo sobre Brent que complementa el de nueve series.
Figura Seaborn: `docs/figuras/dq_distribucion_rendimientos.png`. Código
`dq_return_distribution.py`. Hallazgo
`docs/hallazgos/2026-10-07-A-dq-distorsion-distribucion-por-gate.md`.

**Corrección de sentido que conviene fijar.** Suponer normalidad con bandas ±3σ
**infraestima** la frecuencia de extremos, no la sobreestima: en Brent |z| > 3
ocurre el **1,11 %** frente al **0,27 %** teórico (**4,1×**), y a 5σ la razón
llega a **5.605×**. Lo que la normal sobreestima es la masa de los *hombros*
(1σ y 2σ, ratios 0,5× y 0,8×). De ahí **no** se sigue ninguna dirección de sesgo
en capital: eso exige cartera, horizonte y metodología, y no se calcula.

**Consecuencia para DQ.** Si un umbral 3σ dispara cuatro veces más de lo que su
propio supuesto promete, **no puede separar una cola real de mercado de un
defecto**. Esto **motiva** el framework por representaciones; no lo demuestra.
La demostración viene de detección con etiquetas y test temporal (C10/C11).

**La curtosis no es una propiedad estable y no debe citarse sola:** 76,4 con
todo, 25,9 excluyendo un día, 12,9 excluyendo tres, 4,9 excluyendo diez — y
todos esos días son movimientos **reales** (2020-04-21, Brent de 17,36 a 9,12,
el día siguiente al WTI negativo; 2020-03-09; 2009-01-05).

**Degradado y fuera del paper.** La comparación de gates por «distorsión
corregida» (panel D y sus porcentajes) queda retirada: multiplicaba agregados
**no pareados** —distorsión sobre 40 episodios con un RNG, recall sobre 124
ventanas con otro— y proyectaba bajo corrección perfecta. Challenge en
`docs/auditorias/2026-10-07-A-challenge-dq-return-distribution.md`, aceptación y
condiciones para reabrir en
`docs/auditorias/2026-10-07-A-respuesta-challenge-dq-return-distribution.md`.
Ambas reservas —ésta y la de capital— tienen la misma raíz: un porcentaje
relativo grande sobre una base pequeña o sobre un supuesto idealizado se lee
como un resultado y no lo es.
