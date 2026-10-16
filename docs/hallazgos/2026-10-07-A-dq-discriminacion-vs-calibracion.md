# Hallazgo · La IA sí aporta en discriminación; lo que falla es la calibración, y no por operar sobre precios

- **Autor:** A · **Fecha:** 2026-10-07 · 🟡 **provisional**, pendiente de challenge B.
- **Motivo:** el MASTER plantea que el problema puede estar en usar ventanas
  rodantes sobre **precios** en vez de sobre **retornos**, y objeta que no puede
  ser que CNN, XGBoost y supervivencia de canal no aporten valor.
- **Veredicto corto:** la hipótesis del espacio precio/retorno **no se sostiene**,
  pero la objeción de fondo **sí**: la IA aporta, y lo que estaba enmascarando su
  aportación era mezclar discriminación con calibración en la misma métrica.
- **Código:** `code/applications/experiments/dq_discrimination_vs_calibration.py`
  reproduce los §1, §4, §5, §7 y §10. **Tests:** `tests/test_dq_discrimination_vs_calibration.py` (5).
  **Artefactos:** `results/reports/dq_discrimination_vs_calibration/summary.json`.
  Los §8 (supervivencia AFT) y §11 (`asinh`) se midieron en diagnósticos aparte
  y **no están aún en el repositorio**: son negativos y no se citan como
  resultado, pero habría que portarlos si se quieren reabrir.

## 1 · La hipótesis precio-vs-retorno no se sostiene

Deriva del score limpio entre validación y test, con umbral congelado al
cuantil 95 de validación (objetivo nominal 0,05):

| control | espacio | FPR OOS | KS | valores distintos |
|---|---|---|---|---|
| **CNN 1D** | retorno normalizado | **0,169** | 0,20 | 233 |
| canal · oscilación | precio | 0,097 | 0,08 | **7** |
| cross-asset `1−R²` | retorno normalizado | 0,097 | 0,18 | 236 |
| canal · coherencia | precio | 0,089 | 0,08 | 236 |
| canal · geometría | precio | 0,073 | 0,12 | 236 |
| canal · ruptura | precio | 0,032 | 0,14 | 236 |
| 3σ | retorno normalizado | 0,032 | 0,16 | 99 |
| retícula | precio | 0,000 | 0,00 | **1** |
| vintage | precio | 0,000 | 0,31 | 99 |

Los controles que **más** derivan son los de **retorno normalizado**, no los de
precio. La CNN es el peor de los nueve: su mediana se desplaza de 0,0086 a
0,0279, un factor 3. Los controles de canal sobre precios se quedan entre 0,03 y
0,10. Cambiar de precios a retornos no arregla esto; si acaso, va en contra.

## 2 · Las tres causas reales del fallo de calibración

**(a) La muestra de calibración es demasiado pequeña para el presupuesto.** La
calibración usa **59 ventanas**. En una unión de 9 controles el presupuesto por
control es 0,05/9 = **0,0056**, mientras que la resolución de un cuantil con 59
puntos es 1/59 = **0,017**: el objetivo es **3,1 veces más fino de lo que la
muestra puede medir**. El umbral colapsa al máximo empírico, y con 124 ventanas
de test y 9 controles correlacionados ese máximo se supera a menudo. Esto, y no
la deriva, es lo que explica que el gate unión llegara a **0,774** de FPR cuando
ningún control individual pasa de 0,169.

**(b) Deriva del score**, concentrada en los detectores continuos y aprendidos.

**(c) Discretización.** `canal_oscilación` toma **7** valores distintos y
`retícula` uno solo: un cuantil sobre eso no representa el objetivo nominal.

## 3 · Dos clases de control que no admiten la misma calibración

Es el hallazgo arquitectónico de esta revisión, y explica por qué la unión
estaba mal construida:

- **Controles estadísticos** —CNN, cross-asset, canal—: score continuo, se
  calibran por cuantil y sufren deriva.
- **Controles deterministas o semánticos** —vintage, retícula—: su score limpio
  es **constante** (vintage ≈ 1e-14, retícula exactamente 0,01, el tick nativo).
  El umbral correcto es «cualquier valor distinto del nominal», no un cuantil.
  Calibrarlos estadísticamente es un **error de categoría**.

Se comprueba al aplicarles recalibración rodante: a vintage le sube la FPR de
**0,000 a 0,129** y a retícula no le cambia nada, mientras que a la CNN le baja
de **0,218 a 0,110**. Un mismo esquema de calibración no puede servir a los dos.

## 4 · Recalibración rodante: deployable y funciona donde hace falta

Umbral = cuantil rodante de los últimos 60 scores **observados**, sin etiquetas.
Esto **sí** es desplegable, a diferencia del ACI retirado, que realimentaba el
umbral con el hecho de saber que la ventana era limpia.

| control | congelado | rodante | rodante con 10 % de contaminación |
|---|---|---|---|
| **CNN 1D** | 0,218 | **0,110** | **0,078** |
| canal · oscilación | 0,097 | 0,056 | 0,027 |
| canal · ruptura | 0,032 | 0,056 | 0,062 |
| cross-asset | 0,097 | 0,097 | 0,086 |
| vintage | 0,000 | **0,129** | 0,000 |

