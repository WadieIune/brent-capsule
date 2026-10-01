# El backtest — el filtro que descartó las hipótesis de fantasía

- **Autor:** Agente A · **Fecha:** 2026-09-11 · a petición del MASTER
- **Por qué existe este documento:** el activo metodológico central del proyecto
  no es ningún modelo, es el **banco de pruebas**. Es lo que convirtió «parece que
  funciona» en «lo probamos y no pasa», y lo que da credibilidad a lo poco que sí
  sobrevive. Esta es su especificación y su hoja de servicios.

## El problema que ataca

Sobre una serie de precios —que es casi un paseo aleatorio— es fácil producir
resultados que *parecen* señal y son artefacto: solapamiento de ventanas,
selección sobre el test, p-hacking entre variantes, un estadístico que sube
sobre 0,5 por pura mecánica. El backtest está diseñado para **matar justo esos
artefactos**, no para lucirlos.

## El *gauntlet*: qué atraviesa cada hipótesis

| Prueba | Qué artefacto mata | Dónde vive |
|---|---|---|
| **Walk-forward purgado + embargo** (López de Prado, cap. 7) | fuga por solapamiento de ventanas y correlación serial entre train y test | `code/brent_pattern_system/cv_purged.py` (`purge_indices`, `apply_embargo`, `walk_forward_folds`) |
| **Corte out-of-time** (2020-08-20) | sobreajuste al pasado; comprueba generalización a un tramo nunca visto | configs y `--cutoff` en los experimentos |
| **DSR — Deflated Sharpe Ratio** | el Sharpe que sube solo por haber probado muchas variantes | `metrics.py::deflated_sharpe_ratio`, `part2_channel_survival/metrics_min.py` |
| **PBO / CSCV** | probabilidad de que el «mejor» modelo lo sea por azar combinatorio | `metrics_min.py` (PBO), `backtest.py` |
| **Nulo de paseo aleatorio / block-bootstrap** (decisión #11) | la señal que un paseo aleatorio procesado con la MISMA maquinaria reproduce | `common.py` (`synthetic_brent`, block bootstrap), scripts de challenge |
| **Selección solo en train/validación** | elegir el modelo mirando el test | disciplina impuesta en cada experimento |
| **Block bootstrap (no i.i.d.)** | IC demasiado estrechos con objetivos solapados | arneses de validación |
| **Tests de VaR**: Kupiec POF, Christoffersen, Engle-Manganelli DQ | cobertura y, sobre todo, **independencia** de excepciones | `experiments/predicted_var.py` |
| **Semáforo / multiplicador de Basilea** | traduce el backtesting a capital real (el clustering consume capital) | `experiments/portfolio_var.py` |
| **Censura administrativa** (supervivencia) | sesgo por episodios aún vivos al corte | `part2_channel_survival/channel_survival.py` |
| **AUC-PR + presupuesto fijo de alertas (top-k)** | la ilusión de acierto con una clase positiva rara | arneses de clasificación/alerta |

## Los criterios de muerte (fijados *antes*, no después)

- Una señal de canal debe **batir al nulo de paseo aleatorio**, no al 0,5 ingenuo.
- Una estrategia debe dar **DSR > 0 con IC por bloques que excluya el cero**.
- Una capa de información debe mejorar **de forma incremental** sobre el baseline
  fuerte (EWMA/HAR), no sobre un hombre de paja.
- Un reductor de VaR debe mantener **cobertura Kupiec** y no empeorar la
  **independencia** de Christoffersen.
- Si no se cumple, **se publica como negativo**. No se reabre sin evidencia nueva.

## El principio que ahorró tiempo: gate barato antes que caro

Antes de pagar un reentreno de la CNN, la hipótesis se prueba con features
tabulares baratas y su nulo. Si no supera ese gate, no se escala al modelo caro.
Así murió H1 (clustering de excepciones) sin gastar el reentreno —ver
`hallazgos/2026-09-11-A-H1-H3-gate-barato-capital.md`.

## Hoja de servicios — lo que el backtest MATÓ

| Hipótesis de fantasía | Lo que parecía | Lo que dijo el backtest |
|---|---|---|
| La detección del canal da ventaja direccional (#2) | — | DSR ≈ 0 |
| Acertar la ruptura da dinero (#4) | 67,8 % de acierto | Sharpe **−0,48**, DSR 0,014 |
| La fragilidad del canal anticipa la cola del VaR (#5) | — | *lift* **0,00** vs 3,19 de la vol EWMA; una constante iguala al overlay |
| La compresión anticipa la expansión de vol (#6) | AUC 0,723 | la forma aporta **+0,006**, IC incluye 0 |
| El control geométrico bate a un detector especializado (#8) | — | el detector de rachas logra recall 0,69 en *stale* |
| Solo la distancia al borde anticipa la ruptura (#9, C1) | AUC 0,677 | el paseo aleatorio da **0,624**; señal real +0,03/+0,05 |
| La cadena de Markov describe el régimen mejor que i.i.d. (#10, C2) | +0,610 | el nulo da **+0,617**: era solapamiento de ventanas |
| La CNN sobre volatilidad bate a la persistencia | — | la persistencia gana (corr 0,45 vs ≈0) |
| La dirección es predecible con más datos (H5/10/20) | — | por debajo del *base rate* en los tres horizontes |
| La geometría anticipa el clustering de excepciones (H1) | overlay baja capital | **−0,0032 AUC-PR**, dentro del nulo; el capital lo movía la vol |

## Y lo que SOBREVIVIÓ al mismo filtro

Esto es lo que da valor al negativo: el banco no está sesgado a rechazar, acepta
señal real cuando la hay.

| Afirmación | Métrica | 
|---|---|
| El canal se detecta con fiabilidad (#1) | AUC **0,97 / 0,956** out-of-time |
| La vida del canal es ordenable (#3) | C-index **0,664 ± 0,007** (XGB-AFT, walk-forward) |
| El control geométrico ve defectos que un control de cola no ve (#7) | recall 0,00 de Hampel/Tukey/iForest en *stale* y precio no positivo |
| El dato sucio subestima el capital (#13) | **13,4 %** de infradotación |

## La frase para el comité

«No presentamos lo que funcionó; presentamos lo que **sobrevivió a un banco de
pruebas diseñado para matarlo**. Las mismas reglas que rechazaron nueve hipótesis
aceptaron cuatro. Por eso creemos las cuatro.»
