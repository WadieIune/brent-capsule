# RETIRADO — análisis de capital no válido para el paper DQ

> No citar ni reutilizar las cifras que permanecen en el registro histórico de
> abajo. El usuario determinó que no son resultados reales: dependen de una
> cartera equiponderada y nominal normalizado, defectos/prevalencias sintéticos,
> supuesto de corrección perfecta, ventanas solapadas y presupuestos de FPR
> diferentes. No representan capital de cartera ni desempeño validado de una
> capa DQ. Se conservan únicamente para auditoría del proceso.

## Estado vigente

La comparación principal se centra en distribuciones de rendimientos y calidad
de detección: FPR, recall/precisión por familia con prevalencia defendible,
transferencia temporal y falsas alertas ante movimientos legítimos. No se
reportan porcentajes de capital evitado. Véase
`docs/hallazgos/2026-10-07-A-distribuciones-rendimientos-3sigma.md`.

- **Autor:** A · **Fecha:** 2026-10-07 · 🟡 **provisional**, pendiente de challenge B.
- **Código:** `code/applications/experiments/dq_capital_value_added.py`.
- **Tests:** `tests/test_dq_capital_value_added.py` (7). Suite 87/87.
- **Artefactos:** `results/reports/dq_capital_value_added/summary.json`.
- **Enlaza:** detección de `dq_representation_stack` (C11) con el esquema de
  capital `k · VaR` de `dq_capital_impact` (C7) y el multiplicador de
  `portfolio_var`.

## Qué se mide y por qué así

C7 estableció que consumir dato sucio mueve el capital, comparando panel crudo
contra depurado. La pregunta del objetivo del paper es la siguiente: **de ese
error, cuánto evita cada capa de control, y cuánto añade la IA sobre los
controles estadísticos.**

```
error_residual(gate) = media_familias [ (1 − recall_gate(familia)) × |Δcapital(familia)| ]
```

Lo que el gate detecta se sanea y se recalcula, así que no llega al capital; lo
que no detecta, pasa. Los gates se construyen **anidados** —`solo_3sigma` ⊂
`sin_ia` ⊂ `con_cnn`— para que la diferencia entre dos consecutivos **sea** la
aportación de la capa que los separa, y cada subconjunto se recalibra a su propio
reparto para que todos operen a carga de alarmas comparable. Sin ese anidamiento
y esa recalibración no se puede atribuir valor a nadie.

**Alcance deliberadamente superficial** (instrucción del MASTER): cartera
estándar equiponderada sobre los cinco activos del panel, VaR histórico 99 % a
250 sesiones, capital `k · VaR` con el semáforo de Basilea, base 100 de notional.
Fuera: correlaciones entre factores, diversificación entre mesas, específico y
default, PLA por mesa, NMRF, suelo SA. **Las cifras en base 100 no estiman el
impacto real**; lo comparable entre gates es la *proporción* de error evitado.

## Resultado por capa

Capital de la cartera limpia: **9,13** en base 100. Error de capital si no hay
control alguno: **0,058**.

| gate | FPR | error residual | **error evitado** |
|---|---|---|---|
| sin control | — | 0,058 | 0,0 % |
| solo 3σ (statu quo) | 0,032 | 0,052 | **10,0 %** |
| banco sin IA (8 controles) | 0,081 | 0,009 | **84,8 %** |
| banco **con CNN** (9) | 0,083 | 0,008 | **86,7 %** |
| combinador XGBoost | 0,051 | 0,011 | 81,6 % |

| capa | valor añadido |
|---|---|
| banco de controles **sobre 3σ** | **+74,8 pp** |
| **CNN sobre el banco** | **+1,9 pp** |
| combinador XGBoost sobre el banco | **−5,1 pp** |

El statu quo —3σ sobre log-rendimientos— evita **el 10 %** del error de capital.
El banco de representaciones evita el **85 %**. Ahí está el valor del trabajo, y
no es deep learning: es mirar el dato en varias representaciones.

## Dónde está el valor por control, y por qué no coincide con el recall

