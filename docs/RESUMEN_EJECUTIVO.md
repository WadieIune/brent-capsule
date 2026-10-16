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
2018-12-31, validación 2019-2023, test desde 2024-01-05. Métrica principal
**recall con umbrales calibrados a objetivo nominal común; FPR OOS no igualada**;
no se reporta precisión/PPV
porque exigiría una prevalencia real que no se tiene.

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
