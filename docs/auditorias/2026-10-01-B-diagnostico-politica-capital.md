# Estado supervisor y diagnóstico de decisiones

2026-10-01. Continuación del backtest CNN-capital. Resultado económico aún nulo; ningún agente ha demostrado ventaja CNN.

Se ejecutó capital_policy_diagnostic.py: para cada fold anual se conserva la biblioteca de escenarios de entrenamiento y los mismos costes/restricciones. Se evalúan distribución histórica y seis vértices de la mezcla 20% histórica +80% probabilidad de una clase. No se usan pérdidas de test para elegir parámetros. Los vértices son distribuciones hipotéticas extremas, no predicciones logradas por la CNN.

Resultados: 21 casos, 20 con cobertura petróleo 100%, divisa 0%. Un vértice de 2026 selecciona petróleo75%, divisa0%, reserva130000 EUR, con ventaja objetiva prevista de3.12 EUR frente a la mejor cobertura distinta. Las reservas varían entre45000 y130000 EUR; los tres históricos seleccionan60000 EUR. La política puede responder a probabilidades distintas, pero el resultado original no muestra ahorro. No se demuestra invariancia global por evaluar solo vértices con reoptimización.

El margen de objetivo frente a otra cobertura en la distribución histórica es559.08,488.14 y430.95 EUR en2024,2025,2026. Los cambios de reserva cercanos tienen diferencias mucho menores. Esto explica por qué se observa algo de variación en reserva de CNN1D sin alteración de cobertura.

Siguiente protocolo exploratorio fijo antes de ejecutarlo: financiación anual{1%,5%,10%}, penalización de déficit{.25,1,2}, coste cobertura{10,50,100} puntos básicos. Publicar las27 combinaciones para todos los comparadores; no elegir retrospectivamente la que favorezca CNN. Las cifras son escenarios hipotéticos de sensibilidad, no costes de negocio verificados. Mantener exposición, límite de cobertura y presupuesto originales, añadiendo referencia determinista hp1,hf0,R60000. Medir calibración clases/logloss/Brier antes de atribuir diferencias de capital a información aprendida. Esta matriz sigue siendo exploratoria y no sustituye una prueba prospectiva.

Para cerrar evidencia favorable faltan instrumentos negociables, costes reales y liquidez/colateral; sensibilidad/semillas y comparador EWMA/FHS; política y modelo congelados en datos no usados para diseño. Mantener resultado inicial sin alteraciones.
