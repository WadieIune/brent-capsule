# Factorial DQ × XGBoost: primera ejecución

2026-10-01. Estado exploratorio condicionado a contaminación sintética, no validación de cadena productiva.

## Contrato y alcance

Panel Brent/EURUSD observado en fechas comunes. Inyección reproducible seed71: bloques de2-5 precios congelados, probabilidad de inicio.005 por fecha/serie. No precios no positivos ni exclusión de episodios WTI. El filtro causal de rachas marca desde el segundo retorno consecutivo cero; conserva calendario, deja ausencias sin reconstruir el precio verdadero. No es CNN ni implementación completa regresión+ATR.

Tres estados de entrada: contaminado, filtrado por rachas, referencia sin inyección. Dos motores: escenarios históricos condicionados por ratio EWMA de varianza y el mismo motor con pesos de clases XGBClassifier. Biblioteca de futuros de entrenamiento y labels idénticos derivados de referencia separadamente auditada. Así se aísla la calidad de entradas/condicionamiento; NO se mide contaminación de la biblioteca histórica ni un flujo productivo completo.

Ventanas64 observaciones, delay1; entrenamiento/validación anual purgados por labels10observaciones. XGBoost clasifica6 clusters de futuros entrenados solo en train, no XGB-AFT. Early stopping en validación previa. FHS aquí escala directamente escenarios multidía por ratioEWMA (.25-4 fijo); no simulación completa de trayectorias diarias. Mismo optimizador de exposición1M EUR, presupuesto150k y coberturas ideales, costes hipotéticos, sin afirmación regulatoria.

## Resultados

67 decisiones por celda. El coste incluye tarifa cobertura, financiación y penalización déficit. No hubo déficit observado en ninguna celda; eso no acredita protección extrema.

| Entrada | Motor | Coste medio EUR | Reserva media EUR | Cola95 realizada EUR |
|---|---|---:|---:|---:|
| Contaminada | EWMA |962.45|99552|44663|
| Contaminada | XGB+EWMA |950.07|98955|45286|
| Rachas | EWMA |962.60|99627|44663|
| Rachas | XGB+EWMA |938.85|100821|49345|
| Referencia | EWMA |965.44|99179|44663|
| Referencia | XGB+EWMA |950.16|102761|44663|

En entrada filtrada, deltaXGB-base=-23.75 EUR/decisión, ICbootstrap bloques3 decisiones[-43.77,-8.05]. Reserva AUMENTA1194 EUR y cola95 empeoraaprox10.5%. No es ahorro de capital a protección equivalente. Menor cobertura media (.7388 vs.7649) explica parte de reducción de costes; registrar riesgo residual evita premiar solo menor cobertura.

EfectoDQ en baseline=+0.1481 EUR; efectoXGB en entrada contaminada=-12.3786 EUR; interacciónDQ×XGB=-11.3717 EUR. No afirmar significación ni robustez de interacción: una semilla de inyección y otra de modelo, costes elegidos y muestra inspeccionada.

Logloss mixto XGB: contaminada1.348205, rachas1.350841, referencia1.364077; histórico1.351352. Mejora probabilística pequeña/no consistente. Brier rachasXGB.701842 vshistórico.701331 (peor). No identificar mejora de coste con calibración superior.

## Convergencia con línea del otro agente

DQ puede alimentar todos los motores como arquitectura deseada. Las ejecuciones previas no verifican esa conexión; no atribuir FHS−22.7% aDQ oCNN. XGB-AFT de supervivencia es otro objetivo y no el XGBClassifier aquí implementado. El−22.71% se reprodujo como proxy retrospectivo histórico/FHS con coeficiente k del peor test y banda informal de excepciones; no testKupiec ejecutado ni ahorro regulatorio validado.

Siguiente gate: mejora económica robusta, sin degradación de protección, con controles de cola y exposición/instrumentos/costes genuinos. Usar varias semillas prefijadas y biblioteca afectada porDQ en un experimento separado manteniendo labels/calendario referencia. No mezclar resultado de rachas sintéticas con superioridad de un control geométrico en datos naturales.

## Artefactos

Script experiments/risk_director_dq_xgb_factorial.py. Outputs_capital/dq_xgb_factorial contiene decisions.csv,scores.csv,summary.csv,manifest.json,paired_uncertainty.json. Pruebas manuales ejecutadas: máscara causal, modificación futura no altera pasado, calendario preservado, inyección positiva; comparación pareada y pérdidas de cola revisadas. El manifiesto conserva hashes y particiones.

## Revisión independiente final

No se detectó fuga directa en entradas retrasadas o particiones purgadas. Scores de clases son del clasificador auxiliar, no calibración de distribución reescalada ni de reserva. Se añadieron guardas de precios positivos/finitos, fechas ordenadas/únicas y varianza disponible; el manifiesto conserva hash de ejecución y hash posterior revisado. La aproximación EWMA multidía no reemplaza un baseline FHS completo. Gate de igual protección sigue incumplido.
