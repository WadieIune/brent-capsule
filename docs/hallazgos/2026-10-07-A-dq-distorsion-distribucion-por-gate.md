# Hallazgo · Cuánto deforma la distribución de rendimientos un defecto no detectado, y cuánto corrige cada capa del banco

> **§3 DEGRADADO — no citar.** Las cifras de «distorsión corregida» son una
> proyección bajo corrección perfecta, no una mejora medida, y además multiplican
> agregados **no pareados**. Challenge aceptado sin reservas:
> `docs/auditorias/2026-10-07-A-challenge-dq-return-distribution.md`; respuesta y
> condiciones para reabrir en
> `docs/auditorias/2026-10-07-A-respuesta-challenge-dq-return-distribution.md`.
> **Lo que sigue en pie son los §1-2** (diagnóstico descriptivo) y la figura, de
> la que ya se retiró el panel D.

- **Autor:** A · **Fecha:** 2026-10-07 · 🟡 **provisional**, pendiente de challenge B.
- **Código:** `code/applications/experiments/dq_return_distribution.py`.
- **Figura:** `docs/figuras/dq_distribucion_rendimientos.png`.
- **Artefactos:** `results/reports/dq_return_distribution/summary.json`.
- **Continúa** `2026-10-07-A-distribuciones-rendimientos-3sigma.md`, que cierra el
  diagnóstico de normalidad sobre nueve series. Este documento ejecuta el
  «siguiente experimento» que aquél pedía: **cuánto cambia la distribución tras
  una corrupción conocida y si el sistema identifica ese tramo.**
- **Sustituye el encuadre de capital** de `2026-10-07-A-dq-capital-valor-anadido.md`
  (C12), ya retirado.

## 1 · Dos correcciones de partida

**(a) Las cifras de capital quedan retiradas.** C12 decía «error de capital
evitado: banco 84,8 %». El error total era el **0,633 %** del capital (0,058
sobre 9,13 en base 100), así que ese 84,8 % era el 84,8 % *de una cantidad
diminuta* y se leía como una fracción del capital. Un 80 % de capital no es una
mejora: es no tener capital. Solo queda el **disclaimer de método**: el capital
por modelo interno sería `k · VaR` con `k` del semáforo de Basilea, y calcularlo
en serio exige cartera real, correlaciones entre factores, diversificación entre
mesas, específico y default, PLA por mesa, NMRF y suelo SA. **No se dan cifras.**

**(b) El sentido del sesgo de la normal no es el que se asumía.** Conviene
dejarlo escrito porque es contraintuitivo: suponer normalidad con bandas ±3σ
**infraestima** la frecuencia de extremos, no la sobreestima. En Brent, |z| > 3
ocurre el **1,11 %** de las sesiones frente al **0,27 %** que predice la normal
—**4,1×**— y a 5σ la razón llega a **5.605×**. Lo que la normal sobreestima es la
masa de los *hombros*: a 1σ y 2σ los ratios son 0,5× y 0,8×. Es la firma
canónica de la leptocurtosis: centro más apretado, hombros más finos, colas
mucho más gruesas.

De ahí **no** se sigue ninguna dirección de sesgo en capital. Eso dependería de
cartera, horizonte y metodología, y aquí no se calcula.

## 2 · Lo que esto implica para el control de calidad

Un umbral 3σ es un **supuesto de normalidad encubierto**. Si dispara cuatro
veces más de lo que su propio supuesto promete, entonces **no puede separar una
cola real de mercado de un defecto de dato**: bajo normalidad las dos cosas son
«imposibles». Esa es la razón de fondo por la que la cobertura hay que ganarla
con **otras representaciones** —precio, canal, vintage, pares— y no subiendo el
umbral.

**Sensibilidad declarada.** La curtosis de Brent la dominan unos pocos días:

| días extremos excluidos | curtosis de exceso |
|---|---|
| 0 | 76,4 |
| 1 | 25,9 |
| 3 | 12,9 |
| 10 | 4,9 |

Esos días son **mercado real** —2020-04-21, Brent de 17,36 a 9,12 USD, el día
siguiente al settlement negativo del WTI; 2020-03-09; 2009-01-05—, no defectos.
Aun excluyendo diez sigue siendo claramente leptocúrtica, así que la conclusión
aguanta; pero **el 76,4 no es una propiedad estable y no debe citarse solo**.

## 3 · Distorsión por gate — DEGRADADO, se conserva solo para auditoría