Ayuda justo donde más falla —la CNN— y aguanta un 10 % de defectos mezclados en
el flujo de calibración. No es universal: rompe los controles deterministas, que
no deben calibrarse así.

## 5 · La IA sí aporta, medido a punto de operación idéntico

A FPR **impuesta al 5 %** sobre el limpio de test (oráculo, no desplegable, pero
es la única medida que separa «ve el defecto» de «está mal calibrado»):

| control | recall medio | AUC media |
|---|---|---|
| vintage | 0,509 | 0,742 |
| **CNN 1D** | **0,440** | **0,755** |
| cross-asset `1−R²` | 0,400 | 0,791 |
| canal · coherencia | 0,331 | 0,786 |
| canal · oscilación | 0,182 | 0,595 |
| **3σ** | **0,119** | 0,599 |

**La CNN es el mejor control en 7 de las 14 celdas familia-modo, y en 6 de las 7
del régimen `fresh`** —el operativamente frecuente, donde vintage es ciego por
construcción porque no hay snapshot con el que comparar—. Gana `reversible_jump`
en los dos modos (0,84 y 0,83), y en `fresh` gana `stale`, `decoupling`, `lag1`,
`weekly_ffill`, `source_switch` y `quantize`.

Vintage encabeza la media global, pero esa media está dominada por el modo
`restated`, donde logra 1,00 en cinco familias. Es un control potentísimo en su
subespacio y nulo fuera de él.

**El 3σ estándar obtiene 0,119.** No es solo que esté mal calibrado: a punto de
operación idéntico tampoco discrimina.

## 6 · Lectura

La afirmación «la IA no aporta» era un artefacto de medir discriminación y
calibración en el mismo número. Separadas:

- **Discriminación:** la IA aporta. La CNN domina el régimen de dato nuevo y
  supera al control estándar por un factor de casi 4 en recall medio.
- **Calibración:** la IA es la que peor transfiere, y es un problema con
  solución conocida —recalibración rodante, que lo reduce a la mitad— no una
  limitación del modelo.

Eso reencuadra el mensaje del paper: no «IA frente a controles estadísticos»,
sino **separar el detector del calibrador**, demostrar la aportación en
discriminación a punto de operación común, y tratar la calibración como un
problema propio con dos regímenes según la clase de control.

## 7 · XGBoost a FPR emparejada: el negativo anterior era un artefacto

Medido al mismo punto de operación que todo lo demás (5 % impuesto sobre el
limpio de test):

| control | recall medio | peor familia |
|---|---|---|
| **combinador XGBoost** | **0,613** | 0,054 |
| vintage | 0,509 | 0,048 |
| CNN 1D | 0,440 | 0,056 |
| cross-asset `1−R²` | 0,400 | 0,054 |
| 3σ | 0,119 | 0,032 |

**El combinador es el mejor de todo lo medido.** La conclusión previa —«XGBoost
como combinador pierde contra la unión de controles»— **era un artefacto de
comparar a tasas de falsas alarmas distintas**, exactamente el mismo error que
enmascaraba la aportación de la CNN. Queda **retirada**.

Reserva que hay que mantener: el combinador se entrena con las mismas familias
que se le miden. El leave-one-family-out previo mostró degradación fuera de
distribución, y ese control sigue siendo necesario antes de cerrar la
afirmación.

## 8 · Supervivencia del canal como control: no funciona

Se ajustó un **XGB-AFT** sobre 558 ventanas limpias de entrenamiento que predice
la vida restante del canal —sesiones hasta salir de la banda de 2σ, censura a 20
sesiones, vida media observada 5,8— a partir de su geometría: pendiente y ancho
normalizados por nivel, R², número de giros y posición final dentro de banda. El
score es lo anómala que resulta la vida predicha frente a la distribución
limpia. Es **causal**: usa solo la ventana, no su futuro.

**Recall medio 0,020, por debajo del azar (0,05), y 0,000 en la peor familia.**
Por familias en modo `fresh` no pasa de 0,06. No detecta nada.

La explicación más plausible es que las features de geometría que alimentan al
AFT son en su mayoría invariantes de escala, y las corrupciones inyectadas no
mueven la **vida predicha** aunque sí muevan la geometría puntual. Además la
vida observada es corta frente a la ventana de 20 sesiones, así que el objetivo
del AFT es ruidoso. Es un negativo limpio: la supervivencia del canal es una
pata de riesgo válida —C-index 0,664 en su tarea— pero **no transfiere a control
de calidad de dato** con este diseño.

## 9 · Simetría de subidas y bajadas

Señalado por el MASTER y confirmado como defecto de diseño:

- **`source_switch` solo se inyectaba al alza** (`uniform(1,04, 1,10)`), así que
  un detector aprendido nunca veía el empalme a la baja. **Corregido**: el factor
  es ahora simétrico en log, tan probable hacia arriba como hacia abajo. Las
  cifras de los §7-8 ya se midieron con la versión simétrica.
