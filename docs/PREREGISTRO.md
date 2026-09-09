# Pre-registro de la competición — cierre del paper

> **Contrato entre los dos agentes.** Escrito **antes** de ejecutar ningún
> experimento de los tracks. Ver el protocolo completo en
> [`PLAN_COMPETITIVO.md`](PLAN_COMPETITIVO.md).
>
> **Fecha de congelación:** commit del que cuelga este documento.
> **Estado del repo al congelar:** `main` limpio; 11 experimentos (5 `accept`,
> 3 `review`, 3 `reject`); 11/11 manifiestos en `results/reports/`.

## Por qué esto existe

El propio paper demuestra, con DSR y PBO, que elegir la mejor configuración
*después* de ver los resultados produce hallazgos que no sobreviven al escrutinio.
Si dos agentes compiten y luego escogemos al ganador por sus números, cometemos
exactamente ese error a nivel de proyecto. Fijar hipótesis, métrica, baseline y
umbral **antes** de ejecutar es lo que hace que la competición refuerce el trabajo
en lugar de invalidarlo.

**Regla de oro:** cualquier desviación respecto de lo escrito aquí se documenta
como *desviación*, con su motivo, en el manifiesto del experimento y en la sección
§4 de este documento. No se reescribe el pre-registro.

## Condiciones comunes a ambos tracks

| Parámetro | Valor congelado |
|---|---|
| Serie de precios | `data/brent_fred_daily.csv` (1 activo) · `data/dataset_wide_with_target.csv` (panel de 6) |
| Frecuencia | **Días hábiles**, sin relleno de calendario |
| Corte temporal | `2020-08-20` (train ≤ corte < test) |
| Semilla | 42 (`PYTHONHASHSEED=0`) |
| Harness | `RunContext` / manifiesto ARF obligatorio |
| Bootstrap | B = 3000, IC percentil 95 % |
| Nivel de significación | 5 % |

**Prohibido** durante la ejecución del track: tocar `data/`, `.gitignore`,
`harness.py` y `common.py`.

---

## Track A — Calidad de dato basada en geometría del canal

**Agente A.** Zona: `code/applications/experiments/dq_*`. Rama: `track-a`.

- **Hipótesis (falsable).** El control geométrico de canal detecta defectos de
  dato de mercado que un control convencional de cola **no puede detectar por
  construcción** (familias *stale*, relleno de calendario y precio congelado), y
  no es peor que él en las familias donde ambos son aplicables (saltos y
  atípicos). El motivo es estructural: un retorno exactamente cero nunca es un
  valor atípico de la distribución de retornos.

- **Métrica primaria (una sola).** **AUC-PR** (precisión-recall) por familia de
  defecto, sobre inyección sintética con verdad conocida. Se usa PR y no ROC
  porque la clase positiva es rara y el ROC resulta optimista con desbalance.

- **Métricas secundarias.** Precisión/recall al umbral operativo; **impacto en
  unidades de riesgo** (distorsión de la contribución al riesgo antes/después de
  depurar); carga operativa (% de observaciones marcadas).

- **Baseline fuerte** (no basta el cuantil de |retorno|, que es el baseline débil
  ya usado): **Hampel / MAD móvil**, **vallas de Tukey**, **isolation forest** y
  **detector de rachas constantes**. El mejor de los cuatro por familia es el
  rival a batir.

- **Control de nivel / ablación.** Un detector que marque **al azar** la misma
  fracción de observaciones que el control geométrico. Descarta que el mérito
  venga del volumen de alertas y no de su acierto.

- **Datos y diseño.** Inyección sobre serie limpia (días hábiles, sin *ffill*), a
  tasas de corrupción de **0.5 %, 1 % y 2 %**, con 10 semillas por combinación.
  Familias: `stale/relleno`, `salto_reversible`, `outlier_de_cola`,
  `precio_no_positivo`, `desfase_calendario`.

- **Umbral de éxito (numérico, previo).** Se declara `accept` si **ambas**:
  1. En las familias *ciegas* (`stale/relleno`, `precio_congelado`): recall del
     mejor baseline **< 0.10** y recall del control geométrico **≥ 0.70**.
  2. En las familias comunes (`salto_reversible`, `outlier_de_cola`): ΔAUC-PR del
     control geométrico frente al mejor baseline con **IC 95 % que no incluya
     valores < −0.05** (es decir, no ser materialmente peor).

  Si (1) se cumple y (2) no, el veredicto es `review` con el alcance acotado a las
  familias ciegas.

- **Regla de parada.** **Una** configuración del control geométrico: los
  parámetros ya publicados (`LOOKBACK=32`, `BAND_MULT=2.0`, `k=5.0σ` para banda
  esperada, `ATR_WIN=14`). No se optimizan hiperparámetros. Si se explorasen más,
  se reportaría el número de configuraciones y se deflactaría el resultado.

