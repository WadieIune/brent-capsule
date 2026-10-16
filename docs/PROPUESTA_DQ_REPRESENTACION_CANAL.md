# Propuesta de investigación — framework de Data Quality para series temporales

- **Fecha:** 2026-10-07
- **Objetivo del paper:** diseñar y evaluar un framework de Data Quality (DQ)
  para series temporales financieras heterogéneas, combinando controles
  estadísticos contrastados con ML/deep learning donde aporten cobertura o
  automatización. No se busca demostrar alpha, rentabilidad, cumplimiento de
  Basilea ni que el canal prediga retornos.
- **Estado:** primera corrida confirmatoria inicial completada; no se promueve a producción ni se afirma superioridad de IA.

## Tesis y alcance

La unidad de investigación es un framework reusable para millones de series de
distintas asset classes, frecuencias y semánticas: precios, retornos, curvas,
spreads, volatilidades e indicadores. No se presupone que un modelo universal
resuelva todo. Se plantea una arquitectura de controles por capas que enruta
cada serie a controles y representaciones compatibles con su tipología,
metadatos, calendario, fuente y relaciones cross-series.

La arquitectura tiene dos capas explícitas. **Capa 1: controles estadísticos y
deterministas** como benchmark y barrera base (3σ, TRIM, rangos, calendario,
repetidos, etc.). **Capa 2: controles automáticos e inteligentes para el Risk
Director**, donde se integran canal y supervivencia como representación DQ,
XGBoost para combinar señales/features y CNN/visión para patrones temporales y
geométricos. El generativo puede apoyar escenarios de entrenamiento, nunca
sustituir ground truth ni validación con incidentes reales. La capa 2 amplía y
prioriza controles; no reemplaza la primera ni se presume superior.

La segunda capa entrega al Risk Director alertas trazables (serie, fecha/tramo,
familia probable, controles activados, evidencia, score/calibración y prioridad)
para revisar o escalar. Evita corrección automática opaca. El éxito se mide por
calidad DQ, cobertura y automatización fiables; capital/riesgo es un posible
impacto downstream, no el objetivo primario.

## Framework propuesto

1. **Contrato y tipología:** unidad, calendario, frecuencia, precisión/tick,
   fuente, límites, relaciones conocidas, transformaciones corporativas y
   transformación estadística compatible con la semántica de la serie.
2. **Capa 1 — controles deterministas:** esquema/completitud, duplicados, faltantes,
   orden temporal, stale y rachas de retornos cero (incluido TRIM >=20 sesiones),
   rangos/positividad, 3σ y robust-statistics, saltos/reversiones, ticks,
   splits/restatements y consistencia cross-asset.
3. **Capa 2 — representaciones:** precio-retorno; pares/cestas; geometría de
   curva/tenor; canal/régimen/supervivencia; visión cuando la localización
   espacial añada información. Cálculo *as-of*, sin fuga temporal.
4. **Capa 2 — modelos:** XGBoost para features tabulares/combinación calibrada;
   CNN 1D para forma temporal multivariante; detección visual para localización;
   generativo solo para escenarios sintéticos auditables.
5. **Capa 2 — alertas al Risk Director:** presupuesto de falsos positivos por tipología,
   priorización por severidad, evidencia, trazabilidad y revisión humana.
6. **Operación a escala:** batch/stream, modelos compartidos por familias
   cuando sea válido, calibración por tipología/fuente, drift, latencia,
   throughput, coste, fallback determinista y versionado reproducible. Millones
   de series es requisito objetivo, no capacidad demostrada por los pilotos.

### Contrato de representación por tipología

No se fuerza una única transformación para todas las series. Los log-retornos
son la vista principal para cambios proporcionales de precios positivos y
comparan cambios en una unidad adimensional; **no igualan la volatilidad** entre
activos. Para comparar magnitudes entre activos se conserva también una vista
estandarizada por volatilidad histórica causal, estimada solo con observaciones
anteriores a la fecha evaluada. Las señales de precio absoluto, unidad, rejilla y
vintage permanecen disponibles en paralelo: ni log-retornos ni z-scores deben
borrar defectos de nivel, tick, split o restatement.

