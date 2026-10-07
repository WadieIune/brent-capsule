# Hallazgo · El canal es una TERCERA representación de control, y cubre lo que las otras dos no ven

- **Autor:** A · **Fecha:** 2026-10-07 · 🟡 **provisional**, pendiente de challenge B.
- **Código:** `code/applications/experiments/dq_channel_representation.py`.
- **Tests:** `tests/test_dq_channel_representation.py` (8).
- **Artefactos:** `results/reports/dq_channel_representation/summary.json`.
- **Instrucción MASTER:** medir DQ dentro del canal **como representación de
  control**, no buscando rentabilidad. El objetivo del paper es que CNN y ML
  **apoyen** a los controles estadísticos para no infra/sobre-estimar capital.

## Por qué hacía falta

`dq_conformal_gate` midió cuatro detectores que miran **todos lo mismo**:
retornos normalizados por volatilidad. Por eso compartían un espacio nulo entero.
`dq_quantize_price_grid` añadió la **retícula del precio** y cerró `quantize`. La
tercera representación que el proyecto ya tenía construida —para la pata de
riesgo, no para DQ— es la **geometría del canal**: recta central, ancho de banda,
oscilación y coherencia de posición-en-banda entre activos correlacionados.

Dos decisiones de diseño que corrigen límites declarados de los experimentos
anteriores:

1. **Las inyecciones son ahora en espacio de PRECIO**, no sobre retornos ya
   normalizados; retornos y normalización causal se **recalculan** sobre la serie
   corrompida. Las tres representaciones ven exactamente el mismo defecto.
2. La definición de canal **se reutiliza** de `part2_channel_survival`
   (`_linear_fit_metrics`, `find_turning_points`). No se inventa una nueva.

## Resultado

Se reportan **los dos protocolos**, porque medir solo el primero fue
precisamente el fallo que este hilo vino a corregir:

- **A · FPR emparejada**: umbral sobre el test limpio. Aísla poder
  discriminante, **no es operativo**.
- **B · gate conforme-adaptativo (ACI)**: calibrado en validación limpia y
  recalibrado en línea. **Es el gate real.**

### A · FPR emparejada por construcción (poder discriminante)

Recall a FPR emparejada (5 %, azar ≈ 0,048), 124 ventanas de test, 5 semillas.
`*` = en el azar.

| control | representación | stale | rev_jump | decoupling | lag1 | weekly_ffill | source_switch | quantize |
|---|---|---|---|---|---|---|---|---|
| coherencia de banda | canal | **1,000** | 0,516 | 0,581 | 0,581 | 0,492 | 0,210 | 0,065 |
| ruptura de banda | canal | 0,000* | 0,694 | 0,048* | 0,274 | 0,105 | 0,065 | 0,032* |
| cambio de geometría | canal | 0,000* | 0,202 | 0,121 | 0,065 | 0,242 | 0,056 | 0,048* |
| déficit de oscilación | canal | **1,000** | 0,016* | 0,024* | 0,024* | **0,992** | 0,040* | 0,105 |
| retícula | precio | 0,613 | 0,000* | 0,000* | 0,000* | 0,024* | 0,000* | **1,000** |
| CNN 1D | retorno norm. | 0,792 | **0,800** | **0,931** | 0,550 | 0,666 | **0,406** | 0,053 |
| `1-R²` cross-asset | retorno norm. | 0,839 | 0,532 | 0,895 | **0,855** | 0,742 | 0,210 | 0,065 |
| 3σ | retorno norm. | 0,032* | 0,411 | 0,153 | 0,081 | 0,121 | 0,081 | 0,032* |

### B · Gate conforme-adaptativo ACI (protocolo OPERATIVO)

Todos los controles cumplen el presupuesto (FPR realizada 0,000-0,065 sobre un
objetivo del 5 %), así que las comparaciones son a carga de alarmas pareja.

| control | repr. | FPR | stale | rev_jump | decoupling | lag1 | weekly_ffill | source_switch | quantize |
|---|---|---|---|---|---|---|---|---|---|
| coherencia de banda | canal | 0,048 | **1,000** | 0,540 | 0,645 | 0,629 | 0,532 | 0,234 | 0,056 |
| ruptura de banda | canal | 0,065 | 0,000* | 0,677 | 0,048* | 0,282 | 0,097 | 0,065 | 0,032* |
| cambio de geometría | canal | 0,065 | 0,000* | 0,290 | 0,137 | 0,097 | 0,306 | 0,113 | 0,040* |
| déficit de oscilación | canal | 0,048 | **1,000** | 0,000* | 0,008* | 0,024* | **0,815** | 0,008* | 0,048* |
| retícula | precio | 0,000 | 0,613 | 0,000* | 0,000* | 0,000* | 0,024* | 0,000* | **1,000** |
| CNN 1D | retorno norm. | 0,053 | 0,708 | **0,718** | **0,835** | 0,506 | 0,618 | **0,332** | 0,021* |
| `1-R²` cross-asset | retorno norm. | 0,040 | 0,734 | 0,581 | 0,798 | **0,790** | 0,694 | 0,242 | 0,065 |
| 3σ | retorno norm. | 0,048 | 0,032* | 0,371 | 0,129 | 0,073 | 0,089 | 0,097 | 0,032* |

