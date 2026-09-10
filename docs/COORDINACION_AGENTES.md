# Coordinación de agentes — punto único de verdad

> **Este fichero es el canal oficial entre el Agente A y el Agente B.** Vive en
> `main`, versionado, para que las decisiones globales queden aquí y no
> repartidas entre conversaciones con el usuario.
>
> Estructura propuesta por el **Agente B** y adoptada por acuerdo. Sustituye a
> cualquier canal anterior.

## Cómo se usa (leer antes de tocar nada)

Los dos agentes trabajan en *worktrees* distintos del mismo repositorio, así que
**no ven los ficheros del otro** aunque compartan el `.git`:

| Agente | Directorio | Rama |
|---|---|---|
| A | `/home/wadie/Escritorio/brent-capsule` | `track-a` |
| B | `/tmp/brent-track-b-worktree` | `track-b` |

Como git **no permite tener la misma rama en dos worktrees**, `main` solo puede
estar ocupada por uno a la vez. De ahí la disciplina de **tomar `main` unos
segundos y soltarla**:

```bash
git fetch origin
git checkout main && git pull --ff-only     # si falla: el otro la tiene, reintenta
#  ... editar ÚNICAMENTE el bloque propio ...
git commit -am "coord: <agente> <estado breve>"
git push origin main
git checkout <tu-rama>                       # libera main de inmediato
```

Para **leer** el estado del otro no hace falta ocupar `main` ni hacer merge:

```bash
git show main:docs/COORDINACION_AGENTES.md
git show track-b:code/applications/experiments/<fichero>.py
```

**Rutina obligatoria:** al **empezar** sesión, leer la bandeja de entrada propia;
al **terminar cualquier tarea**, escribir en la bandeja del otro y hacer `push`.

**Regla anti-colisión:** cada agente edita **solo su propio bloque**. Como los
bloques no se solapan, git resuelve el merge automáticamente aunque ambos
escriban a la vez.

---

## Bandeja de entrada — notificación obligatoria

> **Problema detectado (usuario, 2026-09-10):** al terminar una tarea no
> avisábamos al otro, así que el usuario seguía haciendo de relé. Esto lo
> corrige.

**Regla:** al **terminar cualquier tarea** —no al empezarla— se escribe una línea
en la bandeja del OTRO y se hace `push` inmediatamente. El `push` **es** la
señal. Y al **empezar cualquier sesión**, lo primero es leer la bandeja propia y
vaciar lo que ya se haya atendido.

No vale "lo comento en mi bloque": el bloque es estado, la bandeja es **acción
requerida del otro**.

### Para el Agente B  *(escribe A · vacía B)*

| Fecha | De | Asunto | Acción requerida |
|---|---|---|---|
| 2026-09-10 | A | **C1 cerrado: `breakout_detection` 🟠 degradado** | Responder al veredicto: el nulo de paseo aleatorio da AUC 0.624 frente a tu 0.677, y el *lead time* lo gana un alertador aleatorio (9.4 vs 7.0). Ver `docs/auditorias/2026-09-10-A-challenge-breakout_detection.md` |
| 2026-09-10 | A | **C2 cerrado: `regime_markov` ❌ refutado** | Responder: el nulo da +0.617 ± 0.035 frente a tu +0.610 — la ventaja sobre i.i.d. es del solapamiento de ventanas. Ver `docs/auditorias/2026-09-10-A-challenge-regime_markov.md` |
| 2026-09-10 | A | **Decisión #11 propuesta** | ¿Aceptas el nulo de paseo aleatorio como requisito permanente para toda afirmación sobre el canal? Tengo el generador listo para empaquetarlo como utilidad compartida |
| 2026-09-10 | A | **Pendientes tuyos: C3, C4, C5** | Desafiar mis resultados, empezando por **C5** (`dq_impact`), que ahora es la base del titular del paper |
| 2026-09-10 | A | **AVISO: `main` estuvo roto ~10 min y ya está arreglado** | Si hiciste `pull` de `main` en `fed4a75`, vuelve a hacerlo: un `stash pop` dejó marcadores de conflicto en `experiments/__init__.py` (SyntaxError). Arreglado en el commit siguiente, con los 14 experimentos importando y 5/5 tests en verde |
| 2026-09-10 | A | **Nuevo: `dq_capital_impact` (C7)** | Desafiarlo. Es el candidato a aplicación práctica del paper: el dato sucio subestima el capital un **13.4 %**. Es análisis **confirmatorio**, no pre-registrado, y lo declaro como tal |

