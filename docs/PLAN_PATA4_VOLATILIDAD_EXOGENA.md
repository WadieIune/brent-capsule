# Plan de la 4ª pata — del precio a la volatilidad, y de la geometría a la información

> **Propuesta conjunta A + B.** Redactada por A a partir de la idea del usuario y
> del informe de B (`auditorias/2026-09-10-B-revision-regimen-volatilidad.md`),
> que ya proponía el pronóstico de varianza. Este documento la extiende con la
> capa exógena y la aplicación de riesgo, y reparte el trabajo.

---

## 1. El diagnóstico del usuario, confirmado con datos

> «Los precios son por definición estocásticos […] los canales han funcionado en
> identificar la tendencia pero no podemos asegurar su continuidad ni su
> supervivencia […] ¿no sería mejor transformar la serie a volatilidad?»

Es exactamente lo que muestran nuestros propios contrastes, y ahora también la
estructura de la serie:

| Medida sobre el Brent (1987–2026) | Valor | Lectura |
|---|---|---|
| Autocorrelación del **retorno**, lag 1 | **−0.013** | El precio es, a efectos prácticos, un paseo aleatorio |
| Autocorrelación de **\|retorno\|**, lag 1 | **+0.258** | La volatilidad **sí** tiene estructura |
| Autocorrelación de **\|retorno\|**, lag 5 | +0.231 | …y persiste |
| Autocorrelación de **\|retorno\|**, lag 20 | **+0.167** | …con memoria larga |

Esto explica **por qué fracasaron las tres primeras patas y por qué esta puede no
hacerlo**: estábamos aplicando reconocimiento de formas sobre el único aspecto de
la serie que no tiene memoria. La volatilidad, que sí la tiene, quedó como
subproducto. Nuestros propios nulos lo anticipaban: un paseo aleatorio reproducía
los resultados de canal (C1, C2) porque el canal vive en el espacio del precio.

**Estacionalidad:** existe, pero es modesta —la volatilidad media de marzo
(1.95 %) es 1.38 veces la de julio (1.42 %)—. Merece corregirse por higiene, no
como fuente principal de señal.

---

## 2. Advertencia que condiciona todo el diseño: episodios, fuentes y 2026

La cadena causal que describe el usuario —shock en el Brent → inflación → subida
de tipos → caída de producción— es real y está documentada en la literatura. Pero
para **entrenar** un modelo que la explote, el recuento de episodios independientes
sigue siendo limitado. Además, antes de contar episodios hay que fijar la fuente
de precio: el panel ancho corta antes que la serie FRED separada, y mezclar ambos
artefactos cambia la conclusión sobre 2026.

Fuente mandante para cualquier afirmación sobre 2026: `data/brent_fred_daily.csv`
(`sha256=f6f80761627e99b897325bbe7485e6f2463d8d6dd429df4ec5cec7c30f328ef9`),
con muestra 1987-05-20 a 2026-06-29. Volatilidad descriptiva: desviación muestral
móvil de 20 log-retornos × raíz de 252, sin relleno de calendario.

| Episodio descriptivo | Días entre los 400 de mayor volatilidad | Vol. máxima |
|---|---|---|
| Crisis 2008 | 139 | 107 % |
| COVID 2020 | 78 | 170 % |
| Ucrania 2022 | 43 | 92 % |
| **2026 reciente, sin atribución causal cerrada** | **44** | **112.4 %** |

Dos consecuencias que hay que asumir antes de escribir una línea de código:

1. **Un modelo de «anticipación de shocks» no puede entrenarse como si unos pocos
   conflictos fueran miles de episodios independientes.** Las ventanas solapadas
   ayudan a medir demora y fragilidad, pero no multiplican los shocks.
2. **2026 sí aparece en la serie FRED disponible, pero no como prueba causal de
   Ormuz por sí sola.** La muestra termina el 2026-06-29: cubre parte de 2026, no
   un supuesto periodo de septiembre. El máximo anualizado de 2026 es 112.4 % el
   2026-04-17 y hay 44 observaciones de 2026 entre las 400 más volátiles. La
   atribución a Ormuz, Ucrania, demanda u otra causa exige fechas externas y
   contraste específico.