- La serie objetivo **ya usaba log-retornos**, que tratan igual subidas y
  bajadas. Pero **WTI, uno de los cuatro pares, entra en diferencias de dólares**
  —para preservar su settlement negativo de abril de 2020— mientras los otros
  tres van en log. Es una inconsistencia de representación que queda
  **pendiente**: la normalización por volatilidad iguala la escala pero no la
  asimetría. Probar `asinh`, que es simétrico y está definido en negativos.

## 10 · LOFO del combinador: sobrevive, y falla donde se esperaba

Reentrenando el combinador **sin** la familia que luego se le mide, a FPR
idéntica:

| familia · modo | dentro | retenida | caída |
|---|---|---|---|
| `quantize` · restated | 0,618 | **0,048** | **−0,570** |
| `source_switch` · restated | 0,976 | 0,685 | −0,290 |
| `reversible_jump` · fresh | 0,817 | 0,530 | −0,288 |
| `reversible_jump` · restated | 0,968 | 0,903 | −0,065 |
| `stale`, `decoupling`, `weekly_ffill`, `lag1` | — | — | **≈ 0,000** |
| **MEDIA** | **0,613** | **0,513** | **−0,100** |

La media cae una décima, pero **0,513 fuera de distribución sigue por encima de
todos los controles individuales**: vintage 0,509, CNN 0,440, cross-asset 0,400.
La afirmación del §7 sobrevive al control que la podía tumbar.

Y el patrón de la caída es interpretable, no ruido. En las familias que varios
controles cubren a la vez —`stale`, `decoupling`, `weekly_ffill`, `lag1`— la
pérdida es **nula**: el combinador generaliza porque las features de los otros
controles siguen informando. **Se hunde justo donde una sola feature
especializada es la única señal**: `quantize` cae a 0,048, el azar, porque sin
haber visto esa familia el modelo nunca aprende a usar el umbral de la retícula.

Es la misma patología vista desde el otro lado: un combinador aprendido no hereda
la garantía analítica de un control exacto, ni la reconstruye por su cuenta.
De ahí la arquitectura: **el combinador no sustituye a los controles exactos, se
une a ellos**.

## 11 · `asinh` para WTI: correcto por principio, irrelevante por resultado

La serie objetivo ya iba en log. El problema era **WTI**, que entraba en
diferencias de dólares —asimétricas y en otra escala— para preservar su
settlement negativo de abril de 2020. Se sustituye por `asinh(p/s)` con `s` = 74,1
USD estimado **solo en train**: simétrico en subidas y bajadas, definido en
negativos y asintóticamente igual al log para precios altos.

| representación de WTI | recall CNN | peor familia |
|---|---|---|
| diferencias en dólares | 0,433 | 0,054 |
| **`asinh` simétrico** | **0,435** | 0,048 |

**Sin diferencia medible.** La normalización causal por media y desviación
móviles ya estandariza cada canal, de modo que la escala estaba compensada; y la
asimetría de un canal entre cuatro pares no mueve la aguja cuando el objetivo
—Brent— siempre fue logarítmico.

Se recomienda adoptarlo igualmente **por coherencia de representación**, no por
rendimiento: deja las cinco series en una transformación simétrica y evita tener
que explicar una excepción. Pero no debe presentarse como una mejora.

## 12 · Lo que esto es: una metaheurística de controles

El encuadre del MASTER describe bien lo que ha quedado. No es un detector, ni una
competición entre una red y 3σ: es una **metaheurística** — una cartera de
controles sobre representaciones distintas, con dos piezas que la gobiernan.

- **Los controles** cubren familias de defecto con espacios nulos declarados.
  Ninguno domina; varios son exactos en su familia y ciegos fuera de ella.
- **El combinador** (XGBoost, 0,613 dentro y 0,513 fuera de distribución) agrega
  evidencia débil donde ningún control es decisivo, y no sustituye a los exactos.
- **El calibrador** es una pieza propia, con dos regímenes según la clase de
  control (§3), y es hoy el eslabón que falla.

El valor de la IA aparece en la capa de agregación y en la cobertura de lo no
anticipado, no en desplazar al control estadístico de su familia.

## 13 · Límites

- La medida a FPR idéntica es un **oráculo**: fija el umbral sobre el limpio de
  test. No es desplegable y no debe presentarse como rendimiento operativo.
  Sirve para atribuir, no para prometer.
- Defectos **sintéticos**, prevalencia uniforme, 124 ventanas **solapadas al
  75 %**, un solo activo y sus cuatro pares. Tres semillas.
- La recalibración rodante se evaluó sobre el flujo limpio y con un 10 % de
  contaminación de una sola familia. Falta barrer nivel y mezcla de familias.
- **XGBoost y la supervivencia de canal no se han reevaluado aquí.** El
  combinador sigue sin comparación a FPR equivalente, y la supervivencia aún no
  se ha usado como control de calidad. Son las dos piezas pendientes para
  responder del todo a la objeción del MASTER.
