# applications — Aplicaciones en Riesgo de Mercado sobre la geometría del canal

Experimentos que llevan la señal del proyecto (geometría del canal de la 1ª pata
+ supervivencia/ruptura de `part2_channel_survival`) hacia usos de un
departamento de **Riesgo de Mercado (Opciones)**. El código está organizado con
la disciplina de **harness engineering** del
[Agentic Research Framework](https://github.com/WadieIune/Agentic-Research-Framework):

```
Input spec → Pre-flight → Execution → Logging → Validation →
Comparison (baseline) → Decision → Artifact storage
```

Cada ejecución deja un `run_manifest.json` con los campos mínimos del harness
(task/experiment id, timestamp, inputs, config, seed, comando, outputs,
métricas, baseline, errores y decisión), de modo que ninguna afirmación quede
sin evidencia reproducible.

## Aplicaciones

Once experimentos agrupados en cuatro bloques. La columna *decisión* es la del
harness: `accept` cuando el experimento bate a su baseline, `reject` cuando no lo
hace —y se publica igualmente— y `review` cuando la comparación no es concluyente.

**Bloque A · Calidad de dato**

| Id | Qué hace | Baseline | Resultado | Dec. |
|----|----------|----------|-----------|------|
| `dq_price_control` | Marca precios fuera de la banda ±k·σ del canal, saltos ATR reversibles y *stale* | Outliers por cuantil de \|retorno\| | 10.9% de candidatos, Jaccard **0.01** con el baseline → regla complementaria | `reject` |
| `dq_impact` | Mide el control **en unidades de riesgo**, no en recuento de alertas | Control convencional de cola | Depurar corrige **74.4 pp** de distorsión: la concentración en WTI cae de 0.985 a 0.240; los retornos cero, del 31.1% al 0% | `accept` |
| `dq_daily_monitor` | Monitor operativo diario sobre 6 activos | Control convencional | 459 alertas / 28.086 obs (**1.63%** de carga); el convencional emite 30 y es **ciego** a precio congelado y relleno de calendario | `accept` |

**Bloque B · Régimen y ruptura**

| Id | Qué hace | Baseline | Resultado | Dec. |
|----|----------|----------|-----------|------|
| `channel_vol_forecast` | ¿Compresión del canal + `P(T>k)` anticipan expansión de vol? | AUC 0.5 | AUC **0.716**, pero **el mérito es de la volatilidad, no de la forma** (ver auditoría WP3) | `accept`* |
| `channel_vol_audit` | **WP3**: audita el anterior contra vol realizada, EWMA(0.94) y GARCH(1,1) | Baselines de volatilidad | Supera a los baselines de una sola medida, pero **no bate a sus propios proxies de vol** | `review` |
| `breakout_detection` | ¿Se anticipa la ruptura a ≤5 sesiones? | Actuarial (solo tiempo) 0.496; vol 0.482; forma 0.518 | Solo la **distancia al borde** informa: AUC **0.677** (+0.181 sobre el mejor baseline); *lead time* mediano 6 sesiones | `accept` |
| `regime_markov` | Cadena de Markov de 4 estados (asc/desc × borde/centro) | Modelo i.i.d. | Markov bate al i.i.d. (**+0.61** log-verosimilitud por obs.); hazard heterogéneo por edad (p=0.020) → conviene semi-Markov | `accept` |

**Bloque C · VaR y capital**

| Id | Qué hace | Baseline | Resultado | Dec. |
|----|----------|----------|-----------|------|
| `predicted_var` | VaR FHS-EWMA + add-on por `1−P(T>k)` (1 activo) | Histórico, FHS-EWMA y **constante equivalente** | Cobertura 1.019%, pero **no bate a una constante** del mismo nivel medio | `review` |
| `portfolio_var` | Réplica solo-precio en 6 commodities + agregación | Íd. + semáforo de Basilea | **FHS-EWMA gana** (1.005%); el canal no aporta *timing* | `reject` |
| `portfolio_var_alert` | Ablación del *timing*: ¿concentra el canal las excepciones? | Vol EWMA y constante | Canal *lift* **0.00** vs EWMA **3.19** → el canal **no** anticipa la cola | `reject` |
| `frtb_capital` | ES estresado, IMCC e impacto en capital del cambio de modelo | Basilea 2.5 | FRTB IMA **−57.1%** de capital (parcial: omite SES/DRC/RRAO) | `review` |

**Bloque D · FRTB (proxies)**

| Id | Qué hace | Estado |
|----|----------|--------|
| `frtb_applications` | Stress period, *liquidity horizon*, observabilidad NMRF/RFET | Proxy / scaffolding |

### WP3 · Auditoría de `channel_vol_forecast`: la atribución era falsa

> `accept`* significa que el experimento **mantiene** su decisión —supera el
> umbral pre-registrado— pero **la causa que se le atribuía es incorrecta**.

`channel_vol_forecast` se publicó con AUC 0.716 prediciendo la expansión de la
volatilidad realizada, comparado únicamente contra la tasa base (AUC 0.5). Nunca
se contrastó con un modelo de volatilidad, que es el mismo patrón que invalidó el
resultado del VaR.

Había un motivo concreto para sospechar: de las once *features* que el
experimento llama "geometría", **cuatro son medidas de volatilidad**:

| Feature | Qué es realmente |
|---|---|
| `vol20` | desviación de los últimos 20 retornos — volatilidad realizada |
| `atr_norm` | ATR / precio — rango medio |
| `resid_norm` | σ de los residuos / nivel — dispersión *detrended* |
| `band_width` | 2·m·σ_resid / nivel — la anterior, reescalada |

Y el objetivo —¿superará la vol futura a la actual?— es en gran parte una
pregunta sobre **reversión a la media de la volatilidad**. Resultado de la
auditoría (mismo objetivo, split, clasificador y estandarización para todos):

| Modelo | AUC | Qué contiene |
|---|---|---|
| **`vol_proxies_solo`** | **0.723** | **solo los 4 proxies de vol, cero forma** |
| `geometria_publicada` | 0.716 | las 11 features publicadas |
| `vol_mejor_mas_forma` | 0.631 | mejor vol + forma pura |
| `rv_lagged` | 0.625 | vol realizada (nivel y posición relativa) |
| `forma_pura` | 0.608 | geometría **sin** los 4 proxies de vol |
| `garch_11` | 0.566 | GARCH(1,1), parámetros solo de train |
| `ewma_094` | 0.560 | EWMA λ=0.94 |

Tres contrastes *bootstrap* (B=3000) cierran la atribución:

- **Criterio pre-registrado** — publicado vs `rv_lagged`: ΔAUC **+0.091**,
  IC95 [+0.053, +0.127] → **supera**, así que el `accept` se mantiene.
- **Atribución** — publicado vs *solo sus proxies de vol*: ΔAUC **−0.007**,
  IC95 [−0.021, +0.006] → **la forma no aporta nada**; el modelo sin ninguna
  información de forma es, si acaso, ligeramente mejor.
- **Incremental** — añadir forma a la mejor vol: ΔAUC **+0.006**,
  IC95 [−0.024, +0.035] → indistinguible de cero.

**Conclusión.** El experimento supera el umbral, pero **no porque la geometría
del canal anticipe la volatilidad**: lo hace porque sus *features* contienen una
**representación multi-medida de la volatilidad** (realizada + ATR + dispersión
*detrended*) que resulta mejor predictor que EWMA o GARCH(1,1) de una sola
medida. Eso sigue siendo un hallazgo útil —y algo llamativo, porque bate a
GARCH— pero pertenece a la **medición de volatilidad**, no al chartismo. La
afirmación "la compresión del canal anticipa la expansión de vol" queda refutada.

### El resultado de VaR, corregido

> **Este bloque sustituye a la versión anterior.** Una revisión posterior encontró
> tres defectos que invalidaban la conclusión publicada; se documentan aquí porque
> el error y su corrección forman parte del resultado.

**Los tres defectos**

1. **Precio negativo del WTI.** El 2020-04-20 el WTI liquidó a −37.63 USD.
   `log_returns` acotaba a `1e-9`, generando dos log-retornos artificiales de
   |r|≈23 (±2300%) que dominaban la covarianza: WTI aparecía con el **98.4%** del
   riesgo de cartera en lugar del 24%, e inflaba la vol EWMA durante meses.
2. **Calendario en vez de días hábiles.** `dataset_wide_with_target.csv` es de
   calendario con *forward-fill*: 365 obs/año y **~32% de retornos exactamente
   cero**. Eso sesga el cuantil empírico, contamina el test de independencia (un
   día de retorno cero nunca puede ser excepción) y desescala el semáforo de
   Basilea, que cuenta 250 sesiones de negociación. Corregido: 4.680 sesiones a
   251.6 obs/año.
3. **Faltaba el control de nivel.** Sin comparar contra una **constante con el
   mismo VaR medio** no se puede distinguir si el overlay mejora por *timing*
   (reacciona al régimen) o simplemente por *nivel* (es más conservador).

**El resultado tras corregir** (cartera, 1.393 sesiones de test):

| Estimador | Cobertura (obj. 1%) | Kupiec p | Christoffersen p | Capital vs histórico |
|---|---|---|---|---|
| Histórico | 1.292% | — | **0.0011 → rechaza** | — |
| **FHS-EWMA (sin canal)** | **1.005%** | **0.985** | 0.1284 | **−1.8%** |
| Predicted (con canal) | 0.933% | — | 0.1080 | +5.3% |
| Constante ×1.073 (control) | ≈ predicted | — | — | ≈ predicted |

**El canal no aporta *timing* de cola.** La ablación lo demuestra por tres vías
independientes:

- **Lift**: en los días de mayor fragilidad de canal se concentran *cero*
  excepciones (lift@q80 = **0.00** en cartera, 0.997 en activo único), mientras la
  vol EWMA da lift **3.19**.
- **Correlación**: corr(fragilidad, vol) = **−0.12** — el canal se comprime cuando
  hay calma, y las excepciones ocurren en volatilidad alta. La señal apunta en
  sentido contrario al que necesita un VaR.
- **Ablación**: una **constante ×1.071** con el mismo VaR medio iguala al overlay,
  luego su mejora aparente era efecto de **nivel**, no de régimen.

**Quien sí cumple el objetivo es FHS-EWMA**: cobertura 1.005% (Kupiec p=0.985),
corrige el agrupamiento de excepciones del histórico (p de 0.0011 a 0.1284) y
**ahorra un 1.8% de capital**. La capa de alertas discretas sobre VaR histórico
tampoco lo consigue (+0.2%): el fallo del histórico es de *agrupamiento*, y eso se
corrige con escalado **continuo** de volatilidad, no con saltos discretos.

*Caveat* que se reporta igualmente: el test **DQ de Engle–Manganelli** rechaza a
**todos** los estimadores, incluido el mejor. Ninguno captura por completo la
dinámica de la cola.

Este resultado es coherente con las otras dos patas: la geometría del canal
**describe el régimen**, pero no anticipa ni la dirección (1ª pata), ni el
beneficio (2ª), ni la cola (3ª). Donde sí aporta valor medible es en **calidad de
dato** (`dq_impact`: 74.4 pp de distorsión corregida) y como **descriptor
interpretable** de régimen (`regime_markov`, `breakout_detection`).

Otras líneas (early-warning de límites, escenarios de stress *data-driven*,
señal para libro de opciones) se apoyan en las mismas salidas y quedan como
ampliación.

## Estructura

```
applications/
├── README.md
├── requirements.txt
├── config.yaml            # parámetros de referencia (mismos que la CLI)
├── harness.py             # harness ARF: contexto, resultado y persistencia de manifest
├── common.py              # reutiliza la geometría de part2_channel_survival (sin duplicarla)
├── run_all.py             # orquestador de todos los experimentos
├── experiments/
│   ├── dq_price_control.py       # A · control geométrico de precio
│   ├── dq_impact.py              # A · impacto del control en unidades de riesgo
│   ├── dq_daily_monitor.py       # A · monitor operativo diario
│   ├── channel_vol_forecast.py   # B · compresión -> expansión de vol
│   ├── breakout_detection.py     # B · anticipación de la ruptura
│   ├── regime_markov.py          # B · cadena de Markov de régimen
│   ├── predicted_var.py          # C · VaR de un activo
│   ├── portfolio_var.py          # C · VaR de cartera multi-commodity
│   ├── portfolio_var_alert.py    # C · ablación del timing (¿aporta el canal?)
│   ├── frtb_capital.py           # C · ES estresado, IMCC y cambio de modelo
│   └── frtb_applications.py      # D · proxies FRTB
└── test/
    └── test_smoke.py
```

`common.py` **no reimplementa** el canal: añade `part2_channel_survival/` al path
y reutiliza `channel_survival.py` (recta OLS, banda ±k·σ, ATR, episodios). Si el
etiquetador del proyecto cambia, estas aplicaciones lo heredan sin desincronizarse.

## Uso

```bash
cd code/applications
pip install -r requirements.txt

# con la serie del proyecto (data/brent_fred_daily.csv) si existe:
python run_all.py --cutoff 2020-08-20

# sin la serie propietaria (verificación con datos sintéticos):
python run_all.py --synthetic

# un solo experimento:
python run_all.py --only predicted_var --synthetic
```

Salidas en `outputs/` (git-ignoradas): un `run_manifest.json` por experimento,
CSVs de detalle (flags de DQ, episodios FRTB) y `summary.json` consolidado.

## Verificación

```bash
python -m pytest test -q           # o: python test/test_smoke.py
```

Los smoke tests iteran sobre `ALL_EXPERIMENTS`, de modo que cubren los **once**
experimentos sobre serie sintética y comprueban que el harness produce manifiesto
y métricas sin excepciones. **No** validan poder predictivo: eso depende del dato
real y se reporta tal cual —incluidos los resultados negativos: **3 de los 11 son
`reject`**— en coherencia con el ledger del proyecto (backtest chartista sin
*edge*).

## Notas y límites

- La serie sintética de `common.synthetic_brent` es **solo para ejecutar/testear**;
  no es dato de mercado y no debe usarse para conclusiones.
- `frtb_applications` produce **proxies** (stress period, LH, RFET), no cálculos
  regulatorios oficiales; requieren integración con el motor FRTB corporativo.
- Los splits son **temporales y sin fuga** (`common.temporal_mask`); las features
  de DQ usan residuo proyectado hacia delante (el punto evaluado no entra en el ajuste).
- La **supervivencia del canal** (`common.SurvivalFeaturizer`) se ajusta **solo con
  episodios del periodo de train** y se usa como feature `P(T>k)` en el forecast y
  como propensión de ruptura `1−P(T>k)` en el add-on del VaR. Usa **Cox (lifelines)**
  si está instalado; si no, un **Kaplan-Meier por buckets** (solo numpy). Instala
  `lifelines` para el modo Cox: `pip install lifelines`.