> **No citar nada de esta sección.** El motivo decisivo: la distorsión se
> promedia sobre 40 episodios con un generador aleatorio y el recall se lee del
> stack, que usó **otras** inyecciones sobre 124 ventanas. Multiplicar
> `media(1−recall) × media(W)` supone un pareado que no existe. Además es una
> proyección bajo corrección perfecta —detección y corrección son problemas
> distintos— y «precisión» es terminología incorrecta: no se calcula PPV.

Lo que un defecto no detectado estropea es la **forma** de la distribución. Se
mide con la distancia de Wasserstein entre la distribución limpia y la
corrompida, en unidades de sigma, ponderada por lo que cada gate deja pasar:

```
distorsión_residual(gate) = media_f [ (1 − recall_gate(f)) × W(limpia, corrompida_f) ]
```

Los gates son los **anidados** de `dq_representation_stack`, cada uno
recalibrado a su propio reparto, de modo que la diferencia entre consecutivos
aísla la capa que los separa.

| gate | FPR | distorsión residual | corregida |
|---|---|---|---|
| sin control | — | 0,01115 | 0,0 % |
| solo 3σ (statu quo) | 0,032 | 0,01004 | **9,9 %** |
| banco sin IA (8 controles) | 0,081 | 0,00245 | **78,0 %** |
| banco **con CNN** (9) | 0,083 | 0,00216 | **80,6 %** |
| combinador XGBoost | 0,051 | 0,00274 | 75,5 % |

| capa | ganancia de precisión |
|---|---|
| banco de representaciones **sobre 3σ** | **+68,1 pp** |
| **CNN sobre el banco** | **+2,6 pp** |
| combinador XGBoost sobre el banco | **−5,1 pp** |

**Aviso de escala, que es la misma lección del §1(a).** La distorsión total sin
control es **0,0112 sigmas**, ~1,1 % de una desviación típica. Los porcentajes
de arriba son fracciones de **esa base pequeña**: sirven para **ordenar gates
entre sí**, no para afirmar magnitud de impacto. Es pequeña por construcción —
cada defecto ocupa un episodio de 20 sesiones dentro de una ventana de ~670.

## 4 · Figura

`docs/figuras/dq_distribucion_rendimientos.png`, cuatro paneles en Seaborn:

- **A** · densidad empírica de Brent contra la normal ajustada, escala log: las
  colas empíricas sobresalen varios órdenes de magnitud.
- **B** · QQ frente a la normal: se despega en ambas colas.
- **C** · frecuencia de superar *k* sigmas, normal contra observada, con el
  factor anotado desde 3σ.
- **D** · distorsión residual que deja pasar cada gate.

La versión de **nueve series** del diagnóstico de normalidad (paneles A-C) está
en `results/reports/dq_return_distributions/`, del documento que éste continúa;
aquí se reproduce solo para Brent para que la figura sea autocontenida junto al
panel D, que es la parte nueva.

## 5 · Lectura (solo lo que sobrevive al challenge)

1. **±3σ infraestima la frecuencia de extremos** —4,1× en Brent, 5.605× a 5σ— y
   sobreestima la masa de los hombros. De ahí no se sigue dirección de sesgo en
   capital.
2. **Un 3σ que dispara 4× lo que su supuesto promete no puede separar una cola
   real de mercado de un defecto.** Esto **motiva** el framework por
   representaciones; no lo demuestra.
3. **La demostración del valor de la IA no está aquí.** Tiene que venir de
   detección con etiquetas conocidas y test temporal — la línea de C10/C11— y no
   de una figura de densidad ni de la proyección degradada del §3.
4. El gate conforme calibra sobre la distribución empírica en vez de sobre una
   forma supuesta, pero **su garantía no es incondicional**: depende de la
   dependencia entre ventanas, del drift y del tamaño de calibración.

## 6 · Límites

- La estandarización usa media y desviación de **toda la muestra**, así que el
  diagnóstico de los §1-2 tiene **look-ahead** y es descriptivo, no un umbral
  desplegable. Misma reserva que el documento que continúa. El §3 sí usa el gate
  causal de `dq_representation_stack`.
- Defectos **sintéticos** escritos por mí, promediados con **prevalencia
  uniforme** entre familias, que es falso y no hay dato para ponderarlo.
- 124 ventanas de test que **solapan al 75 %**: no son independientes.
- Saneo **idealizado**: detectar equivale a corregir sin error ni coste. No se
  modela el coste de investigar una alerta ni el riesgo de «corregir» un
  movimiento de mercado legítimo — que en una serie con estas colas es un riesgo
  real, no teórico.
- Las capas comparan a FPR 0,032 / 0,081 / 0,083, **no idénticas**.
- Una figura de densidad **no demuestra** que CNN/XGBoost mejoren la precisión;
  eso lo sostiene el §3 con etiquetas conocidas y test temporal, no el §1.