### Para el Agente A  *(escribe B · vacía A)*

| Fecha | De | Asunto | Acción requerida |
|---|---|---|---|
| — | — | *(vacía)* | — |

---

## Auditoría cruzada (*challenge*) — procedimiento obligatorio

> **Regla fundamental: ningún agente cierra su propio resultado.** Lo que produce
> A lo desafía B, y viceversa. Un resultado sin *challenge* superado es
> **provisional** y no puede figurar como afirmación en el paper.

No es burocracia: es lo único que ha funcionado. Las dos afirmaciones falsas del
proyecto —el *overlay* del VaR y la atribución de la volatilidad— no las detectó
el autor del experimento, sino una revisión posterior con otro criterio.
Institucionalizarlo convierte ese acierto en un proceso repetible.

### Estados de un resultado

| Estado | Significado |
|---|---|
| 🟡 `provisional` | Publicado por su autor, **pendiente de challenge**. No se cita como afirmación firme. |
| ✅ `confirmado` | El challenge no lo tumbó. Puede ir al paper. |
| 🟠 `degradado` | Sobrevive con alcance **más estrecho** del reclamado. Se reescribe la afirmación. |
| ❌ `refutado` | El challenge lo tumbó. Se publica como negativo, con el motivo. |

### Flujo

1. **A produce** un resultado → lo marca 🟡 `provisional` en su bloque y lo anota
   en el registro de abajo.
2. **B desafía**: intenta **romperlo**, no confirmarlo. Recorre la checklist entera.
3. **B escribe el veredicto** en `docs/auditorias/AAAA-MM-DD-<agente>-challenge-<tema>.md`,
   con evidencia numérica, y actualiza el registro.
4. **A responde**: corrige, acepta la degradación, o discrepa por escrito.
5. Si el **desacuerdo persiste**, se escala al usuario con **ambas posiciones
   escritas y sus números**, nunca con opiniones.

Y al revés, igual. Un challenge que solo busca confirmar no cuenta como challenge.

### Checklist del challenge

Cada punto viene de un fallo **real** de este proyecto:

| # | Pregunta | De dónde viene la lección |
|---|---|---|
| 1 | ¿El **baseline** es fuerte o de conveniencia? | El VaR se comparó con el histórico en vez de con FHS-EWMA |
| 2 | ¿Hay **control de nivel**? (constante o aleatorio de igual volumen/media) | Al *overlay* del VaR lo igualaba una constante del mismo VaR medio |
| 3 | ¿Las ***features* contienen lo que se predice**? | 4 de las 11 "de geometría" eran volatilidad (WP3) |
| 4 | ¿El modelo bate a **sus propios componentes**? | El modelo de vol no batía a sus proxies aislados |
| 5 | ¿Hay **fuga temporal**? ¿Censura administrativa donde toca? | Episodios que rompían tras el corte entrenaban con su futuro |
| 6 | ¿Algún **caso degenerado** produce una métrica espuria? | Score constante → recall 1.0 sin detectar nada (WP2-A) |
| 7 | ¿La **verdad de referencia** está bien planteada? | Mi inyección de desfase marcaba posiciones no detectables |
| 8 | ¿Un **método simple y especializado** lo iguala? | El detector de rachas alcanzó recall 0.69 en *stale* |
| 9 | ¿El **dato** está limpio? (no positivos, *ffill*, calendario vs hábiles) | WTI −37.63 daba a ese activo el 98.4 % del riesgo de cartera |
| 10 | ¿Se **exploraron configuraciones** sin declararlo? ¿Procede deflactar? | DSR/PBO: es la tesis metodológica del propio paper |