| Tipología | Representación temporal | Controles que deben conservar la vista original |
|---|---|---|
| Precios estrictamente positivos (equity, FX, commodities positivos) | `log(P_t/P_{t-1})`; opcionalmente z causal sobre historia previa | Límites/unidad, tick, split y ajustes corporativos, stale y comparación vintage |
| Precio que puede ser cero o negativo (WTI en episodios de settlement negativo) | `ΔP` en unidad nativa y escala robusta causal estimada en train; no aplicar log | Nivel y signo, límites contractuales, tick, vintage |
| Tipos, curvas y spreads en bps | Diferencia aditiva en bps; features cross-tenor y residuo contra curva suave | Monotonía/no-arbitraje cuando aplique, tenores, calendario, convención, fuente y smoothness paramétrica |
| Volatilidad/índice estrictamente positivo | Log-cambio para movimiento proporcional y nivel en unidad original | Límites, unidad, saltos y revisión de metodología |
| Series derivadas o con whitelist de repeticiones | Transformación definida por linaje y reglas del instrumento | Repetición por diseño, calendario, propagación/ffill y sincronía con componentes |

La transformación se registra en el contrato con versión y motivo; no se
selecciona mirando el test. Un benchmark de retornos no sustituye los controles
de precio. En particular, canal/supervivencia puede calcular geometría sobre
log-precio relativo (equivalente a la trayectoria acumulada de log-retornos,
salvo inicialización), mientras tick, vintage y nivel siguen operando sobre la
serie fuente. Supervivencia es contexto/persistencia *as-of*, no etiqueta de
defecto ni prueba de calidad por sí misma.

### Núcleo ejecutable del framework

El primer núcleo tipado está implementado en `code/applications/dq_framework.py`.
`SeriesContract` obliga a declarar tipología y unidad; el motor genera retornos
compatibles, z-score y Hampel causales, alertas TRIM al completar 20 retornos
cero, repetidos, timestamps y no-positivos donde la semántica lo requiere.
Admite scores contextuales de canal/supervivencia y scores CNN/XGBoost solo si
vienen alineados por timestamp y acompañados de un umbral congelado; las
salidas son alertas de revisión con evidencia, nunca una corrección del dato.

Este núcleo aún no calcula por sí mismo la geometría ni la supervivencia, no
entrena modelos, no calibra umbrales y no es una ejecución multi-millón. Es el
contrato de integración para esos adaptadores. Está cubierto por
`tests/test_dq_framework.py`; la prueba de escala requerirá una capa batch,
medición de memoria/throughput/latencia y replay estratificado por tipología,
no la extrapolación de este test unitario.

## Hipótesis falsables

H1: el framework por tipología identifica defectos conocidos con mayor cobertura
que los controles estadísticos solos, a un presupuesto común de falsas alertas.
H2: los modelos transfieren a activos, fuentes y familias de defectos no vistos.
H3: la automatización reduce trabajo manual/tiempo de detección sin perder
trazabilidad ni calibración. H4: las alertas no se disparan sistemáticamente
ante cambios de mercado legítimos. Canal es una de las representaciones a
evaluar, no el framework completo.

Si una técnica replica 3σ/TRIM/residuo cross-asset, o su mejora desaparece con
FPR emparejada, no se reclama valor incremental de IA en la segunda capa. Un resultado válido es
que una regla sencilla resuelva una familia con más fiabilidad y menor coste.

## Evidencia exploratoria inicial

Hay un prototipo exploratorio en `code/applications/experiments/dq_channel_representation.py`
y un reporte en `results/reports/dq_channel_representation/summary.json`. A FPR
nominal emparejada de 5% sobre 124 ventanas de test, los controles de canal son
complementarios: coherencia de posición-en-banda da recall 1,00 en `stale` y
0,58 en `decoupling`; déficit de oscilación da 1,00 en `stale` y 0,99 en
`weekly_ffill`; residuo cross-asset en retornos normalizados logra 0,90 en
`decoupling` y 0,85 en `lag1_calendar`; rejilla de precio alcanza 1,00 en
`quantize`. CNN1D logra 0,93 en `decoupling`, pero solo 0,41 en `source_switch`.
Esto apoya investigar una matriz de representaciones complementarias, no la
afirmación de que una red o el canal dominen.

Ese piloto no es evidencia confirmatoria: tenía ventanas solapadas y umbrales
estimados sobre el mismo test limpio. Sus proxies de canal tampoco recalculaban
episodios/supervivencia.

## Corrida confirmatoria inicial

