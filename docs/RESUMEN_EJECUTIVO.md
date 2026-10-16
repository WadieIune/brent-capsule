# Resumen ejecutivo — framework de Data Quality para series temporales

## Objetivo

Diseñar y evaluar un framework de Data Quality para series financieras que
combine controles estadísticos contrastados con una segunda capa automática e
inteligente para apoyar al Risk Director. El éxito se mide en calidad de
detección, cobertura entre tipologías y automatización trazable; no en
rentabilidad ni en porcentajes de capital.

## El problema

El control estándar en series de precios es una banda de ±3σ sobre
log-rendimientos, que lleva dentro un supuesto de normalidad que los datos no
cumplen. En nueve series del panel (2007-2026), la frecuencia empírica fuera de
±3σ está entre **1,14 % y 1,64 %**, frente al **0,27 %** de la referencia
gaussiana: entre 4,2 y 6,1 veces más. Todas tienen curtosis de exceso positiva.
Ver la [figura de distribuciones](../results/reports/dq_return_distributions/empirical_vs_gaussian_returns.png)
y el [resumen numérico](../results/reports/dq_return_distributions/distribution_metrics.json).

La comparación cuestiona la calibración gaussiana, pero **no permite clasificar
un movimiento como cola real de mercado o defecto de dato**. Eso motiva evaluar
otras representaciones y controles con etiquetas de incidentes. No permite
inferir ninguna dirección de sesgo en capital, que dependería de cartera,
horizonte y metodología y aquí no se calcula.

Advertencia de alcance: esa comparación es descriptiva y de muestra completa,
con *look-ahead* por la estandarización ex post. No es un umbral desplegable.

## Punto de operación declarado

**El gate no promete una tasa nominal de falsas alarmas: declara la medida.** Un
objetivo nominal del 5 % no se cumple fuera de muestra, y esconderlo detrás de la
palabra «objetivo» haría que el consumidor dimensionara mal su capacidad de
revisión. La curva de operación medida, con calibración rodante por clase de
control sobre el bloque de test 2024-2026:

| α nominal pedido | **FPR realizada** | exceso | recall medio |
|---|---|---|---|
| 0,005 | **0,083 ± 0,004** | 16,7× | 0,605 |
| 0,010 | **0,083 ± 0,004** | 8,3× | 0,608 |
| 0,020 | 0,099 ± 0,004 | 5,0× | 0,616 |
| 0,050 | 0,116 ± 0,004 | 2,3× | 0,646 |
| 0,100 | 0,202 ± 0,011 | 2,0× | 0,700 |

Dos lecturas operativas, y la primera es la que condiciona el despliegue:

1. **Hay un suelo en torno al 8 % de ventanas limpias marcadas.** Pedir 0,005 o
   0,010 da exactamente lo mismo: el gate no baja de ahí. Por debajo de ese punto
   no existe configuración, así que dimensionar la revisión suponiendo un 5 % o
   un 1 % es dimensionar mal.
2. **Por encima del suelo hay un intercambio real y suave.** De 0,083 a 0,202 de
   carga, el recall sube de 0,605 a 0,700. El punto se elige por capacidad de
   revisión disponible, no por un número de referencia.

La dispersión entre semillas es pequeña (±0,004 salvo en el extremo), así que la
curva es estable dentro de esta muestra.

### Por qué existe ese suelo

Porque **por debajo de cierto presupuesto la petición no es representable** con
la muestra de calibración disponible.

Las ventanas de análisis son de 20 sesiones con paso 5, de modo que dos
puntuaciones consecutivas comparten el 75 % de sus datos: de cada cuatro, solo
una está en fase no solapada. Una ventana de recalibración de 236 puntuaciones
contiene por tanto **59 observaciones efectivas**, no 236, y eso ignorando aún la
dependencia serial del propio mercado.

De ahí sale el límite:

| | |
|---|---|
| observaciones efectivas de calibración | **59** |
| presupuesto por control con 7 estadísticos | α / 7 |
| **α mínimo representable** | **7 / 59 = 0,119** |

Pedir un α por debajo de 0,119 no cambia el comportamiento del gate: el umbral
por control cae en el máximo empírico de la muestra y la unión entrega su suelo.
Eso explica la observación de la tabla anterior —pedir 0,005 o 0,010 da
exactamente el mismo 0,083— y convierte el suelo en una **consecuencia del
tamaño de la muestra**, no en una curiosidad empírica.

Es también la razón estructural por la que este documento declara el presupuesto
medido en lugar de prometer uno nominal: **no se puede prometer por debajo de lo
que la calibración es capaz de representar.**