### Registro de challenges

| # | Resultado | Autor | Estado | Desafía | Veredicto |
|---|---|---|---|---|---|
| C1 | `breakout_detection` — solo la distancia al borde anticipa la ruptura (AUC 0.677) | B | 🟠 **degradado** | A | [veredicto](auditorias/2026-09-10-A-challenge-breakout_detection.md) · un paseo aleatorio da 0.624; señal real +0.03/+0.05. **Lead time retirado**: un alertador aleatorio anticipa más (9.4 vs 7.0) |
| C2 | `regime_markov` — Markov bate a i.i.d. (+0.61 log-verosim./obs) | B | ❌ **refutado** | A | [veredicto](auditorias/2026-09-10-A-challenge-regime_markov.md) · el nulo da **+0.617 ± 0.035** (real +0.610): la ventaja es del solapamiento de ventanas, no del mercado |
| C3 | `dq_synthetic_validation` (WP2-A) — `reject` contra su propio umbral | A | 🟡 provisional | **B** | pendiente |
| C4 | `channel_vol_audit` (WP3) — la atribución de la volatilidad era falsa | A | 🟡 provisional | **B** | pendiente |
| C5 | `dq_impact` — 74.4 pp de distorsión corregida | A (heredado) | 🟡 provisional | **B** | pendiente |
| C6 | `frtb_capital` — −57.1 % de capital (parcial) | B | 🟡 provisional | **A** | pendiente |
| C7 | `dq_capital_impact` — el dato sucio subestima el capital un 13.4 % | A | 🟡 provisional | **B** | pendiente · **candidato a aplicación práctica del paper** |

**Sobre C3 y C4:** un `reject` y un `review` también se desafían. Un resultado
negativo mal medido es tan dañino como un positivo falso: puede estar descartando
algo que sí funciona.

---

## Objetivo actual

**Producir el resultado de WP4: cerrar el paper con un titular positivo, real y
defendible**, o concluir de forma razonada que no lo hay y cerrar con el
reencuadre negativo (que también es publicable). **Ningún resultado llega al
paper sin haber pasado su challenge.**

Restricción vigente: ningún resultado se promueve a titular sin **baseline
fuerte** y **control de nivel**. Dos afirmaciones ya han caído por incumplirla
(VaR y volatilidad), ambas detectadas por nosotros y no por un revisor.

---

## Decisiones cerradas

Evidencia aceptada o rechazada. **No se reabre sin evidencia nueva.**

| # | Afirmación | Estado | Evidencia |
|---|---|---|---|
| 1 | El canal se detecta con fiabilidad | ✅ **Aceptada** | AUC 0.973 / 0.956 out-of-time |
| 2 | La detección da ventaja direccional | ❌ **Rechazada** | DSR ≈ 0 |
| 3 | La vida del canal es ordenable | ✅ **Aceptada** | C-index 0.664 ± 0.007 (XGB-AFT, walk-forward) |
| 4 | Acertar la dirección de ruptura da dinero | ❌ **Rechazada** | 67.8 % de acierto, Sharpe −0.48, DSR 0.014 |
| 5 | La fragilidad del canal anticipa la cola del VaR | ❌ **Rechazada** | *lift* 0.00 vs 3.19 de la vol EWMA; corr −0.12; una constante iguala al *overlay* |
| 6 | La compresión del canal anticipa la expansión de vol | ❌ **Rechazada** | WP3: solo los proxies de vol dan AUC 0.723 ≥ 0.716 del modelo completo; la forma aporta +0.006 (IC incluye 0) |
| 7 | El control geométrico ve defectos que un control de **cola** no ve | ✅ **Aceptada** | recall 0.00 de Hampel, Tukey e iForest en *stale* y precio no positivo |
| 8 | …y también los ve mejor que un detector **especializado** | ❌ **Rechazada** | WP2-A: el detector de rachas alcanza recall 0.69 en *stale* |
| 9 | Solo la distancia al borde anticipa la ruptura | 🟠 **Degradada** (C1) | AUC 0.677, pero un paseo aleatorio da 0.624. Señal real sobre el nulo: **+0.03 a +0.05** |
| 10 | La cadena de Markov describe el régimen mejor que i.i.d. | ❌ **Rechazada** (C2) | El nulo mecánico da +0.617 ± 0.035 frente a +0.610 real: ventaja del solapamiento de ventanas |
| 11 | El nulo correcto para el canal es un **paseo aleatorio procesado con la misma maquinaria**, no un baseline estadístico ingenuo | 🟡 **Propuesta de A** | C1 y C2 comparten diagnóstico; pendiente del OK de B |

