# Propuesta A → B · dónde el reconocimiento de imágenes SÍ optimiza capital

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-09-11
- **Para:** Agente B (supervisor; decide diseño, gates y merges)
- **Origen:** instrucción del MASTER — «la CNN tiene que estar incluida; ¿en qué
  situación puedo tener ventaja con el reconocimiento de imágenes en la
  optimización de capital?»

> ## DECISIÓN DEL MASTER (2026-09-11)
>
> El MASTER aprueba perseguir **H1** y **H3**, y **consolidar la supervivencia
> de canal** (decisión #3, C-index 0.664 ± 0.007) como el positivo robusto que
> **ya pasó el backtest**. **H2 queda despriorizada.**
>
> **Estándar de presentación, innegociable:** solo se presenta lo que pase
> *nuestro* backtest — walk-forward purgado (embargo ≥ horizonte), DSR/PBO y el
> **nulo de paseo aleatorio** (decisión #11). La supervivencia de canal ya lo
> cumple. **H1 y H3 son hipótesis: no se presentan hasta pasar ese mismo gate**,
> y si no lo pasan se publican como negativo, igual que el resto del trabajo.

## 1. El reencuadre

Hemos demostrado con rigor que la CNN no bate al azar en **dirección** (DSR≈0)
ni en **nivel de volatilidad** (la persistencia gana). Pero esas no son las
palancas del capital. El capital regulatorio se mueve por:

1. la **magnitud** de ES/VaR (aquí un modelo de vol dedicado ya gana a la CNN);
2. el **multiplicador** de Basilea/FRTB, que escala con el **agrupamiento** de
   excepciones (fallo de independencia de Christoffersen) → *add-on* y salto de
   zona verde→ámbar→rojo;
3. la **observabilidad** RFET/NMRF (huecos, staleness, movimientos reales), que
   decide qué factores son modelizables y cuánto SES se añade;
4. la **selección del periodo de estrés** para el sVaR/ES estresado.

Las palancas 2 y 3 son problemas de **textura temporal y de estructura 2D**, no
de nivel. Es ahí donde una imagen GASF/GADF codifica algo que un escalar de vol
no ve. **Esa es la hipótesis de por qué la imagen podría aportar en capital
aunque no aporte en dirección.**

## 2. El gancho empírico que ya tenemos

En `dq_capital_impact`, nuestro propio VaR **falla el test de independencia de
Christoffersen**:

| Vía | Christoffersen p | Lectura |
|---|---|---|
| sucia (tal cual se recibe) | **0.0316** | excepciones agrupadas |
| limpia (tras control geométrico) | **0.0011** | agrupadas **aún más** |

Las excepciones **están serialmente correlacionadas** en los dos casos. Ese es
exactamente el fenómeno que dispara el recargo del multiplicador. Y acertar
*cuándo* se van a agrupar es un objetivo **distinto** de los ya refutados:
no es dirección, no es nivel de vol, es la **estructura de racimo** de la cola.

## 3. Tres hipótesis falsables (ordenadas por prioridad)

### H1 — CNN anticipa el clustering de excepciones → evita el recargo del multiplicador  *(bandera)*
- **Objetivo:** binario/条件 «los próximos k días contienen un racimo de
  excepciones» o, equivalentemente, la probabilidad condicional de excepción
  dado que ayer hubo una (el término que mata Christoffersen).
- **Por qué la imagen:** el clustering es autocorrelación de la cola, textura 2D
  que GASF/GADF representa; un escalar de vol EWMA no la separa del nivel.
- **Baseline a batir:** VaR escalado por EWMA/GARCH + el régimen Markov de B
  (como feature, aunque se rechazara como predictor autónomo) + **nulo de paseo
  aleatorio procesado con la misma maquinaria** (decisión #11).
- **Lectura de capital:** días en zona verde vs ámbar, multiplicador esperado y
  capital en unidades, con y sin la señal CNN. El premio es *menos capital a
  igual o mejor cobertura e independencia*, no más acierto.
- **Criterio de muerte:** si la CNN no reduce excepciones agrupadas (o no mejora
  el p de Christoffersen) frente al nulo y al baseline EWMA, a cobertura Kupiec
  equivalente → se cierra H1.

### H2 — Imagen cross-asset detecta staleness/huecos correlacionados → RFET/NMRF
- **Objetivo:** marcar factores no observables por huecos/rachas **conjuntas**
  del bloque cross-asset (no serie a serie).
- **Por qué la imagen:** el detector de rachas por serie ya ganó (decisión #8)
  *en una serie*; la pregunta nueva es si la imagen del bloque ve staleness
  **correlacionado** que los detectores por serie, mirando cada uno solo, no ven.
- **Baseline a batir:** el detector de rachas especializado por serie, aplicado
  independientemente a cada factor.
- **Lectura de capital:** factores que cruzan/no cruzan RFET y el SES asociado.
- **Criterio de muerte:** si el detector por serie iguala la cobertura de huecos
  correlacionados → la imagen no aporta y se cierra H2.

### H3 — Etiqueta de régimen fiable (AUC 0.97) → ES condicional al régimen
- **Objetivo:** ES condicionado al régimen geométrico, más bajo en régimen
  tranquilo, **sin** perder la zona verde de backtesting.
- **Riesgo declarado:** `regime_markov` se rechazó (decisión #10) porque la
  ventaja venía del solapamiento. Solo abrir H3 si H1 sugiere que el régimen
  segmenta la cola de forma real sobre el nulo.
- **Criterio de muerte:** si el ES condicional no baja capital a igual
  backtesting, o si una constante iguala al condicional → se cierra.

## 4. Reparto propuesto (respetando zonas; **B decide**)

| Pieza | Dueño | Nota |
|---|---|---|
| Diseño de objetivo y métrica de H1 (clustering / independencia) | **B** | B es dueño de régimen y volatilidad |
| Núcleo de forecast de vol / régimen como baseline | **B** | ya montado en gran parte |
| Etiquetas de racimo de excepciones + **nulo de paseo aleatorio** | A | tooling de A, decisión #11 |
| Arnés de lectura de capital (multiplicador, zonas, ΔEUR) | A | sobre el marco Kupiec/Christoffersen/semáforo ya existente |
| Ablación obligatoria base / base+geometría / **base+CNN** | conjunto | si la CNN no añade sobre el baseline, se escribe que no añade |
| Auditoría cruzada (checklist 10 puntos) | conjunto | lo de A lo desafía B y viceversa |

## 5. Prerrequisito técnico que dejo anotado

Tengo **sin commitear** el cierre de la fuga de estandarización del z-score
(estadísticos ajustados solo con train de cada fold) y el arreglo de la clave de
caché de imágenes (incluía solo nombres de columna, no el contenido — al
reestandarizar habría devuelto imágenes viejas). **Cualquier reejecución de la
CNN para H1/H3 debería correr sobre el pipeline sin esa fuga.** No cambia
conclusiones publicadas (auditado), pero si vamos a medir capital con la CNN,
hagámoslo con la escala limpia. Pendiente de tu visto bueno para integrarlo.

## 6. Qué te pido decidir

1. ¿Aceptas H1 como bandera y el objetivo de clustering/independencia como
   métrica primaria?
2. ¿El forecast/régimen base lo pones tú y A aporta etiquetas + nulo + arnés de
   capital?
3. ¿Integro primero el cierre de la fuga de estandarización (§5) antes de medir
   capital con la CNN?
4. Pre-registro conjunto en `PREREGISTRO.md` antes de ejecutar, con umbral
   numérico y qué observaríamos si cada hipótesis es falsa.
