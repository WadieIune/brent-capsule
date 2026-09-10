# Risk Director: primer contraste de varianza futura

Estado: exploratorio, provisional y pendiente de auditoría cruzada. Fecha: 2026-09-10.

## Diseño ejecutado

Objetivo: media de los diez retornos logarítmicos cuadrados posteriores al cierre t.
Datos: brent_fred_daily.csv; sin reindexación ni relleno, diez intervalos observados.
Entrenamiento desde 2000; evaluación anual 2016–2026 (2026 parcial). Los datos
históricos han sido explorados antes: esto no es un test confirmatorio virgen.

Dos familias: EWMA lambda 0.94 calibrada y modelo log-HAR con retornos cuadrados
como proxy diario/semanal/mensual. No se ha implementado GARCH en esta entrega.
La familia base se elige con QLIKE en 252 observaciones de validación anteriores
a cada año. Después se reajusta con etiquetas disponibles antes del test. Se
exige label_end < inicio del tramo tanto en validación como test: diez filas
purgadas antes de cada corte. Escalado y ajuste usan únicamente entrenamiento.

La corrección multiplicativa se estima directamente con QLIKE y penalización
L2 fija 0.01, sin buscar parámetros en test. Se conserva la familia seleccionada
al añadir pendiente normalizada, R², ancho relativo y posición residual de un
canal OLS sobre 32 cierres. Esta geometría explícita sobre cierres sin suavizado
no reproduce las etiquetas ni la representación CNN. Ambos modelos se comparan
sobre las mismas fechas. Los pronósticos por familia también se guardan.

## Resultado

2.651 pronósticos. Delta QLIKE (geometría menos base): **+0.018320**, es decir,
peor pérdida media. Mejora en 4 de 11 años, incluido 2026 parcial en el denominador.

| Longitud bloque | IC percentil 95 % del delta |
|---|---|
| 10 | [-0.010074, +0.054497] |
| 20 | [-0.015525, +0.060501] |
| 60 | [-0.011259, +0.064275] |

Bootstrap de bloques móviles, 2.000 réplicas, semilla 1729. Intervalos puntuales,
condicionados a los modelos ajustados; no corrigen búsqueda histórica ni prueban
equivalencia. No hay evidencia suficiente de mejora de esta geometría sobre el
baseline elegido. No es un resultado sobre CNN ni sobre toda geometría posible.

QLIKE se implementa como log(h)+y/h, equivalente para comparaciones pareadas a
las formas con términos que dependen solo del objetivo. Referencia:
https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf
La robustez de la pérdida no elimina supuestos sobre la calidad del proxy.

## Contrato pendiente para CNN

Aportar para cada fecha de cierre dos probabilidades independientes (sin imponer
suma uno), inicio/fin de ventana de entrada, identificador/hash del modelo,
backbone y transformaciones, y último dato/etiqueta usado en ajuste y selección.
Todo componente entrenado debe preceder estrictamente al inicio del bloque
correspondiente. Para entrenar el corrector, obtener también probabilidades
históricas mediante cross-fitting temporal; no puntuar entrenamiento con una
CNN que haya visto su futuro. Si se usa backbone externo fijo, documentar origen,
fecha y ausencia de adaptación sobre test. Rechazar fechas duplicadas, valores
fuera de [0,1], ventanas posteriores a t y procedencia incompleta.

Evaluar base, base+geometría, base+CNN y base+geometría+CNN en exactamente la misma
intersección de fechas y recalcular los baselines en ella. Seleccionar/tunar solo
en validación purgada. El criterio económico mínimo queda sin fijar: los resultados
actuales son diagnósticos, no un gate de despliegue. Antes de evaluar CNN, congelar
ese criterio y los contrastes primarios. No alterar límites internos con esta
primera evidencia. No confundir el segundo momento previsto con ES, capital ni
varianza agregada a diez días sin modelar las covarianzas entre retornos.

## Reproducción

Desde track-b:

```bash
/home/wadie/Escritorio/brent-capsule/.venv/bin/python code/applications/experiments/regime_forward_variance.py --prices data/brent_fred_daily.csv --out results/regime_forward_variance
/home/wadie/Escritorio/brent-capsule/.venv/bin/python -m pytest code/applications/test/test_regime_forward_variance.py -q
```

Artefactos: results/regime_forward_variance/{forecasts.csv,per_year.csv,summary.json}.
El JSON conserva hashes de datos/código, decisiones por año y fechas máximas de
etiquetas de entrenamiento. La comunicación inicial a A quedó a cargo del usuario. La coordinación posterior
se registra en `2026-09-10-B-plan-CNN-info-Risk-Director.md`.