El protocolo revisado y el resultado están en
`docs/hallazgos/2026-10-07-A-dq-canal-confirmatorio.md`; código en
`code/applications/experiments/dq_channel_confirmatory.py` y números completos
en `results/reports/dq_channel_confirmatory/summary.json`. Se usan ventanas
disjuntas 20/20, umbrales calibrados en validación limpia independiente, CNN1D,
XGBoost DQ (tres familias conocidas y cuatro holdout), recálculo de episodios
Brent y predicciones de un XGB-AFT limpio congelado.

La validación solo contiene 19 ventanas limpias y test 71: FPR test es 0/71
para CNN y XGBoost, pero excede el 5% nominal en controles de ruptura de banda
(8.45%), geometría (12.68%) y oscilación (7.04%). La CNN no detecta la mayoría
de familias y XGBoost apenas transfiere a las familias reservadas; los
controles específicos ganan en familias concretas. El XGB-AFT muestra que los
defectos sintéticos pueden alterar el inventario de episodios. Los IC
Clopper–Pearson 95% están en el JSON; para 0/71, el límite superior es 5.06%, así
que tampoco se descarta que la FPR real supere el 5% nominal.

Como análisis paralelo, la comparación Seaborn de rendimientos muestra la
distribución empírica frente a normal y ±3σ para nueve precios/FX. Método y
límites: `docs/hallazgos/2026-10-07-A-distribuciones-rendimientos-3sigma.md`.
Esto motiva calibración por distribución/tipología; no prueba que la IA mejore
precisión. La prueba de IA requiere ground truth, test OOS y métricas de alerta.

**Conclusión provisional:** queda demostrado que defectos sintéticos pueden
alterar episodios del canal y riesgo estimado; no que CNN/XGBoost sean mejores
detectores. La validación pequeña, intervalos amplios, un único panel y una
sola cartera proxy impiden una conclusión confirmatoria fuerte. Ver el
hallazgo para las cifras completas y límites.

## Experimento de retornos rolling — 2026-10-16

**Estado:** evidencia provisional, pendiente de challenge cruzado; no se eleva a conclusión confirmatoria del paper.

La hipótesis de que usar retornos en los controles de canal resolvería la falta
de valor incremental se probó en un benchmark aislado con transformaciones
causales y defectos inyectados en precio. Protocolo, cifras y limitaciones:
`docs/hallazgos/2026-10-16-rolling-returns-vs-precios.md`; salida íntegra:
`results/reports/dq_rolling_return_channel/summary.json`.

En ventanas rolling, canal sobre retornos acumulados y canal sobre precios
tuvieron AUC descriptiva 0,857 y 0,855 respectivamente, y FPR OOS 26,6% y
27,4%. La pequeña diferencia no confirma una mejora robusta. XGBoost con
controles de precio obtuvo AUC 0,890, frente a 0,880 con controles de retorno y
0,873 al añadir el score CNN a estos últimos. La CNN sola tuvo AUC 0,790, pero
FPR OOS 15,1% ante un objetivo nominal del 5%. Esto no valida un combinador ni
una calibración operativa: son ventanas solapadas, la calibración es pequeña y
las etiquetas son sintéticas. La lectura compatible con la tesis del paper es
cobertura por representación especializada más calibración transferible, no
superioridad genérica de IA ni sustitución de precio por retornos.

Se añadió una comparación de calibración causal rodante. Actualizar con todos
los scores pasados redujo FPR del XGBoost de precio de 20,4% a 7,0%, pero el
recall de `source_switch` bajó de 94,4% a 45,4% y el de `quantize` de 22,0% a
8,3%. Actualizar solo con observaciones no alertadas elevó la FPR a 22,6% para
ese mismo detector: la selección por score trunca la cola y sesga la
recalibración. Ninguna política alcanzó un gate operativo estable. Por tanto,
la transferencia de calibración bajo drift es un problema central del
framework, no algo que se resuelva aplicando una ventana móvil sin control de
calidad del conjunto calibrador.

## Representaciones y controles

1. **Precio/retorno:** 3σ causal, límites/positividad, TRIM (incluidos 20
   retornos cero), salto/reversión y rejilla/tick cuando aplique.
2. **Cross-asset:** regresión/hedge ratio estimado en train y residuo
   contemporáneo; `1-R²` de ventana donde corresponda. Pares fijados con train
   y metadatos económicos, no con test.