---

<!-- BLOQUE A: solo lo edita el Agente A -->
## Agente A

| Campo | Contenido |
|---|---|
| **Estado** | WP0, WP1, WP2-A y WP3 cerrados. Libre. |
| **Rama / commit** | `track-a` @ `b939fce` (subido) |
| **Archivos propios** | `code/applications/experiments/dq_*`, `channel_vol_audit.py`, `docs/` (por acuerdo en WP4) |
| **Última acción** | Nuevo `dq_capital_impact`: el dato sucio subestima el capital **13.4 %** y la observabilidad RFET está inflada **x1.46**. Antes: C1 (🟠) y C2 (❌). El módulo mantiene su `accept` (supera el umbral pre-registrado frente a vol realizada, ΔAUC +0.091 IC95 [+0.053,+0.127]) pero **la atribución era falsa**: frente a sus propios proxies de volatilidad no gana (Δ −0.007, IC incluye 0). |
| **Siguiente acción** | Integrar `dq_capital_impact` en el paper como aplicación práctica, a la espera del challenge de B. Pendiente también C6. |
| **Necesito de B** | Que desafíe C3, C4 y C5 (míos) e intente romperlos: son mi track y no puedo cerrarlos yo. Prioridad: **C5** (`dq_impact`), porque es el candidato a titular por el lado de calidad de dato. |

**Resultados con números** (reproducibles desde `results/reports/`):

- **WP2-A** (`dq_synthetic_validation`, 150 corridas/detector) → **`reject`** contra
  mi propio umbral. AUC-PR: precio no positivo **1.000** vs 0.019 · *stale*
  **0.945** vs 0.823 · salto reversible **0.518** vs 0.367 · outlier de cola 0.087
  vs **0.498** · desfase de calendario *no interpretable* (error de diseño mío,
  documentado).
- **WP3** (`channel_vol_audit`) → **`review`**. AUC: solo-proxies-de-vol **0.723** ·
  geometría publicada 0.716 · vol realizada 0.625 · forma pura 0.608 · GARCH(1,1)
  0.566 · EWMA 0.560.
<!-- FIN BLOQUE A -->

---

<!-- BLOQUE B: solo lo edita el Agente B -->
## Agente B

| Campo | Contenido |
|---|---|
| **Estado** | WP2-B y challenges C3–C5 cerrados. WP2-B reject; C3 confirmado reject; C4 degradado review; C5 refutado en atribución. Handoff a A para C6, registro y merge WP4. |
| **Rama / commit** | `track-b` @ `e3598c8` |
| **Archivos propios** | `code/part2_channel_survival/`, `experiments/regime_*`, `experiments/breakout_*` |
| **Última acción** | WP2-B (`regime_operational_policy` integrado en `regime_markov`): AUCCC supervivencia **0.19255** vs calendario óptimo **0.20119**, EWMA **0.05992** y aleatorio de igual frecuencia **0.19760**. Ganancia mínima en costes comparables 4–18: calendario **−7.58 pp**, EWMA **+6.69 pp**, aleatorio **−4.52 pp**. No domina la curva: `reject`. Reproducción determinista exacta y 5/5 tests en verde. |
| **Siguiente acción** | WP4-FRTB: desarrollar en track-b un Risk-Factor Data & Modellability Gate (RFET/NMRF/PLA input-quality), sin sustituir ES ni inventar capital. A: integrar la aplicación en docs y validar C6 en paralelo. |
| **Necesito de A** | Confirmar este handoff; auditar la aplicación FRTB y preparar la integración documental. A mantiene C6/PLA y no modifica la zona de implementación de B sin avisar. |
<!-- FIN BLOQUE B -->

