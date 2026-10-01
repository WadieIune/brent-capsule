# Representación visual y contrato científico: CNN → escenarios → capital

Fecha: 2026-10-01. Autor: investigador sugerente delegado. Estado: implementación
aislada y pruebas sintéticas; no hay evidencia de ventaja económica de CNN.
Archivos propios: `/tmp/cnn_capital_images.py`, `/tmp/test_cnn_capital_images.py`.
No se han editado archivos del repositorio ni de otros agentes.

## Decisión propuesta y frontera con el supervisor

El supervisor implementa escenarios, política de cobertura y reserva monetaria.
Este módulo entrega una representación determinista de exactamente el mismo
pasado que reciben los comparadores. Una imagen no añade información a sus
series de origen: se contrasta si su estructura facilita aprender dependencias.

Hipótesis: a idéntica exposición, datos y techo de presupuesto, el modelo visual
reduce el coste realizado de cobertura + financiación + déficit frente al mejor
comparador elegido en validación pasada, manteniendo calibración de riesgo.
No se considerará éxito una reducción aislada de la reserva o del ES previsto.

## Entradas y API

`fit_scaler(data, train_end_exclusive)` recibe una matriz tiempo × variables y
ajusta mediana y escala IQR/1.349 solo en el prefijo de entrenamiento. Si el IQR
es nulo usa desviación típica de entrenamiento y, si también es nula, 1. Una
variable totalmente ausente en entrenamiento permanece deshabilitada hasta el
siguiente reajuste. La API hace explícito el corte; el llamador debe pasar el
corte del fold correcto y no el del dataset completo.

`transform_window(data, scaler, decision_index, window=64)` solo accede a
`[decision_index-window+1, decision_index]`. Devuelve:

- `images`: tensor float32 `(3F,L,L)`; por variable, GASF, GADF, máscara de pares.
- `normalized_window`: z robusto `(L,F)` y `valid_window`: máscara booleana.
- `bounded_window`: transformación fija del z a [0,1].
- Fracción de ausentes y de saturación por variable; corte de ajuste y decisión.

Normalización: `z=(x-mediana_train)/escala_train`, `u=(1+tanh(z/3))/2`.
No hay min/max por ventana: no se elimina el nivel absoluto de riesgo entre
ventanas. La saturación de tanh pierde resolución en extremos; se registra
`|z|>9` y se analiza como limitación, nunca se recalibra usando test. Para un
contraste estrictamente de representación, todos reciben u y máscara; un segundo
contraste permite z a todos (con canal adicional explícito para CNN visual).

Para `phi=arccos(u)`, GASF(i,j)=cos(phi_i+phi_j) y
GADF(i,j)=sin(phi_i-phi_j). En [0,1], la diagonal de GASF permite reconstruir u,
salvo precisión numérica. La tercera capa identifica pares realmente observados.
Las celdas no disponibles se ponen a cero y siempre llevan máscara cero: cero
no se interpreta como observación. El helper no interpola ni hace forward-fill.

Variables iniciales sugeridas: retornos Brent USD y EURUSD (USD por EUR),
log-varianza retrospectiva de ambas, productos cruzados o correlación móvil,
y edades de disponibilidad. Cada derivación debe ser unilateral y respetar
sesiones sin cotización; no convertir un precio obsoleto en retorno observado 0.
No incluir indiscriminadamente niveles de precio, calendario o identificadores
que permitan memorizar episodios. Esas inclusiones necesitan ablasión explícita.

## Disponibilidad y target conjunto

El panel debe estar alineado por disponibilidad real antes de llegar al helper.
Fecha de observación no basta. Edad, máscara y fuente deben viajar con el dato.
La cotización de referencia EURUSD y el precio Brent de una fecha pueden tener
horas diferentes: la decisión debe situarse tras ambas o aplicar retrasos.

`joint_target(brent_usd, eurusd, t, horizon=10)` devuelve el vector futuro
`[log(B[t+10]/B[t]), log(FX[t+10]/FX[t])]` y el cambio exacto del coste en EUR:
`expm1(rB-rFX)`. Horizonte significa diez filas de un calendario común de sesiones
de decisión; el llamador debe declararlo. El helper rechaza cotizaciones endpoint
ausentes/no positivas y etiquetas sin madurar. No rellena precios futuros.

Para un importador de Q barriles, el coste inicial es Q*B[t]/FX[t] y su incremento
futuro exacto es ese coste multiplicado por `expm1(rB-rFX)`. No sumar simplemente
retorno petróleo menos retorno divisa: se perdería el término no lineal conjunto.
La reserva objetivo cubre la pérdida residual después de una cobertura con P&L
y unidades declarados. Esto es capital económico interno y presupuesto de
cobertura; no capital regulatorio. Sin instrumentos/costes negociables auditados,
la ejecución spot es idealizada y los ahorros son del modelo estilizado.

## Comparadores y escenarios

Mismos folds, ventanas, variables, máscaras, escalado, escenario/prototipos,
optimizador, costes, restricciones y recursos de búsqueda:

1. Distribución histórica / modelo de volatilidad como referencia económica.
2. Ridge/logística multiclase sobre ventana completa aplanada u + máscara.
3. CNN 1D temporal con u + máscara; misma historia, capacidad razonable comparable.
4. CNN 2D GASF/GADF + máscaras, mezcla entre variables por canales.

Un tabular de resúmenes es útil, pero insuficiente como único adversario.
Los ejes de cada imagen GAF son tiempo × tiempo; los activos van en canales,
evitando fingir una vecindad espacial natural entre instrumentos.

