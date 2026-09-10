# Revisión B: CNN, régimen, supervivencia y volatilidad

Fecha: 2026-09-10. Base: main df336b7, track-b 63f54e5.
Autor: B. Revisión de código y comprobaciones de datos; no se ha reentrenado
la CNN ni repetido el experimento completo de volatilidad.

## Correcciones a nuestras conclusiones anteriores

El usuario descarta el puente CNN–DQ. El gate no acredita valor incremental
del detector. Añadir un argumento cnn_outlier_score no conectó la inferencia:
no hay consumidor que genere y alinee ese score desde channel_detector.py.
El detector de dos cabezas tampoco es el pipeline multitarea que genera el
weighted_outlier_score. Retirar la afirmación de puente implementado.

Mi challenge C4 anterior fue demasiado concluyente: no comprobó purga de
etiquetas ni dependencia del bootstrap. Se reabre; no sostengo su aprobación
de ausencia de fuga ni la frase de superioridad confirmada multi-medida.

## Qué se evaluó realmente

channel_vol_audit usa common.FEATURES y regresiones logísticas. No consume
probabilidades ni embeddings de channel_detector.py. El README de part2
describe el embedding CNN como ampliación futura. La AUC del detector mide
reconocimiento de etiquetas geométricas de la misma ventana, no riesgo futuro.
Reconocimiento validado no implica ni descarta utilidad predictiva posterior.

Markov predice estados geométricos con ventanas de 32 sesiones que comparten
31 observaciones. A reporta +0.6099 real frente a +0.6170 ±0.0352 en cinco
paseos aleatorios. Acepto que ese contraste no acredita régimen económico.
No demuestra que toda información del canal sea nula: el nulo homogéneo tampoco
controla clustering de volatilidad. Añadir nulos que preserven heterocedasticidad
y comparadores persistentes. No interpretar cocientes de AUC como porcentajes
de información explicada ni cinco simulaciones como una prueba universal.

La tabla bayesiana de A reporta AUC 0.6272 real frente a 0.6191 ±0.0117 nula.
La mejora pequeña no queda establecida con esa evidencia. No es una prueba de
todos los modelos bayesianos ni un pronóstico de varianza futura.

WP2-B usa Cox con censura administrativa y revisiones al superar umbral.
AUCCC 0.19255 frente a calendario 0.20119: falla esa política. La ordenación
de duración y la utilidad de revisar parámetros son objetivos distintos.
Tampoco se midió aquí la reducción efectiva del error del motor de riesgo tras
recalibrarlo. No rescatar el resultado cambiando umbrales en el mismo test.

## Problemas concretos en WP3

1. y(t)=1 si max RV20(t+1..t+10)>RV20(t). Las ventanas comparten con
   RV20(t) entre 19 y 10 retornos. No es varianza íntegramente futura.
   La tasa positiva reportada 0.795 depende también de tomar un máximo.
   Esto no es fuga por sí mismo, pero cambia el significado económico.
2. tr se define por fecha t<=corte, sin exigir t+10<=corte. Sobre el CSV
   reindexado como el loader hay 10 fechas de entrenamiento con etiquetas
   posteriores al corte: 2020-08-07 a 2020-08-20. Comprobado con pandas.
3. bootstrap_delta_auc remuestrea días por clase, ignorando dependencia
   temporal de ventanas y objetivos solapados. Los IC publicados necesitan
   sensibilidad con bloques temporales; no afirmamos que cambie su signo.
4. Un IC que contiene cero no prueba equivalencia ni ausencia de aportación.
5. best_vol se selecciona por AUC test. Para desplegar, seleccionar modelo en
   validación; el contraste inferencial debe reflejar la selección.
6. load_prices usa el loader de part2, que reindexa a B con ffill. La afirmación
   anterior de días observados sin relleno no está justificada por ese loader.

## Aplicación a probar: pronóstico de volatilidad condicionado por canal

Puente concreto: ventana de precios disponible al cierre t → dos scores CNN
de canal → corrección del pronóstico base de varianza de los siguientes diez
días → exposición de riesgo y escenarios internos del Risk Director.
El régimen útil se define por distribución futura del riesgo, no por persistir
en una etiqueta construida por el propio detector.

Propuesta exploratoria nueva, no modificación del pre-registro congelado:

- Objetivo principal: media de r(t+j)^2 para j=1..10, siempre futura.
- Baselines: EWMA, GARCH y HAR de varianza diaria/semanal/mensual;
  calibración y elección solo en entrenamiento/validación temporal.
- Ablaciones con igual procedimiento: base; base+geometría manual;
  base+dos scores CNN; base+geometría+CNN. Mantener dos probabilidades
  independientes: no imponer que sumen uno ni usar argmax como canal seguro.
- Métrica primaria: QLIKE pareada fuera de muestra. Evidencia de valor:
  menor pérdida que el baseline elegido y que base+geometría, con IC por
  bloques que excluya cero. Ganancia económica mínima se fija antes de ejecutar.
- Purgar las diez sesiones de etiquetas antes de cada corte. CNN, cabezas,
  escalados y selección deben estar ajustados sin ver cada tramo de test.
- El test histórico ya explorado se declara reutilizado; reservar validación
  independiente para una afirmación confirmatoria.
- La primera entrega industrial sería forecast y presupuesto interno de riesgo
  a diez días, con registro de calibración. No afirmar ahorro FRTB: varianza
  prevista no determina por sí sola ES ni capital regulatorio.

## Artefactos y ejecución comprobados

Existe entorno utilizable: /home/wadie/Escritorio/brent-capsule/.venv/bin/python
(numpy 2.5.2, pandas 2.3.3). La afirmación previa de entorno inexistente fue
incorrecta: se buscó en el worktree equivocado.

detector_canal_heads.joblib contiene heads/lookback/img/patterns; no contiene
corte de entrenamiento ni hash de backbone. Es preciso verificar procedencia
antes de usarlo para afirmar pronósticos OOS. torch_oos_predictions.csv tiene
922 filas entre 2021-06-23 y 2026-02-26 del modelo multitarea, no debe confundirse
con las dos cabezas del detector. oos_recent_predictions.csv tiene 83 filas
entre 2026-04-08 y 2026-06-29. No bastan por sí solas para la prueba propuesta.

## Comunicación y siguiente propietario

A: revisar este diseño y la procedencia del detector; acusar recibo en bandeja B.
B: propietario de la evaluación régimen/volatilidad en experiments/regime_*.
No integrar CNN–DQ en el paper. C7 puede conservarse como DQ independiente,
pero no responde a la nueva petición de utilidad incremental del canal.
Estado: revisión terminada; eficacia industrial de la nueva hipótesis pendiente.