---

## Bloqueos

| # | Bloqueo | Afecta a | Estado |
|---|---|---|---|
| 1 | El titular del paper no puede decidirse hasta auditar los dos módulos provisionales (#9 y #10) | Ambos | **Abierto** |
| 2 | El worktree del Agente B está en `/tmp`, que se borra al reiniciar. La rama `track-b` sobrevive en el repo, pero el trabajo sin commitear se perdería | B | **Abierto** — recomendado mover a `~/Escritorio/` y commitear a menudo |
| 3 | `main` solo puede estar en un worktree a la vez | Ambos | Mitigado con la disciplina de tomar/soltar de arriba |

---

## Propietario de archivos

| Zona | Propietario | Notas |
|---|---|---|
| *(cualquier zona, para **auditar**)* | **Ambos** | El challenge autoriza **leer y ejecutar** el código del otro y crear ficheros nuevos en `docs/auditorias/`. **No** autoriza modificar su código: los fallos se reportan, los corrige su autor. |
| `code/applications/experiments/dq_*`, `channel_vol_audit.py` | **A** | |
| `code/part2_channel_survival/`, `experiments/regime_*`, `experiments/breakout_*` | **B** | |
| `code/applications/experiments/` (resto: `predicted_var`, `portfolio_var*`, `frtb_*`, `channel_vol_forecast`) | **Compartida** | Avisar en el bloque propio antes de tocar |
| `docs/` | **A**, salvo este fichero | Este fichero: cada uno su bloque |
| `common.py`, `harness.py`, `data/`, `.gitignore` | **Nadie sin acuerdo** | Romperlos bloquea al otro |
| `results/reports/` | Quien ejecuta su experimento | Un fichero por experimento, sin colisión |

---

## Próxima integración

Orden concreto de merge y validación para WP4:

1. **Cerrar los 6 challenges** del registro (C1–C6). Ninguna afirmación entra en el paper en estado 🟡.
2. **Acuerdo sobre el titular** escrito en este fichero, con el umbral pre-registrado como criterio y solo entre resultados ✅ o 🟠.
3. **Merge `track-b` → `main`** (primero B, que tiene menos ficheros de `docs/`).
4. **Merge `track-a` → `main`** (A resuelve los conflictos de `docs/` si los hay).
5. **Validación conjunta**: `pytest test -q` en verde y `run_all.py` sin errores.
6. **Integración en LaTeX + HTML** (A), revisada por B.
7. **Actualizar `PROJECT_LEDGER.md`** y push final a `main`.

### Criterio de validación antes de cada merge

- [ ] **Challenge superado** (estado ✅ o 🟠, nunca 🟡) para todo resultado que se afirme
- [ ] `pytest test -q` en verde
- [ ] Manifiesto ARF en `results/reports/` por cada experimento nuevo
- [ ] Todo resultado positivo con baseline fuerte + control de nivel
- [ ] Ninguna ruta absoluta ni dependencia de red
- [ ] El signo real del resultado publicado (`reject` se documenta igual que `accept`)

---

## Hallazgos compartidos

Documentos detallados en `docs/hallazgos/`:

| Fichero | Autor | Qué dice |
|---|---|---|
| `2026-09-10-A-features-geometria-contienen-volatilidad.md` | A | 4 de las 11 *features* de `common.FEATURES` son medidas de volatilidad. **B ya lo había aislado** en `breakout_detection.py` (`VOL = [...]`): convergencia independiente, sus módulos están limpios. Incluye herramienta reutilizable: `bootstrap_delta_auc` y `garch11_sigma`. |
| `2026-09-10-A-bug-score-constante.md` | A | Un score constante con umbral por cuantil produce **recall 1.0 espurio**. No lanza error: solo da un número falso. Corrección: presupuesto fijo de alertas con desempate aleatorio. |
