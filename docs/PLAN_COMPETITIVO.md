# Plan de trabajo paralelo y competitivo — cierre del paper

> **Documento de coordinación entre dos agentes.** Redactado por el Agente A tras
> auditar el repositorio en el commit `a7daf83`. Es **autocontenido**: no hace
> falta haber participado en las sesiones anteriores para ejecutarlo.
>
> **Objetivo único:** cerrar el paper con **un resultado positivo, real y
> defendible**. Hoy las tres patas del trabajo son concluyentemente negativas en
> capacidad predictiva; el paper necesita una contribución positiva que resista
> el escrutinio de un comité.

---

## 1. Estado verificado del repositorio

Ambos agentes parten de estos hechos, comprobados sobre el árbol de trabajo (no
de memoria):

| Elemento | Estado |
|---|---|
| Rama / commit | `main`, `a7daf83`, limpio y sincronizado con `origin/main` |
| Experimentos | **11**, todos importan; `pytest test` = 5/5 en verde |
| Decisiones | **5 `accept`** · **3 `review`** · **3 `reject`** |
| Datos | Todo en `data/` (cápsula autocontenida, sin descargas en ejecución) |
| Salidas | `outputs/` no se versiona (regenerable); los manifiestos van a `results/reports/` |

**Decisiones por experimento:**

| `accept` | `review` | `reject` |
|---|---|---|
| `channel_vol_forecast` | `predicted_var` | `dq_price_control` |
| `dq_impact` | `frtb_applications` | `portfolio_var` |
| `breakout_detection` | `frtb_capital` | `portfolio_var_alert` |
| `regime_markov` | | |
| `dq_daily_monitor` | | |

### Deuda técnica pendiente (WP0)

1. `results/reports/applications_summary.json` conserva rutas de ejecución
   `/tmp/final11/...` (no reproducibles por un tercero).
2. `code/applications/README.md` línea ~174 dice que los smoke tests corren
   *"los cuatro experimentos"*; son **once**.
3. **Faltan 3 manifiestos** en `results/reports/`: `dq_price_control`,
   `channel_vol_forecast`, `frtb_applications`. El entregable no cubre los 11.
4. `.pytest_cache/` no está en `.gitignore` (hoy se auto-ignora, pero es frágil).

---

## 2. Diagnóstico: dónde está el resultado real

Las tres patas son **negativas en predicción**, y esa negación está sólidamente
demostrada por tres vías independientes:

- **1ª pata** — detección de canal AUC 0.97, pero DSR ≈ 0 → sin ventaja direccional.
- **2ª pata** — vida del canal ordenable (C-index 0.664), dirección de ruptura
  AUC 0.766, pero DSR 0.014 → acertar la banda de salida no es ganar dinero.
- **3ª pata** — la fragilidad de canal **no** anticipa la cola: *lift* 0.00 frente
  a 3.19 de la volatilidad EWMA, correlación −0.12, y una constante del mismo VaR
  medio iguala al *overlay*.

**El resultado positivo existe y es `dq_impact`.** Está subdesarrollado como
contribución, pero es la apuesta fuerte por una razón que conviene entender bien:

> Su ventaja **no es empírica sino estructural**. Un retorno exactamente cero
> *nunca* puede ser un valor atípico de cola; por tanto un control convencional
> es **ciego por construcción** —no por mala calibración— al relleno de
> calendario y al precio congelado. Eso no se cae ante un baseline mejor.

Evidencia ya disponible: depurar los defectos corrige **74.4 puntos porcentuales**
de distorsión en la contribución al riesgo (la del WTI baja de 0.985 a 0.240) y
elimina el 31.1 % de retornos nulos. El monitor diario opera con **1.63 %** de
carga (459 alertas / 28.086 obs) frente a 30 marcas del control convencional.

**Lo que le falta para ser publicable:** *ground truth*. Hoy se sostiene sobre
**2 defectos reales** (n = 2). Necesita **inyección sintética de defectos** con
verdad conocida para poder reportar precisión/recall/AUC-PR frente a baselines
serios.

---

## 3. La lección del VaR — regla innegociable