Bajar el suelo exige más historia de calibración efectiva, y hoy eso está
limitado por trabajar sobre un solo activo con ventanas solapadas al 75 %.

> **Corrección registrada.** Una versión anterior de esta sección descomponía el
> exceso en «resolución corregida más deriva residual de 2,6×». Esa atribución
> contaba las 236 puntuaciones como independientes y **queda retirada**: con la
> muestra efectiva, el término de resolución sigue activo y el exceso no es
> atribuible a deriva. Challenge en
> `auditorias/2026-10-16-B-challenge-dq-calibracion-por-clase.md`, respuesta en
> `auditorias/2026-10-16-A-respuesta-challenge-calibracion-por-clase.md`.
> El suelo, la curva de operación y la correlación de 0,09 entre alertas no se
> ven afectados: son observaciones, no atribuciones causales.

## Calibración por clase de control

Los controles no admiten todos el mismo esquema, y mezclarlos fue una de las
causas del descalibre:

- **Estadísticos** (3σ, cross-asset, CNN, los de canal): puntuación continua, hay
  cola que estimar, se calibran por **cuantil rodante** sobre el flujo observado.
  Sin etiquetas —solo entra la puntuación de cada ventana que llega—, así que es
  desplegable.
- **Deterministas** (vintage, retícula): su puntuación limpia es **constante** —la
  discrepancia con el snapshot es cero, la retícula es el tick nativo— y no hay
  cola que estimar. El umbral correcto es **semántico**: cualquier valor distinto
  del nominal es una alerta. Aplicarles un cuantil es un error de categoría, y
  medido le sube la tasa de falsas alarmas a vintage de 0,000 a 0,129.

Como los deterministas no consumen presupuesto, α se reparte **solo entre los
estadísticos**.

## Arquitectura

El gate de calidad de dato se despliega en dos capas y entrega una serie
validada a los modelos de riesgo.

1. **Capa A — determinista y estadística:** calendario, duplicados, faltantes,
   TRIM y rachas de retornos cero, rangos y positividad, 3σ y robustos, reglas
   por instrumento. Resuelve de forma cerrada y barata lo que admite regla.
2. **Capa B — por representación, con IA:** el mismo dato mirado como precio
   crudo (retícula del tick), como retorno frente a pares correlacionados
   (1−R² y CNN 1D), como canal (posición en banda, oscilación, geometría) y
   como *vintage* (serie recibida frente al snapshot almacenado). XGBoost entra
   como combinador de señales. Complementa la capa A; no la reemplaza.
3. **Salida:** alerta trazable con serie, tramo, controles activados, evidencia
   y score calibrado. Revisión humana; nunca corrección automática.

Los umbrales se calibran una vez sobre un bloque tardío de validación, purgado
del ajuste, y quedan congelados antes del test. La FPR observada fuera de muestra
se reporta sin feedback. No se reclama garantía conformal ni estabilidad bajo
*drift*.

Figuras regeneradas por el runner: [arquitectura y cobertura](../results/figures/dq/dq_pipeline_gate_a_b.pdf),
[diagnóstico de distribuciones](../results/figures/dq/dq_distribucion_rendimientos.pdf).

## Cómo se mide

Detección sobre defectos de **verdad conocida** inyectados en los precios
crudos, con retornos y normalización recalculados para que el defecto se
propague como en producción. Partición cronológica: entrenamiento hasta
2018-12-31, validación 2019-2023, test desde 2024-01-05.

Se reportan **dos métricas y hay que no confundirlas**. La **FPR realizada** es
la carga de revisión medida fuera de muestra, y es la que se declara arriba: no
hay objetivo nominal que prometer. El **recall** se lee siempre junto al punto de
operación al que se obtuvo, porque comparar recalls a cargas de alarmas distintas
fue el error que llevó a conclusiones falsas en las dos direcciones.

No se reporta precisión/PPV: exigiría una prevalencia real de defectos que no se
tiene, y declararla con una prevalencia inventada daría un número sin
significado.

**Esto no es un backtest.** El gate no toma posiciones: se valida midiendo
detección. El backtest valida a los modelos de riesgo aguas abajo.

## Evidencia

**Evidencia exploratoria, no confirmatoria.** Los resultados son una matriz de
coberturas sobre defectos sintéticos. Las FPR observadas difieren entre controles
y el mejor control por familia se selecciona sobre el mismo test; no demuestra
superioridad generalizable ni aportación incremental.