**Reformulación honesta del objetivo.** No perseguimos predecir el evento
—eso es noticia, no serie—, sino tres cosas con muestra suficiente (miles de
observaciones, no tres):

- **(a) *Nowcast* del régimen de volatilidad**: reconocer la transición **antes**
  que un VaR de ventana móvil, que por construcción reacciona tarde.
- **(b) Medida de fragilidad condicional**: en qué estados un shock haría más
  daño, para dimensionar exposición **antes** de que ocurra.
- **(c) Reducción del retraso de reacción**: cuántos días se gana frente al
  procedimiento estándar, medido en excepciones evitadas y capital.

Eso sí es defendible ante un comité, y sigue siendo exactamente lo que un
*risk director* necesita.

---

## 3. Las tres patas unidas: CNN → información → decisión de riesgo

```
   PATA 1 (CNN)              PATA 2 (información)          PATA 3 (riesgo)
   ─────────────             ────────────────────          ───────────────
   Serie de VOLATILIDAD      Variables exógenas de la      Nowcast de régimen
   (no de precio)            cadena causal conocida:       ↓
   desestacionalizada        tipos, dólar, VIX,            Fragilidad condicional
   ↓                         spread 10Y-2Y, WTI-Brent      ↓
   Imagen GASF/GADF          ↓                             Dimensionamiento y
   sobre log-varianza        ¿aportan sobre HAR?           límites; capital
```

La diferencia esencial con lo anterior: **cada pata tiene que justificar su
existencia contra la pata anterior**. Si la CNN sobre volatilidad no bate a HAR,
se cae. Si lo exógeno no aporta sobre la vol propia, se cae. Si el *nowcast* no
reduce el retraso de reacción, se cae. Nada se hereda por inercia.

---

## 4. Paquetes de trabajo y reparto

Respetando las zonas actuales: **B es propietario de régimen y volatilidad**, y
ya tiene diseño propuesto. A aporta la capa exógena y la aplicación de riesgo.

### WP-V1 · Núcleo de pronóstico de varianza — **dueño: B**
El diseño que B ya propuso, que respaldo íntegro: objetivo íntegramente futuro
(media de `r(t+j)²`, j=1..10), **QLIKE pareado** como métrica primaria, baselines
**EWMA / GARCH / HAR**, purga de las diez sesiones antes de cada corte, y
selección solo en entrenamiento/validación.

Aportaciones mías al diseño, ya enviadas: declarar el **proxy de varianza
realizada** en el pre-registro (con solo cierres, `r²` diario es muy ruidoso);
resolver la **procedencia del artefacto CNN** antes de la ablación `base+CNN`; y
usar un **nulo heterocedástico** (GARCH simulado) en vez del paseo aleatorio
homogéneo, que no controla *clustering* de volatilidad.

### WP-V2 · Transformación de la serie — **dueño: A**
Preparar el sustrato sobre el que trabajarán las demás patas:
- **Desestacionalización** de la volatilidad (componente mensual, ratio 1.38).
- **Log-varianza realizada** como serie objetivo, que es aproximadamente normal y
  estabiliza la varianza —mejor sustrato para cualquier modelo que `r²` crudo.
- **Reconstrucción de la imagen GASF/GADF sobre la serie de volatilidad**, no
  sobre el precio. Es la traducción literal de la idea del usuario y permite
  reutilizar toda la maquinaria de la 1ª pata sobre un objeto que **sí** tiene
  memoria.
- Entregable: serie limpia y versionada + generador de imágenes de vol.

### WP-V3 · Capa exógena — **dueño: A**
Contrastar si la cadena causal conocida aporta **sobre la volatilidad propia**:
- Variables (todas ya en el panel): **VIX**, **DTWEXBGS** (dólar), **DGS2 /
  DGS10** y el **spread 10Y−2Y**, **SPREAD_WTI_BRENT** y **NATGAS**.
- Hipótesis dirigida, no minería: la transmisión conocida es *shock de crudo →
  inflación → tipos*, de modo que el **orden temporal** es contrastable con
  causalidad de Granger y con *lead-lag* explícito.
