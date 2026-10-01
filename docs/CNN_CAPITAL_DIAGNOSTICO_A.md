# Diagnóstico independiente: CNN visual y optimización de capital

Fecha: 2026-10-01. Investigador sugerente delegado. Estado: resultado económico
nulo para CNN visual; no hay ventaja demostrada. No se han ajustado costes,
restricciones, representación ni parámetros para obtener una victoria.

## Evidencia inspeccionada

Lectura directa de `/tmp/cnn_capital_run42/summary.json`, `decisions.csv` y
`/tmp/risk_director_capital_cnn.py`. Run seed42; panel SHA256
`b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3`;
script registrado `0c1fe2469e80254f7f2fa9b45e65600340b0dd4dbda6c9fe277e412d23f43e97`.
Diagnóstico reproducible: `/tmp/cnn_capital_diagnostico_a.py`; cifras derivadas
en `/tmp/CNN_CAPITAL_DIAGNOSTICO_A.json`. No se ha alterado el optimizador.

67 decisiones entre 2024-01-02 y vencimiento máximo 2026-08-28. Todos los modelos
eligieron cobertura petróleo 100% y divisa 0%. CNN visual e histórico reservaron
60.000 EUR siempre; coste medio idéntico 1.119,047619 EUR. CNN1D cuesta 1,332623 EUR
menos por decisión debido a menor financiación de reserva; ninguna estrategia
experimentó déficit. El IC visual-histórico [0,0] describe igualdad exacta de las
acciones observadas, no ausencia universal de valor informativo.

La mayor pérdida residual observada es 26.049,93 EUR, dejando al menos 33.950,07 EUR
de holgura en la reserva visual. El coste realizado principal, en este tramo,
solo distingue primas y financiación; no llega a evaluar penalización por déficit.
La cola empírica al95% contiene únicamente cuatro pérdidas.

## Por qué la política puede ser insensible

Para cobertura fija, el objetivo continuo es
`J(R)=coste_cobertura + f*R + lambda*E[(L-R)+]`, con
`f=.05*10/252=.001984127` y `lambda=2`.
En solución interior y distribución continua, su condición de óptimo es
`P(L>R)=f/lambda=.0009920635`: reserva alrededor del cuantil99,9008%, no ES95.
Con escenarios discretos hay un intervalo de condiciones de subgradiente;
con malla de5.000 EUR y techo presupuestario la identidad es una orientación,
no igualdad exacta. Saltos de reserva discretos pueden esconder cambios modestos
en probabilidades. Con la tasa actual, un salto de5.000 EUR cuesta solo9,92 EUR
de financiación por decisión.

Los escenarios pesan `w_i=.8*q_k/n_k+.2/N`. Por tanto cada escenario histórico
conserva al menos `.2/N` y toda cola tiene probabilidad mínima igual a20% de su
frecuencia histórica. Sin restricciones/discretización, para una cobertura fija,
la condición anterior obliga a una reserva como mínimo alrededor del cuantil
histórico `1-.0009920635/.2=99,503968%`. Las probabilidades de clases de CNN no
pueden eliminar esos escenarios ni cambiar su orden relativo dentro de clase.
En los folds con N=2015,2266,2519, respectivamente10,12,13 observaciones en la
cola bastan para que su suelo supere el alpha objetivo. Muchas etiquetas de
entrenamiento de diez días se solapan: no son tantas crisis independientes.

La restricción hp+hf<=1 y la exposición importadora hacen competir las dos
coberturas. Cuando se elige hp1/hf0 el residual exacto es
`exposición * exp(rBrent) * expm1(-rEURUSD)`.
Por ello un episodio de petróleo al alza puede quedar neutralizado en gran parte
sin que aparezca déficit significativo: el test económico real se concentra en
depreciación del EUR y su interacción con el petróleo. Reconocer visualmente la
volatilidad del crudo no garantiza cambiar la decisión ni reducir ese residual.

## Prueba matemática para separar bloqueo estructural de falta de señal

Sea a una acción completa (hp,hf,R), c_a su coste+financiación y SF_a su déficit.
Como los escenarios están repartidos en seis clases, el objetivo es afín en las
probabilidades q. Para acción actual a y alternativa b:

`min_q (J_b-J_a) = c_b-c_a + .2*lambda*E_prior(SF_b-SF_a)
                  + .8*lambda*min_k E(SF_b-SF_a | clase k)`.

El mínimo es sobre el simplex completo de probabilidades. Si es no negativo para
todas las alternativas, a sigue siendo óptima para cualquier CNN que solo ajuste
esas seis probabilidades: el problema es estructural y cambiar arquitectura no
puede aportar valor de decisión dentro de ese contrato. Si es negativo para
alguna alternativa, existe sensibilidad potencial, pero aún no hay evidencia de
que CNN prediga mejor las regiones relevantes. Evaluar extremos q=e_k es un
diagnóstico de la política, no una predicción ni un parámetro elegido con test.

El supervisor implementa márgenes ganador/segundo y sensibilidad completa; esta
prueba se ha comunicado como complemento sin modificar sus archivos.

## Qué NO permite concluir 0 déficits en 67 decisiones

