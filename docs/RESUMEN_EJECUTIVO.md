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

La consecuencia operativa es la que importa: un umbral que dispara varias veces
más de lo que su propio supuesto promete **no puede separar una cola real de
mercado de un defecto de dato**. Eso motiva buscar cobertura en otras
representaciones del dato, no en subir el umbral. No permite inferir ninguna
dirección de sesgo en capital, que dependería de cartera, horizonte y
metodología y aquí no se calcula.

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

Todos los controles operan bajo un gate conforme-adaptativo, que calibra el
umbral sobre la distribución empírica observada en lugar de sobre una forma
supuesta. Esa garantía **no es incondicional**: depende de la dependencia entre
ventanas, del *drift* y del tamaño de la muestra de calibración.

Figuras: [arquitectura del sistema](figuras/dq_encaje_produccion.pdf) y
[cobertura por control y familia](figuras/dq_pipeline_gate_a_b.pdf).

## Cómo se mide

Detección sobre defectos de **verdad conocida** inyectados en los precios
crudos, con retornos y normalización recalculados para que el defecto se
propague como en producción. Partición cronológica: entrenamiento hasta
2018-12-31, validación 2019-2023, test desde 2024-01-05. Métrica principal
**recall a presupuesto de falsas alarmas común**; no se reporta precisión/PPV
porque exigiría una prevalencia real que no se tiene.

**Esto no es un backtest.** El gate no toma posiciones: se valida midiendo
detección. El backtest valida a los modelos de riesgo aguas abajo.

## Evidencia

**Ninguna representación domina.** Cada familia de defecto la cubre bien un
control distinto y varias las ve uno solo. El resultado es una matriz de
coberturas complementarias con huecos declarados, no un ranking.

**Dónde aporta la capa de IA.** La CNN 1D es el mejor control en las familias
cuyo defecto es un patrón temporal multivariante sin estadístico cerrado
evidente, y es el control que más cubre en el escenario de defecto que llega con
el **dato nuevo** —el frecuente—, aunque ahí lo es dentro de un campo débil.
Donde existe un control dedicado, la red pierde contra él.

**Resultado negativo que se publica igual.** XGBoost como combinador rinde por
debajo de la unión de los mismos controles con umbral propio, y llega a diluir
un control que resuelve su familia de forma exacta. «ML que apoya» sí; «ML que
sustituye» no.

**Alcance del control de vintage.** Alcanza recall 1,00 cuando el defecto
reescribe historia ya publicada, y es ciego **por construcción** cuando llega
con el dato nuevo, porque no hay snapshot con el que comparar. Complementa en el
eje de la procedencia; no resuelve la calidad por sí solo.

Solo son interpretables las comparaciones a la **misma** tasa de falsas alarmas.
Las configuraciones de capa que operan a tasas distintas describen puntos de
operación, y su diferencia de recall no mide valor incremental.

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
