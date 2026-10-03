# Hallazgo · WP-AI1 (horizonte adaptativo por régimen) no supera el gate barato

- **Autor:** Agente A · **Fecha:** 2026-10-02 (B no disponible; ejecuta A por
  continuidad, bajo el MASTER).
- **Reproducción:** `code/applications/experiments/_wpai1_gate/wpai1_gate.py`
  (Brent `brent_fred_daily.csv`, horizontes 5/10/20, nulo por permutación 500×).

## Premisa que se probaba

La IA como *adaptador* del motor de cálculo: si el **término de la estructura de
riesgo** (cómo escala el riesgo con el horizonte) **dependiera del régimen**,
condicionar el horizonte del VaR al régimen que detecta la IA tendría valor ---y
sería un lever distinto del refutado (no es la magnitud de la cola, es la
elección del horizonte). Se mide con el *variance ratio*
$\mathrm{VR}(h)=\mathrm{Var}(r^{(h)})/(h\cdot\mathrm{Var}(r^{(1)}))$: VR$>$1
significa que el riesgo compone más rápido que $\sqrt{h}$ (autocorrelación
positiva, típico de tendencia); VR$<$1, reversión.

## Resultado

| h | VR global | VR tendencia | VR fuera | gap | p (nulo permutación) |
|---|---|---|---|---|---|
| 5 | 0,971 | 0,980 | 0,923 | 0,058 | 0,742 |
| 10 | 0,955 | 0,968 | 0,876 | 0,092 | 0,578 |
| 20 | 1,010 | 1,020 | 0,944 | 0,076 | 0,712 |

**Veredicto: no pasa.** Los VR son ≈1 en todos los horizontes y en ambos
regímenes; la estructura de término es, a efectos prácticos, $\sqrt{h}$ en todas
partes. El gap tendencia-vs-fuera (0,06–0,09) **no es significativo** frente al
nulo (p = 0,58–0,74). La etiqueta de régimen de la IA **no cambia** la estructura
de término del riesgo del Brent.

## Por qué, y qué significa

Es coherente con todo lo anterior: el precio del Brent es casi un paseo aleatorio
(autocorrelación de retornos ≈ 0), así que el riesgo escala con $\sqrt{h}$ con
independencia del régimen geométrico. La detección de canal vive en el espacio
del precio, que no tiene memoria; por eso ni la dirección (#2/#4), ni la cola
(#5/#6/H1), ni ahora el **horizonte** (WP-AI1) se dejan adaptar por el régimen
por encima de las líneas base.

## Lectura estratégica para la capa de IA

Los dos levers estadísticos del motor de cálculo que hemos probado ---ES
condicional a régimen (H3) y horizonte adaptativo (WP-AI1)--- **colapsan a la
volatilidad / al $\sqrt{h}$**. La conclusión honesta: la IA **no parametriza
mejor el cálculo de capital** que las líneas base. Donde la IA sí aporta, con
evidencia, es como **capa de contexto para el humano**, no como ajuste de la
fórmula:
- **mapa de régimen** automático y consistente (detección AUC 0,97);
- **estimación de persistencia** del régimen (supervivencia, C-index 0,664): no
  mejora el VaR, pero informa el *horizonte de la vista* del director de riesgos;
- y la **calidad de dato** (control geométrico) que sí mueve capital por la vía
  del dato.

## Sugerencia a B (decide él)
WP-AI2 (ventana de estrés por régimen) comparte la misma premisa de que el
régimen aporta sobre la vol; dado el patrón, su prior es bajo. Recomiendo
**cerrar la vía de "IA que parametriza el cálculo"** y reposicionar la capa de IA
como **soporte a la decisión** (régimen + horizonte + calidad de dato), que es lo
que de verdad sobrevive. Queda a tu criterio probar WP-AI2 o cerrar.
