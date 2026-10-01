# Protocolo conjunto: CNN visual y capital económico

Estado: hipótesis experimental; no ventaja demostrada. Supervisor B; investigador sugerente shock_research. Fecha: 2026-10-01.

## Aplicación prioritaria

Empresa consumidora de petróleo con compras en USD y caja en EUR. Exposición física fija, horizonte de diez sesiones. La decisión conjunta es cobertura de petróleo/divisa y reserva de liquidez. Una reducción de la reserva prevista solo cuenta como eficiencia si mantiene cobertura de pérdidas realizadas y respeta límites de liquidez/colateral.

## Hipótesis

A igual exposición, información disponible, coste/presupuesto de cobertura y procedimiento de optimización, una CNN de imágenes construidas con historia pasada reduce pérdidas residuales de cola o déficits de reserva frente a EWMA/FHS, modelo tabular y CNN temporal 1D. No se presume que la imagen añada información a las series de origen.

## Representación y objetivo

Ventanas pasadas de 64 observaciones: retornos, semivarianza, log-varianza, Brent/WTI, USD/EUR y spreads; máscaras y edad de datos. Comparar GASF/GADF con representación numérica temporal. Mantener nivel y escala absoluta de riesgo como variables explícitas: la normalización de imagen no debe borrar amplitud. Normalizadores ajustados solo en train.

Objetivo: escenarios conjuntos de cambios futuros y pérdidas de la exposición a diez sesiones; probar escenarios de trayectoria para colateral. Una clasificación de canal no basta. La CNN entrega probabilidades/pesos de escenarios; el mismo optimizador transforma todos los modelos en acciones bajo restricciones idénticas.

Evitar asumir vecindad entre activos en una imagen: probar órdenes predefinidos/permutaciones o usar CNN temporal compartida por activo con agregación explícita.

## Decisión

Optimizar cobertura discreta de petróleo y divisa bajo presupuesto, límites de nocional y capacidad de colateral. Modelar P&L de instrumentos, costes, base y liquidación; no asumir que una alerta elimina un porcentaje fijo de varianza. Datos spot permiten estudio ilustrativo; decisiones con futuros/opciones requieren precios y reglas del instrumento real.

Medir dos contrastes: (1) mismo presupuesto de cobertura y reserva, comparar pérdidas/deficits; (2) mismo nivel de protección validado en pasado, comparar reserva y costes requeridos. Nunca identificar un ES previsto menor con capital liberado demostrado.

## Evaluación

Walk-forward con train/validación/test; purgar etiquetas diez sesiones y congelar transformaciones, arquitectura, calibración, umbrales y política antes del test. Fechas de publicación disponibles por variable. Costes y posiciones fijos antes de observar resultados. Presupuesto causal, sin cuantiles calculados sobre todo test.

Comparadores con idénticas entradas/ventanas y presupuesto de selección. Ablaciones: riesgo propio; +externas; +imagen; CNN 1D; imagen alterada que conserve escala y destruya forma. Reportar variación por semillas, episodios, dependencia temporal e incertidumbre. 2026 reutilizado para diseño es exploratorio; confirmación en tramo intacto o seguimiento prospectivo.

Métricas: pérdidas residuales y cola realizada, frecuencia/severidad de déficit de reserva, costes cobertura/rotación, demanda de colateral y coste de mantener reserva. Calibración y estabilidad junto a desempeño económico. Pocos shocks independientes limitan evidencia de cola.

## Pendientes previos

Corregir monitor as-of; regenerar outputs con hash vigente; cerrar normalización train-only; verificar procedencia de predicciones y correspondencia de fechas; no reutilizar forecasts sin hash. No trasladar proxy legacy k*VaR a ahorro de capital regulatorio.

## Resultado presentable

Una pantalla muestra exposición, reserva base, escenarios ponderados por CNN, cobertura candidata, coste y riesgo residual, con fecha y límites de evidencia. El rol de CNN es explícito y medible. Su inclusión experimental no implica aprobar su uso productivo.