Si se usa k-means, ajustar prototipos solo con targets de entrenamiento maduros;
escalar ambos componentes del target con entrenamiento para evitar que la mayor
volatilidad de Brent borre USD. No asignar mayor veracidad a clases visualmente
atractivas. Predicciones probabilísticas calibradas solo en validación pasada.
Escenarios no son solo centroides: éstos eliminan colas y dispersión intra-clase.
Preferir trayectorias históricas dentro de cada clase ponderadas por p(clase)/n.
Cada clase debe contener observaciones, y la suma total de pesos debe ser 1.
Usar un suelo común de peso histórico/estrés fijado antes del test para no borrar
escenarios extremos. Ajustar estrés no es una ventaja exclusiva de CNN.

## Evaluación y controles de fuga

Separar entrenamiento, validación, test cronológicos y exigir que toda etiqueta
usada haya terminado antes de su fecha de ajuste. Purga de diez sesiones como
mínimo entre etiquetas y el siguiente bloque; no basta separar las fechas origen.
Primera política cada diez sesiones: evita multiplicar presupuesto por ventanas
diarias superpuestas. Después, para operación diaria, contabilizar posiciones
vivas y reserva compartida de forma explícita.

Reservar QLIKE/errores probabilísticos como diagnósticos; principal es coste
realizado predefinido: cobertura/transacciones + financiación de reserva +
penalización de déficit. Reportar gasto, reserva, déficit, cola residual y
liquidez por episodio, más sensibilidad predefinida a costes. Menor reserva no
es éxito si aumentan incumplimientos. Comparar frontera riesgo/coste cuando el
gasto realizado no sea idéntico pese compartir techo de presupuesto.

Prohibidos: cuantil calculado en todo test para elegir alertas; escalado global;
selección de años favorables tras verlos; elegir número de clusters/imagen con
test; llamar OOS confirmatorio a 2026 después de adaptar el diseño a ese episodio.
Reutilizar forecasts requiere hashes de código, panel, configuración y folds.
No estimar IC ingenuo tratando pérdidas de diez días superpuestas como iid.

## Verificación ejecutada

Comando: `/home/wadie/Escritorio/brent-capsule/.venv/bin/python /tmp/test_cnn_capital_images.py`.
Resultado: 5 pruebas superadas. Cubren invariancia al futuro y corte de escalado;
dimensión/simetría GASF/antisimetría GADF e inversión de diagonal; máscaras y
variables ausentes en train; escala constante y retención de amplitud; signo
EURUSD, término cruzado y rechazo de etiquetas no maduras. No son pruebas de
rendimiento predictivo ni certifican la disponibilidad temporal del panel.

## Puntos de convergencia para revisión del optimizador

- Escenarios con sus colas empíricas, no únicamente centroides k-means.
- Convención EURUSD = USD por EUR y P&L de coberturas dimensionalmente comprobado.
- Reserva en EUR y financiación anual prorrateada al horizonte real.
- Penalización de déficit fija ex ante; sensibilidad comunicada sin escoger ganador.
- Separar prima, transacción, nocional y caja de margen.
- Criterio de aceptación medido en pérdida realizada, no en riesgo estimado propio.

## Challenge del primer optimizador del supervisor

Lectura de `/tmp/risk_director_capital_cnn.py` el 2026-10-01, antes de ejecución.
Convergencias verificadas: escenarios empíricos completos dentro de clases,
clustering escalado por componente y ajustado en train, suelo histórico del 20%,
purga por fecha final del target, pérdida física no lineal y convención EURUSD
correctas, tasas/costes explícitos y ausencia de afirmación regulatoria.

Correcciones comunicadas al supervisor:

1. `test=all_test[::HORIZON]` reinicia las decisiones en cada año y puede solapar
   exposición/reserva entre diciembre y enero. Usar calendario global continuo o
   exigir origen posterior/igual al vencimiento de la última decisión aceptada.
   Sin corregir, no llamar no solapadas a las pérdidas ni al bootstrap.
2. La función local `images` usa tanh en [-1,1]. Sustituir por [0,1] evita perder
   el signo de ventanas constantes en GASF/GADF; mi helper ya lo implementa.
3. El IC únicamente contra histórico no acredita aporte incremental de imagen:
   añadir diferencias pareadas contra tabular completo y CNN1D, no escoger rival
   después de observar resultados. Reportar todas las comparaciones.
4. El prorrateo `10/252` es una convención de diez sesiones, no duración exacta
   cuando hay fechas ausentes. Registrar duración calendario real; decidir
   política ex ante de financiación sin usar calendarios de ausencias futuras.
5. Con ambas coberturas completas el residual es el producto cruzado
   `expm1(rBrent)*expm1(-rEURUSD)` multiplicado por exposición. Coste bajo puede
   hacer casi universal esa acción: incluir cobertura completa y reserva fija
   como políticas de control, y publicar distribución/variación de decisiones.
6. El objetivo `funding*R + 2 E[(L-R)+]` implica, si no hay techo/discretización,
   `P(L>R)=funding/2`. Con funding=0.05*10/252, equivale aproximadamente al cuantil
   99.90%, no al 95%. Miles de etiquetas muy solapadas dan poca evidencia efectiva
   de ese extremo. No llamar ES ni reserva calibrada a R; conservar sensibilidad
   predefinida a penalización/funding y declarar la resolución empírica limitada.

No he ejecutado ni alterado el optimizador. Estos puntos son revisión de diseño,
no resultados económicos. El supervisor conserva la decisión final.