El resultado del VaR se publicó, y **se cayó**, porque se comparaba contra un
baseline débil (VaR histórico) en lugar de contra el baseline fuerte (FHS-EWMA) y
sin control de nivel (una constante del mismo VaR medio). Tres defectos de datos
lo agravaron: precio negativo del WTI, calendario en vez de días hábiles, y
ausencia de ese control.

> ### Regla
> **Ningún `accept` sube a titular del paper sin haber sido contrastado contra un
> baseline fuerte y un control de nivel.**

**Aplicación inmediata:** `channel_vol_forecast` (AUC 0.716) presenta hoy el mismo
patrón de riesgo — se compara contra 0.5 y contra "geometría sin supervivencia",
**no contra un baseline de volatilidad** (EWMA, GARCH, vol realizada). Antes de
promoverlo hay que auditarlo (WP3). Es preferible degradarlo a `review` nosotros
mismos que hacerlo un revisor.

---

## 4. Protocolo competitivo

Competir solo suma si los resultados son comparables y el ganador no se elige
*a posteriori*.

1. **Pre-registro obligatorio.** Hipótesis, métrica, baseline y umbral de éxito se
   escriben en `docs/PREREGISTRO.md` **antes** de ejecutar nada. Elegir el ganador
   después de ver los números es exactamente el sesgo de selección que el paper
   denuncia con DSR/PBO: sin pre-registro, la competición invalida el trabajo en
   lugar de reforzarlo.
2. **Mismo dato, mismo split, mismo harness.** Corte `2020-08-20`, **días
   hábiles**, `RunContext`/manifiesto ARF. Cualquier desviación se documenta en el
   pre-registro.
3. **Independencia.** Ningún agente consulta resultados intermedios del otro hasta
   la adjudicación.
4. **Adjudicación contra el pre-registro**, no contra la impresión. **Se publican
   ambos tracks, gane quien gane**: un `reject` documentado vale tanto como un
   `accept` y es coherente con el resto del proyecto (3 de 11 ya lo son).

---

## 5. Paquetes de trabajo

Orden: **WP0 → WP1 → (WP2-A ‖ WP2-B ‖ WP3) → WP4**

### WP0 · Higiene del repositorio
**Dueño:** Agente A · **Momento:** inmediato · **Bloquea:** todo lo demás

Resolver los 4 puntos de deuda técnica de §1. Criterio: `git status` limpio,
11/11 manifiestos en `results/reports/`, sin rutas `/tmp` en entregables.

### WP1 · Pre-registro
**Dueño:** Agente A · **Momento:** antes de WP2 · **Bloquea:** WP2-A, WP2-B

Redactar `docs/PREREGISTRO.md` con la plantilla de §7, una ficha por track.
Criterio: cada track tiene hipótesis falsable, métrica primaria única, baseline
fuerte nombrado, umbral numérico y regla de parada.

### WP2-A · Track A — Calidad de dato *(apuesta principal)*
**Dueño:** Agente A · **Zona:** `code/applications/experiments/dq_*`

Validar el control geométrico con **verdad conocida**:

- **Inyección sintética** de familias de defecto sobre serie limpia, a tasas
  controladas: *stale/relleno*, *salto reversible*, *outlier de cola*, *precio no
  positivo*, *desfase de calendario*.
- **Baselines fuertes** (no basta el cuantil de |retorno|): Hampel / MAD, vallas
  de Tukey, *isolation forest*, detector de rachas constantes.
- **Métricas**: AUC-PR por familia (la clase positiva es rara → PR, no ROC),
  precisión/recall al umbral operativo, e **impacto en unidades de riesgo**.
- **Demostrar el punto ciego**: recall del baseline ≈ 0 en las familias donde el
  argumento estructural predice ceguera.

**Éxito:** gana en AUC-PR con IC *bootstrap* que excluye 0 en al menos las
familias "ciegas", **y** el impacto en riesgo es material.

### WP2-B · Track B — Régimen operativo
**Dueño:** Agente B · **Zona:** `code/part2_channel_survival/`, `experiments/regime_*`, `breakout_*`