3. **Canal:** residuos proyectados hacia delante, z-residuo, slope normalizada,
   R², anchura, posición, turns/curvatura y edad. Cada feature usa solo precios
   disponibles en t; supervivencia no se usa como etiqueta DQ.
4. **Aprendizaje:** CNN 1D sobre secuencia de residuo/anchura/posición y/o
   canales multiactivo; XGBoost sobre features explícitas de DQ, precio, par,
   canal, TRIM y procedencia. La CNN productiva de canales y el XGBoost-AFT de
   supervivencia no se reutilizan como detectores DQ sin entrenamiento y
   evaluación nuevos.

## Etiquetas y splits

Inyectar sobre precio crudo y recomputar retornos, canales y supervivencia en
cada serie corrupta:

- spikes aislados y spikes que revierten;
- stale/repetición y huecos/rellenos de calendario;
- offset o cambio de escala de proveedor;
- ajuste histórico/back-adjustment y cambio de tick/split cuando haya vintage;
- decoplamiento de un miembro de un par hedgeado;
- cambios de régimen reales, movimientos comunes y rupturas legítimas como
  controles negativos (no etiquetarlos automáticamente como corrupción).

Separar por tiempo, activo/familia y fuente cuando haya datos suficientes.
Inyecciones/parametrización se generan después del split. Escala, pares,
umbrales, canal y selección de modelos son train-only; calibración en validación
limpia separada; test incluye defectos OOD y datos limpios de estrés. La
observación t nunca entra en su propia proyección. Intervalos por bloques y
bootstrap por activo/episodio, no IID.

## Métricas y decisión

- Recall, precisión, AUC-PR y retraso por familia.
- FPR por activo-día/curva-fecha a presupuesto común y FPR realizada OOS con IC.
- Alertas por millón de observaciones/series, carga de revisión, latencia,
  throughput, coste de cómputo y cobertura por tipología; medir en replay
  representativo antes de afirmar escalabilidad.
- Si se localiza: error de índice e IoU en tiempo/tenor.
- **Fidelidad de representación:** cambios falsos de canal, variación de
  slope/anchura/posición y error de supervivencia entre serie limpia y
  corrupta; una diferencia no demuestra por sí sola detección útil.
- **Impacto DQ downstream, no alpha:** primero, comparar distribuciones de
  rendimientos empíricas con referencias gaussianas; medir asimetría, curtosis
  y frecuencia observada fuera de bandas ±3σ frente a la probabilidad normal.
  Después, evaluar si alertas etiquetadas distinguen defectos de colas/eventos
  legítimos. No equiparar un rendimiento extremo con dato erróneo ni borrar/
  imputar automáticamente. VaR/ES podrá ser análisis secundario solo con cartera,
  notional y metodología validados; no reportar cifras de capital en este paper.

Promover CNN/XGBoost solo si añaden cobertura en una familia no resuelta por los
controles baratos, respetan FPR y sobreviven al test temporal/familias. Para
afirmar preparación para producción también se exige evaluación operativa a
escala y control de drift. Si gana una regla sencilla, esa regla es el hallazgo.
El VAE solo entra tras validar
marginales, colas, ACF, estados y duración de regímenes; el probado hasta ahora
comprimió colas y no justifica augmentación.

## Secuencia de trabajo

1. Congelar el benchmark por tipología: TRIM, 3σ/MAD sobre transformación
   compatible, controles de tick/vintage y cross-asset/shape; documentar pares.
2. Diseñar calibración rodante con conjunto de referencia adjudicado o
   controles explícitos de contaminación; medir transferencia bajo drift y
   reportar el intercambio FPR/recall. El rolling no supervisado explorado no
   pasa el gate.
3. Añadir canal y supervivencia *as-of* al arnés de inyección, como features
   contextuales y no como etiquetas; medir cambios de forma, régimen y vida.
4. Evaluar reglas, CNN y XGBoost en los mismos splits y a presupuesto comparable
   de falsas alarmas, con familias/activos/fuentes retenidos.
5. Validar eventos reales adjudicados y medir impacto DQ downstream. Mantener
   estrés de mercado legítimo como negativo limpio salvo evidencia de corrupción.
6. Medir carga de revisión, latencia, throughput, drift y coste antes de afirmar
   escalabilidad; cerrar el paper con matriz de cobertura, negativos y límites.

No modificar el flujo productivo hasta que este gate pase auditoría y challenge
cruzado.
