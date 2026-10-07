# Comparación descriptiva de rendimientos y referencia normal

- **Objetivo:** auditar el supuesto de normalidad asociado a bandas ±3σ; no
  estimar capital ni etiquetar automáticamente extremos como errores.
- **Fuente:** `data/panel_extendido_2026-09-09.csv`, precios y FX, 2007–2026.
- **Código:** `code/applications/experiments/dq_return_distribution_comparison.py`.
- **Figura:** `results/reports/dq_return_distributions/empirical_vs_gaussian_returns.png`.
- **Métricas:** `results/reports/dq_return_distributions/distribution_metrics.json`.

## Método

Se calculan rendimientos logarítmicos diarios entre precios positivos
consecutivos por serie, se estandarizan con media y desviación muestrales de
todo el histórico y se comparan en Seaborn con una normal estándar. La figura
marca ±3σ. El estadístico de comparación es la frecuencia empírica
`|z| > 3` frente a la probabilidad bilateral normal (`0,26998%`).

Es un **diagnóstico descriptivo de muestra completa**, con look-ahead por la
estandarización ex post; no es un umbral desplegable. Para evaluar alertas, la
normalización debe estimarse causalmente en train/ventana previa y el umbral
validarse en un periodo independiente. Activos con precios no positivos no
generan log-rendimientos sobre esos días; no se interpolan.

## Resultado

En las nueve series incluidas (BRENT, WTI, GOLD, SILVER, COPPER, SP500, DAX,
EUROSTOXX50, EURUSD), la frecuencia empírica fuera de ±3σ es 1,14%–1,64%,
aproximadamente 4,2–6,1 veces la referencia gaussiana. Todas tienen curtosis
excesiva positiva; el detalle por instrumento y fechas válidas está en el JSON.
La distribución empírica muestra un centro más concentrado y colas más pesadas
que la normal ajustada en estas series.

Esto significa que la regla normal de ±3σ **subestima la frecuencia de
observaciones extremas bajo estos datos**. No permite inferir que la distribución
gaussiana “sobreestima capital”: no se calcula capital aquí, y la dirección de
un sesgo prudencial requiere cartera, horizonte, posiciones y metodología
explícitos. Además, episodios de mercado legítimos, cambios de régimen, errores
de fuente y eventos corporativos pueden contribuir todos a las colas.

## Relación con IA y siguiente prueba

Una gráfica de densidad no demuestra que CNN/XGBoost mejoren precisión ni separa
un error DQ de un movimiento real. Esa mejora se prueba con etiquetas conocidas
y test temporal: sensibilidad/recall y FPR por familia, precisión bajo
prevalencia realista, intervalos y controles negativos de eventos legítimos.
El stack DQ existente es exploratorio y no permite una conclusión general; el
piloto confirmatorio de canal tampoco demuestra superioridad de IA.

Siguiente experimento: construir el benchmark causal móvil de 3σ y reglas
robustas por tipología; fijar contaminación/incidentes en train y validación;
comparar alertas de capa 1 frente a capa 1 + canal/XGBoost en test OOS. Reportar
cuánto cambia la distribución de rendimientos tras una corrupción conocida y
si el sistema identifica correctamente ese tramo, sin corregir ni excluir
observaciones automáticamente.
