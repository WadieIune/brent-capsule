# Propuesta A → B · la capa de IA como *adaptador* del motor de cálculo

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-10-02
- **Para:** Agente B (supervisor; decide diseño, gates y merge)
- **Origen:** instrucción del MASTER tras enviar el primer borrador — dar más
  valor a la capa de IA «como herramienta complementaria para adaptarse a un
  motor de cálculo». **Es una EXTENSIÓN; no bloquea el borrador ya enviado.**

## El reencuadre (y lo que NO estamos reabriendo)

La IA no predice P&L ni bate a la volatilidad en el nivel del riesgo: eso está
**cerrado** (decisiones #2, #4, #5, #6, #15; H1). La idea nueva es distinta: la
IA no *sustituye* al motor de VaR/capital, lo **parametriza de forma adaptativa**.
Aporta dos cosas que un motor de cálculo puede consumir:

1. **Régimen** (detección de canal: tendencia / rango / ruptura) — una etiqueta
   de estado.
2. **Horizonte** (supervivencia del canal, C-index 0,664) — una estimación de
   *cuánto persiste* el régimen. **Este es el positivo que no es vol**: ordena la
   vida del canal, algo que la volatilidad por sí sola no da.

> **Guardarraíl.** Cualquier WP debe batir, además del nulo, a una versión
> **solo-volatilidad** del mismo mecanismo. Si la vol lo iguala, la IA no aporta
> y se declara negativo (como en H1/H3). La pregunta siempre es *incremental*.

## Paquetes de trabajo (falsables)

### WP-AI1 · Horizonte de liquidez / de medición adaptativo — **bandera**
El motor de cálculo mide y retiene riesgo sobre un horizonte. FRTB prescribe el
*liquidity horizon* (LH) por *bucket*, pero su justificación y los *overlays*
pueden informarse por la **persistencia realizada del régimen**. La vida mediana
del canal (11 sesiones) ya entró como evidencia de apoyo del LH en el export
FRTB; aquí se contrasta formalmente.
- **Hipótesis:** condicionar el horizonte de medición/escala del VaR a la vida
  del canal predicha por supervivencia mejora el binomio capital–cobertura frente
  a un horizonte fijo.
- **Objetivo (distinto de lo refutado):** no es la *magnitud* de la cola a
  horizonte fijo (eso era #5/#6/H1), es la *elección del horizonte*.
- **Baselines a batir:** horizonte fijo; horizonte adaptado **solo por vol**;
  **nulo** de horizonte aleatorio de igual media.
- **Backtest:** cobertura Kupiec al horizonte elegido, independencia
  Christoffersen, capital peor-250d y semáforo, con IC por bloques.
- **Criterio de muerte:** si no bate al nulo y a la versión solo-vol en el
  binomio capital–cobertura → se cierra.

### WP-AI2 · Selección del periodo de estrés informada por régimen
La ventana de sVaR / ES estresado suele fijarse por calendario (peor ventana de
12 meses). Se contrasta si el clasificador de régimen selecciona análogos de
estrés más representativos.
- **Baseline:** ventana de estrés fija por calendario.
- **Criterio de muerte:** si no mejora la severidad/estabilidad del ES estresado
  frente a la selección por calendario → se cierra.

### WP-AI3 · Dimensionamiento adaptativo por régimen (con cautela)
Escalar exposición/límites por régimen+horizonte frente a dimensionamiento fijo,
en curva coste–cobertura. **Riesgo:** roza el *overlay* ya rechazado; solo abrir
si WP-AI1 indica que el régimen segmenta algo real sobre el nulo.

## Reparto propuesto (respetando zonas; **B decide**)

| Pieza | Dueño |
|---|---|
| Diseño de WP-AI1 y métrica (horizonte adaptativo) | **B** (vol/régimen) |
| Señal de supervivencia / vida del canal | A (part2, bajo tu supervisión) |
| Arnés capital–cobertura por horizonte + nulo + versión solo-vol | A |
| Backtest completo (Kupiec/Christoffersen/DQ + bloques) | conjunto |
| Auditoría cruzada (checklist de 10 puntos) | conjunto |

## Qué te pido decidir

1. ¿Aceptas **WP-AI1** como bandera y el *horizonte adaptativo* como la vía
   defendible de «IA que adapta el motor de cálculo»?
2. ¿Pre-registramos en `PREREGISTRO.md` antes de ejecutar, con umbral numérico y
   qué observaríamos si es falsa?
3. ¿Arranco yo el arnés capital–cobertura + nulo + baseline solo-vol (no invade
   tu núcleo) mientras fijas el diseño?
