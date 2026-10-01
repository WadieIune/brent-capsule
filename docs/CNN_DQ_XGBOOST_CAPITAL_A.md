# Auditoría y propuesta: CNN-DQ → datos depurados → XGBoost → capital

Fecha: 2026-10-01. Investigador sugerente delegado. Lectura directa del repositorio
`/home/wadie/Escritorio/brent-capsule`. No se han modificado sus archivos ni se ha
recalculado el resultado publicado13,4%. Este documento distingue implementación,
evidencia heredada e hipótesis pendientes.

## Conclusión ejecutiva

La cadena propuesta es una hipótesis productiva, pero no está demostrada ni
implementada de extremo a extremo. La ruta DQ-capital actual no utiliza CNN;
el XGBoost localizado estima supervivencia/clasificación de canales, no capital.
El13,4% heredado es una diferencia retrospectiva de un proxy calculado sobre dos
paneles tratados de forma distinta. No acredita ahorro regulatorio ni ventaja de
CNN, y presenta confusores que deben resolverse antes de atribuirlo a depuración.
Depurar puede aumentar una reserva insuficiente: capital más bajo no equivale a
mejor resultado. La utilidad es reducir error de riesgo y coste real a protección
comparable, no minimizar mecánicamente el capital estimado.

## Evidencia de código

| Componente | Evidencia localizada | Estado comprobado |
|---|---|---|
| DQ → proxy capital | `code/applications/experiments/dq_capital_impact.py`, `sanitize`, `var_and_capital`, `run` | Implementado mediante reglas y VaR histórico |
| CNN → DQ | `docs/hallazgos/2026-09-10-A-la-CNN-no-interviene-en-calidad-de-dato.md` y lectura actual de `sanitize` | No interviene en esa aplicación |
| XGBoost supervivencia | `code/part2_channel_survival/channel_survival.py:343`, `:442`, `:594` | `survival:aft` y `XGBClassifier`; objetivos de canal |
| XGBoost capital | Búsqueda `XGBRegressor`, `XGBClassifier`, `survival:aft`, `reg:quantile`, imports xgboost en todos los `.py` de `code` | No localizado |
| CNN visual → escenarios → reserva | `code/applications/experiments/risk_director_capital_cnn.py` | Implementación exploratoria independiente; no es DQ ni XGBoost |

La auditoría histórica afirma cero imports torch en la antigua ruta DQ. Mi
conclusión actual es más acotada y robusta: la función de depuración usada para
comparar capital no ejecuta ninguna CNN. Imports globales que otros módulos
puedan hacer no demuestran intervención causal de una red en esa depuración.

`sanitize` hace exactamente: copia el panel, enmascara precios<=0, elimina filas
cuyo cambio absoluto agregado es0 y elimina ausentes. Ni siquiera llama al
detector geométrico más elaborado: llamar a esa salida `tras_control_geometrico`
no identifica una intervención de dicho detector en esta función.

## Objeciones materiales al resultado heredado

1. **Precio negativo real frente a defecto.** El propio módulo reconoce la
   liquidación negativa WTI de2020 y la elimina por<=0. Un dato genuino no pasa
   a ser erróneo porque una transformación no lo soporte. Hace falta instrumento,
   contrato y P&L consistentes que admitan ese evento; no imputarlo como corrupción.
2. **Transformación extrema artificial.** `common.py:130-132` implementa retornos
   como `diff(log(clip(prices,1e-9,None)))`. Un precio negativo se convierte en
   epsilon: comparar esa ruta con excluirlo no aísla calidad de dato, también
   cambia la representación de un evento genuino.
3. **Calendario/target distintos.** Cada rama construye su propia secuencia de
   retornos y ventana250. Una puede contener fines de semana rellenados y otra
   sesiones eliminadas. Así cambian frecuencia, horizonte económico, muestra
   evaluada y cantidad de historia. Se necesita calendario de decisión y verdad
   económica comunes para medir el efecto de la información, no dos problemas.
4. **Primera fila eliminada mecánicamente.** `out.diff().abs().sum(axis=1)==0`
   devuelve0 en la primera fila (todos NaN sumados), que se cuenta como relleno.
   La misma reducción puede confundir filas con diferencias no observadas.
5. **Observación no equivale a cambio.** `rfet_audit` considera real solo
   `s[s.diff()!=0]`; una nueva cotización idéntica puede ser observación real, y
   un cambio espurio no certifica observación válida. Cuenta medias anuales y
   bloques90D separados, no una auditoría completa basada en procedencia y todos
   los intervalos relevantes. No certifica elegibilidad regulatoria.
6. **Capital ex post.** `var_and_capital` usa excepciones de todo test para elegir
   un multiplicador y multiplicarlo por VaR medio del mismo test. Es un resumen
   retrospectivo, no reserva disponible antes de cada pérdida ni cálculo
   regulatorio completo. No atribuir ahorro desplegable a ese agregado.