Incluso suponiendo iid, la cota superior unilateral95% de la probabilidad de
déficit tras0/67 es `1-.05^(1/67)=4,3728%`. No valida cobertura99,9%.
Si la verdadera tasa fuera el alpha implícito .000992, esperaríamos0,0665 déficits
y la probabilidad de observar cero sería93,566%. Cero es precisamente lo normal.
Para que una serie iid sin ningún fallo diera una cota superior igual a ese alpha,
harían falta3019 decisiones. Esto ilustra insuficiencia de evidencia: no es un
plan de esperar3019 observaciones. La dependencia y los cambios de régimen hacen
todavía menos justificable extrapolar esa garantía. Bootstrap no crea episodios
extremos ausentes. El ES empírico basado en cuatro pérdidas tampoco certifica
calibración de colas raras.

## Próxima prueba preregistrable

1. Congelar resultado actual como exploratorio/nulo. Registrar hashes y todas las
   variantes; el histórico2024-2026 ya inspeccionado no se vuelve confirmatorio.
2. Medir primero sensibilidad estructural en entrenamiento: margen entre acciones,
   proporción de decisiones con cambio posible y prueba del simplex anterior.
   Si ninguna acción responde a las probabilidades, no gastar recursos en buscar
   una CNN mejor para esa misma política.
3. Especificar exposición real: cantidad, calendario de pagos, moneda y coberturas
   negociables con sus vencimientos, costes, margen/liquidez y límites auténticos.
   Comparar también política fija hp1/hf0 y una reserva fijada solo en entrenamiento.
   La reserva60k observada en test sirve como descripción, no nuevo baseline
   supuestamente preseleccionado.
4. Registrar una matriz completa de financiación, penalización y costes respaldada
   por rangos económicos; reportarla íntegra. No elegir celda ganadora después.
   Si falta evidencia de negocio, etiquetar toda la matriz como estilizada.
5. Conservar iguales escenarios, suelos, restricciones y calibración para histórico,
   ventana completa tabular, CNN1D y CNN visual. Misma información disponible,
   selección temporal anidada y varias semillas prefijadas para estabilidad.
6. Guardar probabilidades y métricas probabilísticas por fecha (log-loss/Brier,
   calibración y puntuación multivariante apropiada), además de acciones. Hoy
   `decisions.csv` no permite atribuir igualdad de acciones a probabilidades iguales
   frente a política insensible. Separar habilidad predictiva y valor económico.
7. Congelar modelo y comparador escogido en validación para un tramo no utilizado.
   Evaluar coste económico total, déficit, caja y protección con exposición fija;
   umbral de relevancia monetaria definido por negocio antes de ver el tramo.
   Si no existe tal umbral, no inventar porcentaje de éxito conveniente.

## Criterio de avance y alternativas

Avanzar a uso operativo solo si: datos negociables y disponibilidad auditados;
política sensible dentro de límites reales; mejora económica frente al comparador
preseleccionado que exceda el mínimo de negocio, con incertidumbre favorable y sin
degradación de protección. Con67 decisiones puede ser necesario mantener conclusión
inconclusa aun si cambia la media. Mejora solo en escenarios simulados acredita
comportamiento en esos escenarios, no rentabilidad empírica.

Si la política es estructuralmente insensible, alternativas legítimas son otra
exposición genuina (importador con pagos distintos, exposición multimoneda), elección
de vencimiento con riesgo de base o reserva de liquidez por trayectoria. Requieren
nuevos datos y una nueva pregunta registrada, no manipular el problema actual.
Si la política responde pero CNN no supera ventana completa/1D, mantener esos
modelos en el Risk Director y conservar CNN como componente experimental.

Conclusión: se ha construido una conexión computacional real CNN→escenarios→
cobertura/reserva. La conexión no ha demostrado ventaja. Esta diferencia debe
mantenerse explícita ante el usuario y en cualquier informe.

## Convergencia con diagnóstico del supervisor

El supervisor comunica `/tmp/capital_policy_diagnostic/summary.json` y
`probability_vertices.csv`:21 casos (prior y seis vértices, tres folds), con
hp1/hf0 en20/21. En el vértice0 de2026 aparece hp.75/hf0 y reserva130k; la
alternativa hp1 cuesta3,115 EUR más en el objetivo de esos escenarios. Las
reservas de vértices recorren45k–130k, frente a60k del prior. Cifras comunicadas
por el supervisor, no recalculadas en mi script independiente.

Esto descarta afirmar invariancia total de la arquitectura: hay sensibilidad
posible a pesos de escenarios, especialmente en reserva. No demuestra que CNN
alcance esas probabilidades de forma calibrada ni que las acciones alternativas
ahorren dinero realizado. No seleccionar el vértice con rendimiento favorable.

Queda acordada antes de ejecutar la siguiente sensibilidad una matriz completa
de27 combinaciones: financiación anual1/5/10%, penalización de déficit.25/1/2 y
coste de cobertura10/50/100 puntos básicos. Misma matriz para todos los modelos,
tablas completas y condición central original conservada. Esta extensión es
exploratoria tras el resultado nulo; no es una confirmación independiente ni
evidencia de que esos costes representen una empresa real.

Registrar además log-loss y Brier multiclase fuera de muestra contra el prior
histórico, curvas de calibración con tamaños de muestra y, si se recalibran
probabilidades, ajuste exclusivamente en validación pasada. Mantener por separado
la mejora de clasificación de clases y la calibración de la cola monetaria: la
primera no valida automáticamente una reserva99,9%. Los datos de negocio que
faltan deben seguir identificados como faltantes; no inferirlos del backtest.
