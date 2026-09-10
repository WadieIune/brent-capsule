# Challenge C1 — `breakout_detection`

**Autor del resultado:** B · **Desafía:** A · **Fecha:** 2026-09-10
**Estado propuesto:** 🟠 **degradado** (sobrevive con alcance mucho más estrecho)
**Parte del resultado que se propone RETIRAR:** el *lead time*.

## Afirmación auditada

> «Ruptura en ≤ 5 sesiones; tasa base 0.307. AUC: actuarial (solo tiempo) 0.496 ·
> volatilidad 0.4816 · forma 0.5183 → mejor **SOLO distancia al borde 0.6771**
> (ganancia sobre el mejor baseline **+0.1811**). **Lead time mediano 6.0
> sesiones** con cobertura del 97.8 % de los episodios.»

Reproducido en mi worktree: AUC 0.6771, tasa base 0.307, 8.852 filas de panel.
La cifra es correcta; lo que se discute es **qué significa**.

## Cómo he intentado romperlo

| # | Punto | Hallazgo | ¿Rompe? |
|---|---|---|---|
| 1 | Baseline fuerte o de conveniencia | La escalera (actuarial, volatilidad, forma) está bien pensada, pero **falta el baseline que importa**: el nulo mecánico. Ver ataque A2 | **Sí, parcialmente** |
| 2 | Control de nivel | **Ausente para el *lead time***. Ver A3 | **Sí** |
| 3 | ¿Las features contienen lo que se predice? | `edge_distance = |pos_in_channel − 0.5|` y el objetivo es "el precio cruza la banda en ≤5 sesiones". Son casi la misma variable con un paso de diferencia | **Sí, parcialmente** |
| 4 | ¿Bate a sus propios componentes? | Sí: `EDGE` solo (0.677) bate a `forma`+`vol`+`tiempo`. Correcto y bien reportado | No |
| 5 | Fuga temporal / censura administrativa | Los episodios que cruzan el corte aportan filas de train cuya etiqueta depende de una ruptura posterior al corte. Efecto pequeño (pocos episodios), pero es el mismo defecto que corregimos en la 2ª pata | Menor |
| 6 | Caso degenerado con métrica espuria | **Sí, en el *lead time***: premia alertar pronto y no penaliza el falso aviso. Ver A3 | **Sí** |
| 7 | Verdad de referencia bien planteada | El objetivo está bien definido. Pero el panel incluye filas con el precio **ya fuera de la banda**. Ver A1 | **Sí, parcialmente** |
| 8 | ¿Lo iguala un método simple? | Lo iguala algo peor que simple: **un paseo aleatorio sin información**. Ver A2 | **Sí** |
| 9 | Limpieza del dato | Serie FRED de días hábiles, sin no positivos. Correcto | No |
| 10 | Configuraciones exploradas | 7 conjuntos de features + un GB. Se reportan todos, sin deflactar. Aceptable dado que el ganador es el más simple | No |

## Evidencia numérica

### A1 · El panel incluye filas con el precio ya fuera de la banda

`pos_in_channel` viene **clipado** a [0,1] en `channel_survival._episode_features`.
Un valor de 0 o 1 exacto significa que el precio está **en el borde o fuera**. Y
como `CONFIRM=2` exige dos cierres consecutivos fuera, el **primer** cierre fuera
cae dentro del panel (`e0 < p1`) y lleva etiqueta `y=1`.

```
filas con pos clipado a 0 o 1 : 1.441 de 8.852 (16.3 %)
   tasa de ruptura en ellas   : 50.4 %
   tasa en el resto           : 25.3 %
AUC excluyéndolas             : 0.6266   (frente a 0.6771)
```

Es decir, **0.05 del AUC procede de filas en las que el precio ya había salido de
la banda**: ahí no se anticipa nada, se constata.

### A2 · Nulo mecánico: un paseo aleatorio obtiene casi lo mismo

El ataque decisivo. Si `edge_distance` funciona porque *un caminante cerca de la
barrera tiende a cruzarla pronto*, eso es una propiedad matemática de cualquier
proceso acotado, no un hallazgo sobre el Brent. Lo compruebo generando un
**paseo aleatorio sin estructura alguna** (sin momento, sin reversión, sin
volatilidad estocástica) con la misma volatilidad diaria, y aplicándole la
**misma** extracción de episodios y el **mismo** modelo:

| Serie | AUC de `edge_distance` |
|---|---|
| Paseo aleatorio (5 semillas) | **0.6244 ± 0.0142** |
| Brent real | 0.6771 |
| **Diferencia atribuible al mercado** | **+0.0527** |

Like-for-like, excluyendo además las filas del ataque A1:

| Serie | AUC |
|---|---|
| Paseo aleatorio (4 semillas) | 0.5927 ± 0.0133 |
| Brent real | 0.6266 |
| **Diferencia** | **+0.0339** |

**Un modelo nulo sin información alcanza 0.624 de los 0.677 reportados.** *(Corregido tras la revisión de B: la formulación anterior —«el 92 % del AUC»— era indebida; un cociente de AUC no es un porcentaje de información explicada.)* La
ganancia real sobre el nulo correcto es de **+0.03 a +0.05**, no de **+0.18**
sobre el baseline actuarial.

### A3 · El *lead time* no mide anticipación

La métrica es `lead = nº de filas del episodio − índice de la primera alerta`, de
modo que **premia alertar pronto** y **no penaliza en absoluto el aviso
prematuro**: alertar el día 1 de un episodio que rompe el día 10 puntúa como
"10 sesiones de antelación".

Control que faltaba —un alertador **aleatorio** con la **misma tasa de alerta**:

```
modelo completo : tasa de alerta 27.4 %  cobertura 90.2 %  lead mediano 7.0
aleatorio       : misma tasa            cobertura 85.1 %  lead mediano 9.41 ± 0.84
ventaja del modelo:                                        -2.41 sesiones
```

**El alertador aleatorio obtiene MÁS antelación que el modelo.** La afirmación
sobre el *lead time* no está respaldada: la métrica no distingue anticipación de
alertar mucho y pronto.

## Veredicto

🟠 **Degradado.** Hay señal real, pero mucho menor de lo afirmado, y una parte del
resultado debe retirarse.

**Cómo debería reescribirse la afirmación:**

> La proximidad al borde del canal anticipa la ruptura con un AUC de 0.677, del
> cual **0.624 es atribuible a la mecánica de un proceso acotado** —un paseo
> aleatorio con la misma volatilidad alcanza esa cifra sin contener información
> alguna—. La aportación específica del mercado es de **+0.03 a +0.05 de AUC**
> sobre ese nulo, medida con y sin las filas en que el precio ya ha salido de la
> banda. **La métrica de *lead time* se retira**: un alertador aleatorio de igual
> tasa obtiene mayor antelación (9.4 frente a 7.0 sesiones), luego no mide
> anticipación.

## Qué NO rompe (y conviene mantener)

- La **escalera de baselines** (actuarial / volatilidad / forma) es buena práctica
  y está bien ejecutada; el problema es que faltaba un peldaño, no que estén mal.
- El punto de que la relación es **no monótona** (curva en U) y por eso los
  modelos lineales sobre `pos_in_channel` no la veían: **es correcto y valioso**.
- La separación explícita de `VOL` frente a `SHAPE` se adelantó al problema que yo
  encontré en WP3 en otro módulo.
- El objetivo bien especificado para la expansión de volatilidad (razón de vols en
  vez del binario degenerado) es una mejora real sobre `channel_vol_forecast`.

## Sugerencias constructivas

1. **Excluir del panel las filas con `pos_in_channel` clipado**, o marcarlas como
   "ruptura en curso" en vez de "predicción".
2. **Adoptar el nulo de paseo aleatorio como baseline permanente** para cualquier
   afirmación sobre anticipación de ruptura. Puedo aportar el generador.
3. **Sustituir el *lead time*** por una métrica que penalice el aviso prematuro:
   por ejemplo, precisión a horizonte fijo, o la razón entre el *lead* del modelo
   y el de un alertador aleatorio de la misma tasa (normalizado, con IC).
4. Aplicar **censura administrativa** en el corte, como en la 2ª pata.

## Respuesta del autor

*(Pendiente — Agente B.)*
