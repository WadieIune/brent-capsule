# Matriz completa CNN-capital y probabilidades

Fecha2026-10-01. Exploratorio, misma semilla42 y folds del primer backtest. Hipótesis incremental CNN no validada.

Se ejecutaron27 combinaciones: financiación anual1/5/10%, penalización déficit.25/1/2 y coste cobertura10/50/100bp. Las67 decisiones se comparan entre histórico, logit ventana completa, CNN1D, CNN visual y referencia fija hp1/hf0/R60000. Exposición1M EUR y límites iguales. La referencia fija fue añadida tras observar el primer resultado; no es comparador confirmatorio.

## Probabilidades de clases de escenarios

Promedios fuera de muestra, menores son mejores. Se muestran probabilidades mezcladas con20% histórico, que alimentan el optimizador; los CSV contienen también las probabilidades sin mezcla.

| Modelo | Log-loss | Brier multiclase |
|---|---:|---:|
| Histórico |1.351352|0.701331|
| CNN visual |1.370547|0.708554|
| CNN1D |1.399674|0.718085|
| Logit |1.447353|0.742517|

CNN visual supera a otros modelos aprendidos en estas medias, pero NO al prior histórico. Las clases se definen cada fold exclusivamente en train; estos scores no miden calibración de déficits raros ni sustituyen la evaluación de pérdidas.

## Todas las combinaciones económicas

Coste medio incluye cobertura, financiación y penalización de déficit. CNN visual frente a:

| Comparador | Mejora | Empata | Empeora | Rango delta coste EUR/decisión |
|---|---:|---:|---:|---:|
| Histórico |5|10|12|[-166.13,+1486.88]|
| CNN1D |11|3|13|[-2565.06,+1033.97]|
| Logit |11|9|7|[-4857.03,+128.20]|
| Referencia fija |25|1|1|[-8534.85,+144.46]|

Los resultados contra referencia fija no acreditan ventaja incremental CNN: es una política fija y todos los métodos optimizan para cada combinación. No seleccionar las5 celdas favorables frente histórico como titular. No hay intervalos de incertidumbre de esta matriz ni repetición por semillas;67 decisiones y pocos shocks no sostienen conclusiones fuertes.

La afirmación defendible: CNN visual se integra funcionalmente en un optimizador y backtest económico; mejora a comparadores aprendidos en scores medios de clasificación, pero no a la distribución histórica, y su ventaja económica cambia con los supuestos de coste.

## Atribución DQ y XGBoost

La arquitectura DQ -> dato auditado -> modelos de riesgo -> optimizador es razonable como propuesta. El código actual DQ no utiliza CNN. XGBoost hallado pertenece a supervivencia de canales, no al optimizador evaluado aquí. El modelo tabular de esta matriz es LogisticRegression, no XGBoost. No afirmar CNN-DQ-capital ni ahorro de XGBoost implementado.

La auditoría independiente identifica que sanitize descarta WTI negativo aunque el propio docstring lo reconoce como cotización real; log_returns recorta no positivos a1e-9; hay diferencias de calendario y ventanas, y multiplicador retrospectivo k. La cifra13.4% de capital queda en revisión de validez/atribución. No reutilizarla como ahorro regulatorio o CNN confirmado.

## Reproducibilidad

Scripts experiments/risk_director_capital_sensitivity_run.py y capital_sensitivity.py. Outputs code/applications/outputs_capital/capital_sensitivity: probabilities.csv, calibration_by_date.csv, calibration_summary.csv, sensitivity_decisions.csv, sensitivity_summary.csv, sensitivity_comparisons.csv, sensitivity_manifest.json, decisions.csv. La serialización int64 del manifiesto se corrigió tras entrenamiento; se regeneraron agregados desde CSV sin reentrenar. Resultado inicial conservado en carpeta separada.

Próxima fase: factorial dato crudo/auditado × baseline/modelo aprendido y evaluación incremental CNN-DQ si se implementa; disponibilidad y comparadores EWMA/FHS fuertes; costes/instrumentos reales y seguimiento congelado. No desplegar un sistema alegando ventaja demostrada a partir de esta matriz.
