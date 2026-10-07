# Resumen ejecutivo — framework de Data Quality para series temporales

## Objetivo

Diseñar y evaluar un framework de Data Quality para series financieras que
combine controles estadísticos contrastados con una segunda capa automática e
inteligente para apoyar al Risk Director. El éxito se mide en calidad de
detección, cobertura entre tipologías y automatización trazable; no en
rentabilidad ni en porcentajes de capital.

## Arquitectura

1. **Capa 1:** controles estadísticos y deterministas (calendario, duplicados,
   faltantes, TRIM, rachas de retornos cero, rangos, 3σ/robustos y reglas por
   instrumento).
2. **Capa 2:** canal/supervivencia como representación DQ, XGBoost para señales
   estructuradas, CNN/visión para forma temporal o de curvas y alertas
   explicables y priorizadas. Complementa la capa 1; no la reemplaza.

El modelo generativo puede apoyar escenarios sintéticos, sujeto a validar su
realismo. Millones de series y múltiples asset classes son el objetivo
arquitectónico; los pilotos aún no prueban esa escala ni generalización.

## Evidencia en curso

- Un piloto de canal con 71 ventanas OOS no establece aún superioridad de
  CNN/XGBoost: el conjunto de validación es pequeño y los controles específicos
  conservan ventajas en defectos concretos.
- En nueve series de precios/FX del panel (2007–2026), los rendimientos
  empíricos estandarizados fuera de ±3σ se sitúan entre 1,14% y 1,64%, frente al
  0,27% de referencia normal. Esto describe colas más pesadas, no distingue por
  sí solo un error DQ de un evento real. Véase la [figura de distribuciones](../results/reports/dq_return_distributions/empirical_vs_gaussian_returns.png)
  y el [resumen numérico](../results/reports/dq_return_distributions/distribution_metrics.json).
- La mejora de IA se evalúa con defectos etiquetados, FPR/recall/precisión por
  familia, test temporal, transferencia y falsas alertas ante movimientos
  legítimos. Una gráfica de densidad no sustituye esta validación.

## Disclaimer

Se retiran las cifras previas de «capital evitado», «capital por dato» y sus
porcentajes derivados de carteras equiponderadas, nominales normalizados o
prevalencias uniformes. No representan una estimación real y no deben citarse.
El análisis se centra en distribuciones de rendimientos y desempeño DQ. Cualquier
impacto de capital queda fuera hasta disponer de posiciones/notional y una
metodología de cartera aprobados.