| control | recall medio | **error de capital evitado** |
|---|---|---|
| vintage | 0,506 | **78,5 %** |
| **CNN 1D** | 0,409 | **63,0 %** |
| canal · coherencia de banda | 0,382 | 61,9 % |
| cross-asset `1−R²` | 0,327 | 54,1 % |
| canal · déficit de oscilación | 0,184 | 25,0 % |
| canal · ruptura de banda | 0,154 | 24,1 % |
| 3σ | 0,130 | 17,3 % |
| canal · cambio de geometría | 0,129 | 16,4 % |
| **precio · retícula** | 0,117 | **10,2 %** |

**El hallazgo más útil de este documento: detectar bien y evitar error de capital
no son lo mismo.** El control de retícula es **analíticamente perfecto** en
`quantize` (recall 1,000) y es el que **menos** valor de capital aporta (10,2 %),
porque `quantize` resulta ser la familia que **menos** mueve el capital
(Δ 0,0040 y 0,0001 en base 100, frente a 0,1654 de `lag1_calendar`). Un control
impecable sobre un defecto inocuo no genera valor prudencial.

Y al revés, en términos de capital la **CNN es el segundo control más valioso**
(63,0 %), por delante del cross-asset estadístico (54,1 %) — mejor posición que
la que sugería la tabla de recall puro. Su contribución *marginal* sobre el banco
es pequeña (+1,9 pp) porque sus fortalezas (`reversible_jump`, `decoupling`)
solapan con el cross-asset, y su debilidad (`lag1_calendar`, recall 0,506) es
justamente la familia de mayor impacto en capital.

Impacto en capital por familia, en base 100 (ordenado):

| familia | Δcapital | familia | Δcapital |
|---|---|---|---|
| `lag1_calendar\|restated` | 0,1654 | `source_switch\|restated` | 0,0166 |
| `reversible_jump\|restated` | 0,1519 | `lag1_calendar\|fresh` | 0,0086 |
| `decoupling\|restated` | 0,1471 | `stale\|fresh` | 0,0086 |
| `stale\|restated` | 0,1252 | `weekly_ffill\|fresh` | 0,0051 |
| `source_switch\|fresh` | 0,0746 | `quantize\|restated` | 0,0040 |
| `weekly_ffill\|restated` | 0,0563 | `decoupling\|fresh` | 0,0032 |
| `reversible_jump\|fresh` | 0,0420 | `quantize\|fresh` | 0,0001 |

## Lectura para el paper

1. **El valor demostrado está en la cobertura por representaciones, no en el
   modelo.** 3σ evita el 10 % del error de capital; el banco, el 85 %.
2. **La CNN aporta, y aporta más de lo que parecía**: segundo control por valor
   de capital, y +1,9 pp marginales sobre un banco que ya incluye todo lo demás.
   Es una mejora real y modesta, no una ruptura, y así debe escribirse.
3. **El combinador XGBoost resta valor (−5,1 pp)** frente a la unión de controles
   gateados. Consistente con C11: el modelo aprendido diluye los controles
   analíticamente decisivos. «ML que apoya» sí; «ML que sustituye» no.
4. **Priorizar controles por recall es un error.** Hay que priorizarlos por error
   de capital evitado, y las dos listas no coinciden.

## Límites

- **No es una medición de impacto real.** Cartera equiponderada de cinco activos,
  un solo esquema de VaR, sin ninguna de las capas de una cartera de CIB.
- Los recalls vienen de **inyecciones sintéticas** escritas por mí, sobre 124
  ventanas de test que **solapan al 75 %**. El tamaño elegido en cada familia
  mueve su Δcapital y por tanto los pesos de toda la tabla.
- **Prevalencia uniforme implícita**: se promedia sobre familias como si todas
  fuesen igual de frecuentes. Es falso y no hay dato para ponderarlo. Con
  prevalencias reales el orden de la tabla por control podría cambiar entero.
- El modelo de saneo es **idealizado**: se supone que detectar equivale a corregir
  sin error y sin coste. No se modela el coste operativo de investigar una alerta
  ni el riesgo de «corregir» un movimiento de mercado legítimo.
- Las tres capas comparan a FPR 0,032 / 0,081 / 0,083, no exactamente iguales. La
  comparación 3σ → banco es conservadora en recall y generosa en alarmas.
