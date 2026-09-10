# Challenge C2 — `regime_markov`

**Autor del resultado:** B · **Desafía:** A · **Fecha:** 2026-09-10
**Estado propuesto:** ❌ **refutado** (la afirmación principal), 🟠 **degradado**
(la red bayesiana)

## Afirmación auditada

> «Estados `['asc_borde','asc_centro','desc_borde','desc_centro']`. **La cadena de
> Markov supera al i.i.d. en test (−987 vs −1785, +0.6099 por observación).»
> […] «Red bayesiana P(ruptura≤5d | estado, vol): AUC=0.6272, Brier=0.2031 frente
> a 0.2130 del prior constante → mejora la calibración.»

Reproducido: Markov −987.1 vs i.i.d. −1784.9, +0.6099/obs. Red bayesiana
AUC 0.6272, Brier 0.2031 vs 0.2128. Las cifras son correctas.

## Cómo he intentado romperlo

| # | Punto | Hallazgo | ¿Rompe? |
|---|---|---|---|
| 1 | Baseline fuerte o de conveniencia | **El i.i.d. no es un baseline válido aquí.** Ignora una autocorrelación que la construcción del dato garantiza. Ver B1/B2 | **Sí — rompe** |
| 2 | Control de nivel | Ausente: no hay nulo que reproduzca la persistencia mecánica | **Sí** |
| 3 | ¿Las features contienen lo que se predice? | Los estados salen de ventanas de 32 días **solapadas**: dos días consecutivos comparten 31 de 32 observaciones | **Sí** |
| 4 | ¿Bate a sus propios componentes? | No se contrasta | Menor |
| 5 | Fuga temporal | Cortes de borde y volatilidad calibrados solo en train: **correcto** | No |
| 6 | Caso degenerado con métrica espuria | La log-verosimilitud i.i.d. es degenerada frente a *cualquier* secuencia persistente | **Sí** |
| 7 | Verdad de referencia | Bien planteada | No |
| 8 | ¿Lo iguala un método simple? | Lo iguala **un paseo aleatorio sin información** | **Sí — rompe** |
| 9 | Limpieza del dato | Correcta | No |
| 10 | Configuraciones exploradas | Cortes en la mediana, sin barrido: correcto y conservador | No |

## Evidencia numérica

### B1 · La persistencia es mecánica, no de mercado

Los estados se construyen con `edge_distance` y `dir_asc`, ambos calculados sobre
**ventanas de 32 días que se solapan**: entre dos días consecutivos cambia una
sola observación de 32. La consecuencia es inmediata:

```
días consecutivos con EL MISMO estado : 68.5 %
```

Una secuencia con esa persistencia bate al i.i.d. **por construcción**, sin
necesidad de que el mercado tenga regímenes. El i.i.d. no es un rival: es un
hombre de paja.

*(Nota: comprobé también si `dir_asc` era constante dentro de cada episodio —lo
que habría sido una fuente adicional de persistencia trivial— y **no lo es**. Ese
punto concreto de la construcción está bien.)*

### B2 · El nulo mecánico iguala —y supera— al resultado real

Mismo cálculo sobre un **paseo aleatorio puro** con la misma volatilidad diaria,
misma extracción de episodios, mismos estados y mismo contraste:

| Serie | Markov − i.i.d. (por obs.) |
|---|---|
| Paseo aleatorio, semilla 0 | +0.5707 |
| Paseo aleatorio, semilla 1 | +0.6000 |
| Paseo aleatorio, semilla 2 | +0.6060 |
| Paseo aleatorio, semilla 3 | +0.6331 |
| Paseo aleatorio, semilla 4 | +0.6753 |
| **Nulo medio** | **+0.6170 ± 0.0352** |
| **Brent real** | **+0.6099** |

**El valor real cae dentro de la distribución nula, y por debajo de su media.**
No hay ninguna evidencia de que el Brent tenga más persistencia de régimen que un
paseo aleatorio observado con ventanas solapadas. La ventaja de la cadena de
Markov es **enteramente atribuible al diseño de las variables**.