- **Qué observaríamos si la hipótesis es FALSA.** Que el baseline convencional
  alcanza recall comparable en las familias *stale*/congelado —lo que refutaría el
  argumento estructural—, o que el control geométrico es materialmente peor en las
  familias comunes, o que el detector aleatorio del mismo volumen iguala su
  AUC-PR. Cualquiera de las tres cierra el track como `reject`.

---

## Track B — Régimen del canal como política operativa de riesgo

**Agente B.** Zona: `code/part2_channel_survival/`, `experiments/regime_*`,
`experiments/breakout_*`. Rama: `track-b`.

- **Hipótesis (falsable).** Una política de revisión de parámetros de riesgo
  **guiada por la supervivencia del canal** (revisar cuando la probabilidad de
  ruptura supera un umbral) domina a una política de **calendario fijo** en la
  curva coste-cobertura: detecta la misma proporción de cambios de régimen con
  menos revisiones, o más con el mismo número.

- **Métrica primaria (una sola).** **Área bajo la curva coste-cobertura**, donde
  el coste es el número de revisiones por año y la cobertura la proporción de
  cambios de régimen detectados dentro de una tolerancia de 5 sesiones.

- **Métricas secundarias.** *Lead time* mediano de aviso; C-index del modelo de
  supervivencia sobre el tramo de test; calibración de la probabilidad de ruptura.

- **Baseline fuerte.** Política de calendario **óptimamente calibrada** —se
  barre la periodicidad fija y se toma la mejor— y política guiada por
  **volatilidad** (revisar cuando la vol EWMA supera su cuantil *q*). Un
  calendario ingenuo no es baseline aceptable.

- **Control de nivel / ablación.** Política que revisa en fechas **aleatorias**
  con la misma frecuencia media que la política guiada. Descarta que el mérito
  venga de revisar más a menudo.

- **Datos y diseño.** Episodios de canal de la 2ª pata, días hábiles, corte
  `2020-08-20`, con **censura administrativa** en el corte (ya implementada en
  `channel_survival.administrative_censoring`).

- **Umbral de éxito (numérico, previo).** Se declara `accept` si la política
  guiada domina a **ambos** baselines en el tramo operativo de 4–24 revisiones al
  año, con una ganancia de cobertura **≥ 5 puntos porcentuales** a igual coste y
  con IC 95 % *bootstrap* que excluye el cero.

- **Regla de parada.** Un único umbral de probabilidad, elegido **en train** por
  validación, no en test. Máximo **3** configuraciones exploradas; si se superan,
  se reporta el recuento y se deflacta.

- **Qué observaríamos si la hipótesis es FALSA.** Que el calendario óptimamente
  calibrado iguala o supera a la política guiada, o que la política por
  volatilidad la domina —lo que indicaría que el valor está en la vol y no en la
  geometría, exactamente como ocurrió en la 3ª pata con el VaR—, o que la política
  aleatoria de igual frecuencia la iguala.

---

## WP3 — Auditoría de baseline fuerte (fuera de competición)

**Dueño:** el agente que termine antes su track.

`channel_vol_forecast` figura hoy como `accept` con AUC 0.716, pero medido
**contra 0.5 y contra "geometría sin supervivencia"**, no contra un baseline de
volatilidad. Es el mismo patrón que invalidó el resultado del VaR.

- **Baseline fuerte obligatorio:** vol realizada rezagada, **EWMA (λ=0.94)** y
  **GARCH(1,1)**.
- **Umbral:** mantiene `accept` solo si su AUC supera al mejor de los tres con IC
  95 % *bootstrap* que excluye el cero. En caso contrario se degrada a `review` o
  `reject`, y se corrige en README, LaTeX y HTML.
- **Compromiso previo:** el resultado se publica sea cual sea. Degradar un
  `accept` propio es un resultado válido del proyecto, no un fracaso.

---

## §4 · Registro de desviaciones

*(Vacío al congelar. Toda desviación respecto de lo anterior se anota aquí con
fecha, motivo y efecto sobre la interpretación. No se edita el texto original.)*

| Fecha | Track | Desviación | Motivo | Efecto |
|---|---|---|---|---|
| 2026-09-10 | B | Colisión de worktree: se observó accidentalmente solo el veredicto final de Track A antes del run real. | Ambos agentes compartían worktree y el cambio de rama de B hizo que el commit de A aterrizara temporalmente en `track-b`. | El diseño y código de B estaban fijados antes; no se vieron métricas de A ni se cambiaron umbrales, modelos o interpretación. Los worktrees quedaron separados antes de ejecutar B. |

---

## §5 · Adjudicación

Al cerrar ambos tracks:

1. Cada agente publica su resultado **contra su propio umbral pre-registrado**,
   sin ver el del otro hasta ese momento.
2. Titula el paper el track que cumpla su umbral. Si **ambos** lo cumplen, titula
   Track A por tener el argumento estructural, y Track B pasa a sección de apoyo.
   Si **ninguno** lo cumple, el paper se cierra con el reencuadre negativo
   —igualmente publicable— y ambos tracks se reportan como `reject`.
3. Los dos tracks se documentan en el paper con el mismo nivel de detalle,
   coherentemente con los 3 `reject` ya publicados.