7. **Fuente distinta del panel integrado.** `load_commodities` busca el dataset
   wide mediante su propio localizador; no consume necesariamente el panel
   extendido oficial pasado al nuevo optimizador. Puede recurrir a sintético si
   falta serie. Toda reproducción debe registrar fuente efectiva, rango y hash.

Estas observaciones no demuestran que la calidad de datos carezca de impacto;
impiden atribuir limpiamente el número heredado a la CNN o a ahorro de capital.

## Experimento de atribución: factorial2×2

Primero separar los dos beneficios sin meter una CNN inexistente en la historia:

| Datos disponibles al pronosticar | Modelo base de riesgo | XGBoost de riesgo |
|---|---|---|
| Flujo contaminado controlado D | D,B | D,X |
| Referencia depurada verificada C | C,B | C,X |

La referencia C debe basarse en procedencia/calendarios/cotización auditada;
no significa simplemente eliminar todos los precios atípicos. Mantener idénticos
calendario, exposición, targets futuros verificados, fechas de evaluación,
escenarios, política y costes. Contaminar las entradas observables (y por separado
las etiquetas históricas de entrenamiento si ésa es otra hipótesis), **nunca la
verdad de evaluación**. Inyectar la misma realización de defectos en B y X.

Sea J coste realizado (menor mejor). Definir:

- Efecto DQ con baseline: `J(D,B)-J(C,B)`.
- Efecto modelo sobre datos depurados: `J(C,B)-J(C,X)`.
- Ganancia total de la secuencia: `J(D,B)-J(C,X)` (suma exacta de esos dos).
- Interacción: `[J(D,B)-J(C,B)]-[J(D,X)-J(C,X)]`.

La interacción evita declarar aditividad universal de beneficios que dependen de
la robustez del modelo. Repetir por familias y severidades de defecto prefijadas,
semillas comunes y episodios reales de estrés que deben conservarse íntegros.

Para aislamiento operativo inicial, XGBoost puede ser `XGBClassifier` que estime
las mismas probabilidades de seis clases futuras petróleo/USD y alimente la
misma biblioteca de escenarios/optimizador. Es una nueva aplicación por construir;
reutilizar una librería instalada o la clase de supervivencia no equivale a tener
el modelo entrenado para capital. Ajuste temporal y calibración en validación,
con idénticas entradas y presupuesto de búsqueda frente al baseline/tabular.

## Segundo experimento: demostrar o descartar CNN-DQ

Solo después de definir C y D, comparar pipelines de reparación aplicados al
mismo D: sin reparar; reglas de calendario/procedencia/rachas y estadísticos
robustos; control geométrico existente; detector tabular; CNN-DQ propuesta; y
referencia C como techo informativo, no método desplegable.

Una CNN-DQ real necesita:

- Entrada visual de la ventana disponible hasta la decisión, máscaras y contexto
  de instrumento/fuente. Etiquetas verificadas de defecto, no de volatilidad alta.
- Salida por registro: probabilidad/tipo de defecto y confianza, con acción de
  cuarentena o sustitución mediante fuente autorizada. Detectar no proporciona
  mágicamente el precio correcto.
- Reparación causal común a todos los detectores: una diferencia en el mecanismo
  de reconstrucción no debe atribuirse a detección CNN. Si se necesita el día
  siguiente para ver una reversión, registrar esa latencia y su impacto real.
- Presupuesto idéntico de revisiones/falsos positivos, umbrales aprendidos solo
  con pasado, y validación en familias/episodios no memorizados.

La comparación decisiva es reglas+CNN contra reglas fuertes con el mismo modelo
de riesgo downstream, primero B y después X. El efecto incremental debe aparecer
tanto en detección/reparación como en error de riesgo/coste; que XGBoost mejore
capital no prueba que la CNN haya limpiado mejor.

## Objetivos, métricas y puertas de avance

Target financiero: pérdida futura exacta de diez sesiones de una exposición
concreta y verificable; petróleo/USD para importador es candidato existente.
El capital económico o reserva se decide antes de la pérdida. VaR/ES estimado
se valida por cobertura/calibración y coste; no llamar regulatorio al proxy.

Métricas DQ: precisión/recall por familia a igual carga de revisión, latencia,
error de reparación y tasa de borrado erróneo de shocks genuinos. Distinguir
faltante, duplicado y precio real repetido. Métricas financieras: puntuación de
distribución, error de riesgo frente al objetivo común, déficit, pérdidas de cola,
reserva y coste total incluyendo revisión/reparación y retrasos operativos.

Puerta1: demostrar referencia limpia y calendario causal. Puerta2: implementar
factorial y comprobar contribuciones DQ/modelo separadas. Puerta3: introducir
CNN-DQ solo con evidencia incremental contra reglas fuertes. Puerta4: evaluar
cadena completa en tramo no utilizado con relevancia económica predefinida.
Si CNN no supera reglas, conservar reglas+XGBoost si éste aporta; no atribuir a
CNN el beneficio de toda la cadena para justificar su presencia.

Las cifras/claims heredadas se mantienen como antecedentes pendientes de nueva
atribución. Este documento propone pruebas falsables, no una ventaja ya obtenida.