**Hipótesis sobre la capa de IA.** La CNN 1D forma parte del banco y hay familias
sintéticas donde muestra cobertura. El diseño actual no permite atribuirle una
mejora causal: falta prueba externa, selección preespecificada y etiquetas de
incidentes reales. No se afirma que un escenario sea frecuente sin datos de
prevalencia.

**XGBoost: comparación no concluyente.** Su FPR OOS y la de la unión de controles
son distintas; por tanto, la diferencia de recall mezcla sensibilidad con punto
de operación. Hace falta comparar a FPR equivalente o mediante curvas ROC/PR,
con protocolo preespecificado y validación externa.

**Alcance del control de vintage.** Alcanza recall 1,00 cuando el defecto
reescribe historia ya publicada, y es ciego **por construcción** cuando llega
con el dato nuevo, porque no hay snapshot con el que comparar. Complementa en el
eje de la procedencia; no resuelve la calidad por sí solo.

El objetivo de calibración es común, pero las tasas de falsas alarmas realizadas
en test no son iguales. Las diferencias de recall describen estos experimentos;
no miden por sí solas valor incremental de CNN o XGBoost. El benchmark ejecuta
los detectores en paralelo y no valida un router secuencial.

La calibración es discreta por el tamaño limitado del bloque. Al repartir el
objetivo nominal de la unión entre varios controles, algunas cuotas quedan por
debajo de una observación de calibración; el umbral cae en el máximo empírico y
no representa exactamente la FPR nominal. Esto limita la interpretación
operativa y ayuda a explicar las FPR OOS elevadas observadas.

## Los modelos de riesgo que consumen la serie

El backtest se les aplica a ellos, que miden riesgo. Conviene dejar escrito no
solo que lo superan, sino por qué.

- **VaR FHS-EWMA condicional a volatilidad.** Kupiec p 0,985 (cobertura
  correcta), Christoffersen p 0,128 (las excepciones no se agrupan), semáforo de
  Basilea en zona verde con k = 3,0. Supera el backtest **porque condiciona a
  volatilidad**: un VaR histórico simple sobre la misma serie falla la prueba de
  independencia (Christoffersen p 0,0011), acumulando sus excepciones en los
  episodios de estrés, que es cuando el capital tiene que aguantar.
- **Supervivencia del canal · XGB-AFT.** C-index 0,664 ± 0,007. Supera el
  backtest **porque la validación es walk-forward purgada con embargo**, que
  impide que un episodio que rompe tras el corte entrene con su propio futuro.
- **Detección de canal.** AUC 0,973 ascendente y 0,956 descendente **como
  clasificador**. Como estrategia de inversión **no** supera el backtest:
  Deflated Sharpe 0,000 y PBO 0,382, con Sharpe 0,329 frente a 1,004 del
  buy & hold. Por eso se usa como contexto de régimen y nunca como señal.

## Entregables

- [Excel de resultados](../results/reports/dq_entregables/resultados_dq.xlsx) —
  métricas y protocolo, cobertura por control y familia, puntos de operación,
  familias de defecto, evidencia de los modelos aguas abajo, estado de
  validación y limitaciones.
- [Resumen en Word](../results/reports/dq_entregables/resumen_dq_estado_del_arte.docx).
- Figuras en PDF vectorial, listas para Overleaf.
- `code/run_dq.sh` reproduce la línea completa en la cápsula Code Ocean. Las
  figuras y los entregables **leen** los JSON publicados por los experimentos,
  de modo que no pueden divergir de la evidencia.

## Límites

Defectos **sintéticos** escritos por nosotros, promediados con prevalencia
uniforme entre familias, que no representa la incidencia real. Test de 124
ventanas que **solapan al 75 %**: no son observaciones independientes y
cualquier intervalo implícito es optimista. Todo el banco se ha medido sobre
Brent y cuatro pares: la transferencia a otras asset classes **no** está
demostrada. Los controles estadísticos son deterministas y no llevan dispersión;
solo la CNN y el combinador promedian semillas.

Todos los resultados del gate son **provisionales** y están sujetos a auditoría
cruzada. Un resultado sin auditoría superada no puede figurar como afirmación
cerrada en el paper.

## Disclaimer de capital

No se reporta ninguna cifra de capital. El capital por modelo interno sería
`k · VaR` con `k` del semáforo de Basilea, pero una traducción honesta exigiría
cartera real con posiciones y notional, correlaciones entre factores,
diversificación entre mesas, riesgo específico y de default, P&L attribution por
mesa, NMRF y suelo del método estándar. Quedan retiradas las cifras previas de
«capital evitado» y «capital por dato» derivadas de carteras equiponderadas,
nominales normalizados o prevalencias uniformes: no representan una estimación
real y no deben citarse.