- **Baseline obligatorio: HAR sobre la propia volatilidad del Brent.** La
  pregunta es *incremental*, nunca «¿mejora sobre 0.5?».
- **Aviso que hay que dejar por escrito**: la 1ª pata ya demostró que el
  *cross-asset* **degradaba** la detección de la geometría del canal. Eso **no**
  cierra esta puerta —predecir volatilidad es otra pregunta distinta— pero
  obliga a enunciar la diferencia explícitamente para no parecer que reabrimos
  algo ya refutado.

### WP-V4 · Aplicación de riesgo — **dueño: A, con validación de B**
Convertir el *nowcast* en las tres métricas del §2:
- **Retraso de reacción**: días que tarda un VaR de ventana móvil en incorporar
  un cambio de régimen, frente al modelo condicionado. Medido en los tres
  episodios reales **como caso de estudio, no como entrenamiento**.
- **Excepciones evitadas y capital**: sobre el mismo marco de Kupiec /
  Christoffersen / semáforo de Basilea ya montado.
- **Fragilidad condicional**: dimensionamiento por régimen frente a
  dimensionamiento fijo, en curva coste–cobertura, con el control aleatorio de
  igual frecuencia que ya usamos.

### WP-V5 · Pre-registro y adjudicación — **conjunto**
Ficha por WP en `PREREGISTRO.md` **antes de ejecutar**, con umbral numérico y
qué observaríamos si la hipótesis es falsa. Y auditoría cruzada obligatoria: lo
de A lo desafía B y viceversa, con la checklist de 10 puntos.

---

## 5. Trampas identificadas de antemano

Las escribo ahora para que no nos pillen después, y para que el challenge del
otro las use:

| # | Trampa | Mitigación |
|---|---|---|
| 1 | **n=3 episodios de shock** | No entrenar en episodios; usarlos solo como caso de estudio. La afirmación se sostiene sobre miles de observaciones de régimen, no sobre tres eventos |
| 2 | **Solapamiento de ventanas** (nos tumbó C2) | Ventanas de varianza no solapadas o purga explícita; nulo que preserve la persistencia mecánica |
| 3 | **Look-ahead en la desestacionalización** | El componente estacional se estima **solo con train** y se aplica al test |
| 4 | **`r²` es un proxy ruidoso de varianza** | Declarar el proxy; reportar robustez con varianza agregada a 10 días |
| 5 | **Selección sobre test** (me pasó en WP3) | Elección de modelo en validación temporal, siempre |
| 6 | **Bootstrap i.i.d. con objetivos solapados** | Remuestreo **por bloques**, ya adoptado |
| 7 | **Cross-asset ya refutado para geometría** | Enunciar que la pregunta es otra; exigir ganancia incremental sobre HAR |
| 8 | **La CNN podría no aportar sobre HAR** | Ablación obligatoria: base / base+geometría / base+CNN. Si la CNN no añade, se dice |

---

## 6. Qué haría fracasar esta pata (criterio previo)

Para que sea una hipótesis y no una esperanza:

- Si la CNN sobre volatilidad **no bate a HAR** en QLIKE con IC por bloques que
  excluya el cero → la parte CNN se cierra, y quedaría el trabajo de vol clásico.
- Si lo exógeno **no aporta sobre HAR** → se cierra la capa de información y el
  resultado es «la volatilidad del Brent se explica por su propia historia».
- Si el *nowcast* **no reduce el retraso de reacción** frente al VaR estándar →
  no hay aplicación de riesgo, por buena que sea la predicción estadística.

Cualquiera de las tres es publicable como negativo, en coherencia con el resto
del trabajo. Pero **si las tres se sostienen**, tenemos por primera vez una
cadena completa: *señal con memoria → información exógena con mecanismo causal
conocido → decisión de riesgo con impacto medible en capital*. Que es
exactamente lo que faltaba para cerrar el paper.

---

## 7. Siguiente paso inmediato

1. **B confirma** si acepta el reparto y si su WP-V1 absorbe o convive con WP-V2.
2. **A ejecuta WP-V2** (transformación y sustrato), que no invade la zona de B y
   desbloquea a ambos.
3. **Pre-registro conjunto** antes de cualquier evaluación.
