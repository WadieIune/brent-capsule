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

| Id | Aplicación | Qué hace | Baseline | Resultado (test 2020-08 → 2026) |
|----|-----------|----------|----------|--------|
| `dq_price_control` | **Data Quality** | Marca precios fuera de la banda ±k·σ del canal, saltos ATR que revierten y *stale prices* | Outliers por cuantil de \|retorno\| | 10.9% de candidatos, Jaccard **0.01** con el baseline → regla **complementaria** |
| `channel_vol_forecast` | **Forecast de vol** | ¿La compresión del canal + `P(T>k)` anticipan expansión de vol? | AUC 0.5 y geometría sin supervivencia | AUC **0.716** con geometría; la supervivencia **no** añade (Δ=−0.002) |
| `predicted_var` | **Predicted VaR** (1 activo) | VaR FHS-EWMA + add-on de cola escalado por `1−P(T>k)` | VaR histórico | Excepciones **1.113%** vs 1.375% (objetivo 1%), Kupiec p=0.66 |
| `portfolio_var` | **Predicted VaR de cartera** | Réplica solo-precio en 6 commodities + agregación por pesos; Kupiec, Christoffersen y semáforo de Basilea | VaR histórico **y** FHS-EWMA sin canal | Cobertura **1.087%** (mejor de tres); el histórico **falla independencia** (p=0.032) |
| `frtb_applications` | **FRTB** | Stress period, liquidity horizon (vida del canal), observabilidad NMRF/RFET | — | Proxy / scaffolding |

### El resultado de cartera, en detalle

`portfolio_var` lleva la tesis central del paper —*con el propio precio de cada
activo basta para caracterizar su régimen*— a una cartera equiponderada de
**BRENT, WTI, GOLD, SILVER, COPPER y NATGAS** (2.024 sesiones de test). Cada
activo aporta su fragilidad `1−P(T>k)` estimada **solo con su serie de precios**;
no hay modelo multivariante de factores.

| Estimador | Excepciones (obj. 1%) | Kupiec p | Christoffersen p | VaR medio |
|---|---|---|---|---|
| Histórico | 1.186% | 0.41 | **0.032 → rechaza** | 3.56% |
| FHS-EWMA (sin canal) | 1.186% | 0.41 | 0.289 | 3.85% |
| **Predicted (con canal)** | **1.087%** | **0.70** | 0.238 | 4.15% |

La atribución se reporta en **dos dimensiones** porque cada componente arregla un
problema distinto —y quedarse solo con la cobertura ocultaría el papel del EWMA:

- el **filtrado EWMA** corrige la *agrupación* de excepciones (el VaR histórico
  las concentra en los episodios de estrés: Christoffersen lo rechaza, p=0.032);
- el **add-on de canal** corrige el *nivel* de cobertura (1.186% → 1.087%).

Coste a ponderar: el VaR medio sube **+7.7%** frente a FHS-EWMA — más consumo de
capital a cambio de una cobertura mejor calibrada. Esa decisión es del risk
director, no del modelo.

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
│   ├── dq_price_control.py
│   ├── channel_vol_forecast.py
│   ├── predicted_var.py
│   ├── portfolio_var.py      # cartera multi-commodity (solo-precio por activo)
│   └── frtb_applications.py
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

Los smoke tests corren los cuatro experimentos sobre serie sintética y
comprueban que el harness produce manifest y métricas sin excepciones. **No**
validan poder predictivo: eso depende del dato real y se reporta tal cual
(incluidos resultados negativos), en coherencia con el ledger del proyecto
(backtest chartista sin *edge*).

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