**Las conclusiones no cambian entre protocolos.** El canal sigue ganando `stale`
(1,000) y `weekly_ffill` (0,815 frente a 0,694 del mejor de retorno), el precio
sigue siendo el único que ve `quantize`, y la CNN sigue siendo la mejor en
`rev_jump`, `decoupling` y `source_switch`. Lo que cae al pasar al gate operativo
es el margen, no el orden.

**Cada representación es dueña de alguna familia, y ninguna domina:**

- **Canal** gana `stale` (1,000 vs 0,839 del mejor de retorno) y sobre todo
  `weekly_ffill` (**0,992** vs 0,742). Las dos son «la serie dejó de moverse», que
  es exactamente lo que mide el déficit de oscilación y exactamente el check TRIM
  que el paper persigue. Un control de magnitud de retorno no las ve bien porque
  el movimiento no desaparece, **se reagrupa**.
- **Precio** gana `quantize` en exclusiva (1,000; todo lo demás en el azar).
- **Retorno normalizado** gana `reversible_jump`, `decoupling` y `source_switch`,
  y ahí **la CNN es el mejor detector de las tres familias** (0,800 / 0,931 /
  0,406). No es pasajera del banco: aporta.

## Lo que esto dice del papel de la red

La CNN **no sustituye** a ningún control explícito —pierde contra el control
dedicado de `stale`, `weekly_ffill`, `lag1` y `quantize`— pero es la mejor opción
en las tres familias donde el defecto es un patrón temporal multivariante sin
estadístico cerrado evidente. Encaja con el objetivo declarado: **apoyar** a los
controles estadísticos, no reemplazarlos.

## El hueco nuevo: `source_switch`

Con `quantize` cerrado, el defecto difícil pasa a ser el **empalme de
proveedores**: el mejor detector es la CNN con **0,406** y ningún control
explícito pasa de 0,210. Un salto de nivel del 4-10 % a mitad de ventana no
rompe ni la banda ni la coherencia lo bastante. Es el candidato natural para el
control de **vintage** de B, que es una cuarta representación (serie almacenada
frente a serie recibida) y que ya demostró 1,000 en el back-adjust de splits.

## Arquitectura que se deriva

**Banco de controles organizado por REPRESENTACIÓN, no por estadístico**, bajo un
único gate conforme que impone la tasa de falsas alarmas:

| representación | qué mira | familias que cubre |
|---|---|---|
| precio crudo | retícula, nivel | `quantize` |
| retorno normalizado | magnitud, correlación | `rev_jump`, `decoupling`, `lag1` |
| canal | forma, banda, oscilación | `stale`, `weekly_ffill` |
| vintage (B) | serie almacenada vs recibida | `back-adjust`, y candidato a `source_switch` |

El siguiente paso natural —y es donde encaja **XGBoost**, que sigue sin existir en
la capa DQ— es un **combinador** sobre las salidas de los controles de las cuatro
representaciones, en vez de un detector más. Esa es la pieza que convierte la
matriz en un único veredicto por ventana con presupuesto de falsas alarmas.

## Límites — lo que NO se afirma

- Defectos **sintéticos**, inyectados por mí; no es una muestra de la prevalencia
  real. El `source_switch` del 4-10 % es una elección mía y mueve su fila entera.
- 124 ventanas con stride 5 sobre ventana 20: **solapan al 75 %**, no son
  independientes, y los intervalos implícitos son optimistas.
- Los controles de canal son **deterministas**: no tienen semilla, así que su
  fila no lleva dispersión. Solo la CNN promedia 5 semillas. No comparar
  estabilidad entre filas.
- El canal se ajusta **dentro de la ventana de 20 sesiones**, que es corto para la
  definición de canal de la pata de riesgo (episodios de meses). No se afirma que
  estos controles equivalgan a los del detector de canal en producción.
- **No se ha medido impacto en capital.** El objetivo declarado es no
  infra/sobre-estimar capital; esto mide *detección*, no el error de capital
  evitado. Enlazarlo con `dq_capital_impact` (C7) es trabajo pendiente.
- La supervivencia del canal (XGB-AFT, C-index 0,664) **no** se ha usado aquí. La
  idea de usar el tiempo de vida esperado como control de calidad sigue sin medir.