Convertir la capacidad descriptiva ya demostrada (C-index 0.664; Markov +0.61
log-verosimilitud/obs; distancia al borde AUC 0.677 con *lead time* 6 sesiones)
en **valor operativo medible**:

- Política de revisión/horizonte guiada por supervivencia **frente a** calendario
  fijo (el statu quo).
- Métrica en **curva coste-cobertura**: ¿menos revisiones a igual cobertura de
  cambios de régimen, o más cobertura a igual coste?
- Debe incluir baseline fuerte: política de calendario **óptimamente calibrada**,
  no una ingenua.

**Éxito:** domina la curva coste-cobertura en el tramo operativo relevante.

### WP3 · Auditoría de baseline fuerte
**Dueño:** el agente que termine antes su WP2

Re-testar `channel_vol_forecast` contra EWMA, GARCH(1,1) y vol realizada.
**Éxito:** sobrevive con margen, **o** se degrada a `review` con honestidad. Las
dos salidas son válidas; ocultarlo no.

### WP4 · Adjudicación e integración
**Dueño:** ambos, secuencial (nunca simultáneo en `docs/`)

Contrastar resultados contra el pre-registro, elegir el titular, integrar en
LaTeX + HTML, actualizar `PROJECT_LEDGER.md`, commit y push.

---

## 6. Reglas anti-colisión

| Zona | Dueño exclusivo |
|---|---|
| `code/applications/experiments/dq_*` | Agente A |
| `code/part2_channel_survival/`, `experiments/regime_*`, `breakout_*` | Agente B |
| `docs/` | **Solo en WP4**, un agente cada vez |
| `results/reports/` | Solo escribe quien ejecuta su propio experimento |

**Ramas:** `track-a` y `track-b`, creadas desde `a7daf83`; merge a `main` en WP4.

**Rutina de cada sesión:**
```bash
git pull --ff-only origin main     # antes de empezar
# ... trabajo ...
git add -A && git commit && git push origin <tu-rama>
```

**Prohibido sin acuerdo previo:** tocar `data/`, `.gitignore`, `harness.py` y
`common.py` (infraestructura compartida: romperlos bloquea al otro agente).

---

## 7. Plantilla de pre-registro

Una ficha por track en `docs/PREREGISTRO.md`:

```markdown
## Track <A|B> — <título>
- **Hipótesis (falsable):** …
- **Métrica primaria (una sola):** …
- **Baseline fuerte:** …            # débil no vale; nombrar el método concreto
- **Control de nivel / ablación:** …  # ¿qué descarta la explicación trivial?
- **Datos y split:** corte 2020-08-20, días hábiles, n_test esperado ≈ …
- **Umbral de éxito (numérico, previo):** …
- **Regla de parada:** …            # nº de configuraciones a probar, fijado ya
- **Qué observaríamos si la hipótesis es FALSA:** …
```

El último punto no es retórico: si no se sabe de antemano qué aspecto tendría un
fracaso, no hay hipótesis falsable y el experimento no puede pre-registrarse.

---

## 8. Definición de "hecho"

Un WP está cerrado cuando cumple **todo**:

- [ ] Corre de extremo a extremo con `run_all.py` y deja manifiesto ARF.
- [ ] `pytest test` en verde.
- [ ] Baseline fuerte y control de nivel documentados **en el manifiesto**.
- [ ] Manifiesto copiado a `results/reports/`, sin rutas `/tmp`.
- [ ] Resultado reportado **con su signo real**: `reject` se publica igual que `accept`.
- [ ] Sin rutas absolutas ni dependencias de red (la cápsula debe seguir siendo
      reproducible por la revista).

---

## 9. Reencuadre del paper

De *"chartismo para alpha"* (negativo, confirmado tres veces) a **"geometría del
canal como control de calidad de dato de mercado y descriptor de régimen"**
(positivo, medible, con encaje en BCBS 239).

Con este marco, los tres resultados negativos dejan de ser el problema y pasan a
ser **la credibilidad que respalda el positivo**: un trabajo que descarta sus
propias hipótesis rentables y aun así encuentra valor donde el dato lo sostiene
es mucho más defendible ante un comité que uno que solo reporta aciertos.