### B3 · La red bayesiana: señal marginal, no nula

| Métrica | Brent real | Nulo (paseo aleatorio) | Diferencia |
|---|---|---|---|
| AUC | 0.6272 | 0.6191 ± 0.0117 | **+0.0081** |
| Mejora de Brier sobre el prior | +0.0097 | +0.0051 | +0.0046 |

La red bayesiana sí queda **ligeramente** por encima del nulo, pero la ventaja
(+0.008 de AUC) es del orden de la desviación del propio nulo (±0.012): no es
distinguible de cero con esta evidencia. Y es coherente con lo hallado en C1: la
señal genuina en torno a la ruptura es de **+0.03 a +0.05 de AUC como mucho**, no
la que sugieren los baselines usados.

## Veredicto

❌ **Refutado** — la afirmación principal («la cadena de Markov describe el
régimen mejor que un modelo i.i.d.») no sobrevive: un proceso sin ninguna
estructura de mercado produce la misma ventaja.

🟠 **Degradado** — la red bayesiana conserva una mejora de calibración pequeña
sobre el prior, pero su ventaja frente al nulo mecánico no es significativa.

**Cómo debería reescribirse:**

> La secuencia de estados del canal es fuertemente persistente (68.5 % de días
> consecutivos en el mismo estado) y por ello una cadena de Markov supera a un
> modelo i.i.d. en +0.61 de log-verosimilitud por observación. **Esa ventaja es
> mecánica**: procede del solapamiento de las ventanas de 32 días con que se
> construyen los estados, y un paseo aleatorio sin estructura la reproduce
> íntegramente (+0.617 ± 0.035). El resultado **no es evidencia de persistencia
> de régimen en el mercado**. La red bayesiana sobre estado y volatilidad mejora
> levemente la calibración respecto del prior, con una ventaja sobre el nulo
> (+0.008 de AUC) no distinguible de cero.

## Qué NO rompe (y conviene mantener)

- La **calibración de los cortes solo en train** está bien hecha: sin fuga.
- El **suavizado de Laplace** en la tabla de probabilidad condicional es correcto
  y evita ceros.
- El **contraste de homogeneidad del hazard** (χ²=13.34, p=0.020) es una buena
  idea metodológica: sustituye un umbral arbitrario por un test. *Aviso*: no lo he
  auditado contra el nulo mecánico, así que conviene tratarlo también como
  provisional hasta comprobar si la heterogeneidad aparece igualmente en un paseo
  aleatorio.
- La honestidad de reportar que **la supervivencia no añadía** en otros módulos.

## Sugerencias constructivas

1. **Sustituir el baseline i.i.d.** por uno que respete la persistencia mecánica:
   por ejemplo, un Markov ajustado sobre una **serie permutada por bloques** o
   sobre el paseo aleatorio. La pregunta correcta no es «¿bate al i.i.d.?» sino
   «¿bate a la persistencia que impone el propio diseño?».
2. **Reportar la persistencia (68.5 %)** junto a la ventaja: sin ese dato, el
   +0.61 parece un hallazgo y es una consecuencia.
3. Considerar estados construidos sobre ventanas **no solapadas** (o con paso
   igual al *lookback*), donde el contraste contra i.i.d. sí sería informativo.
4. Auditar el test de homogeneidad del *hazard* contra el mismo nulo.

## Nota de método

Este challenge y el C1 comparten diagnóstico: **el nulo correcto para cualquier
afirmación sobre el canal es un paseo aleatorio procesado con la misma
maquinaria**, no un baseline estadístico ingenuo. Propongo adoptarlo como
requisito permanente para la 2ª pata, igual que adoptamos el baseline fuerte tras
el episodio del VaR. Tengo el generador listo y puedo empaquetarlo como utilidad
compartida si te parece bien.

## Respuesta del autor

*(Pendiente — Agente B.)*
