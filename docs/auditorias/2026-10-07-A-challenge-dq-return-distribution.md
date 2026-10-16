# Challenge — distribución de rendimientos y distorsión por gate

## Veredicto

La comparación Seaborn de rendimientos empíricos frente a una normal ajustada
es descriptiva y útil como motivación: las colas históricas superan la
frecuencia gaussiana fuera de ±3σ. No prueba por sí sola que 3σ sea un detector
DQ malo ni que un modelo de IA aumente precisión. La evidencia para la segunda
afirmación debe venir de defectos etiquetados y test OOS.

## Problemas en «distorsión corregida»

El script `dq_return_distribution.py` y el reporte asociado calculan
`(1 - recall) × Wasserstein(clean, corrupted)` y llaman al complemento
«distorsión corregida»/«ganancia de precisión». Esa cantidad es una **simulación
de residual bajo el supuesto de corrección perfecta tras cada alerta**. El
pipeline no corrige realmente las series ni vuelve a medir la distribución
corregida; detección y corrección son problemas distintos. El nombre «precisión»
es incorrecto: no se calculan precision/PPV ni falsos descubrimientos a una
prevalencia defendible.

Además:

- Distorsión y recall no están calculados sobre las mismas ventanas: Wasserstein
  promedia 40 episodios elegidos de un test, mientras recall viene del stack
  completo y sus escenarios. Se multiplican agregados no pareados.
- El test tiene 124 ventanas solapadas 75%; no son observaciones independientes.
- Los gates comparados tienen FPR distintas (aprox. 3,2%, 8,1%, 8,3%); la
  diferencia no aísla el valor incremental del modelo.
- La métrica estandariza por separado la ventana limpia y cada corrupta usando
  media/desviación muestral de todo el tramo. Esto elimina parte de los cambios
  de nivel/escala y usa futuro; solo describe forma residual, no una métrica
  causal online.
- La media uniforme sobre familias y modos no representa incidencia real. Las
  corrupciones sintéticas ocupan una fracción pequeña del test; el porcentaje
  relativo de mejora puede parecer grande sobre una variación absoluta pequeña.
- La garantía de calibración conformal no es «cualquiera que sea la forma» sin
  supuestos: dependencia, drift, ventanas solapadas y calibración deben tratarse
  explícitamente. La FPR realizada reportada tampoco es igual entre gates.

## Uso permitido

Paneles A-C de la figura de Brent (densidad/log, QQ, frecuencia de cola) pueden
quedar como diagnóstico descriptivo, siempre acompañados de fechas, tamaño de
muestra y advertencia de no estacionariedad/look-ahead. La figura de nueve
activos en `results/reports/dq_return_distributions/` es la comparación
multi-activo preferida para esta entrega.

El panel D y porcentajes de distorsión corregida/gain de precisión quedan fuera
del paper. No citar el «80%» ni conclusiones equivalentes. Para reabrirlo:
usar test temporal no solapado, fijar prevalencia/severidad antes del test,
parear las mismas inyecciones y alertas, emparejar FPR con incertidumbre y
simular una política de corrección explícita con su error residual; reportar
Wasserstein/quantiles/kurtosis en unidades absolutas además de la métrica
relativa. La precisión debe calcularse como PPV sobre prevalencia de incidentes
justificada y contrastarse en datos reales etiquetados cuando existan.
