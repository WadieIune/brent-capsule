# Hallazgo · WP-RD1 Gate 1 v3 — negativo CONFIRMATORIO (4 fallos de B corregidos)

- **Autor:** A · **Fecha:** 2026-10-06 · corrige `auditorias/2026-10-06-A-challenge-WPRD1-gate1-v2.md`.
- **Reproducción:** `code/applications/experiments/wprd1_gate1_v3.py`, `results/reports/wprd1_gate1_v3.json`.

## Correcciones aplicadas (los 4 puntos de B)
1. **Purga ≥10 sesiones en cada frontera**: theta/eventos/episodios solo usan ventanas forward contenidas en su región.
2. **Baseline preseleccionado en VALIDACIÓN** (no en test): sale calendario (val 0,615 > solo-vol 0,462).
3. **FA emparejada**: curva recall-vs-FA + interpolación a FA=15/año a priori; carga realizada reportada.
4. **Nulo con la misma política**: mismo nº de alertas (94) y cooldown de 10; solo aleatoriza el tiempo.

## Resultado (test > 2020-08-20, 31 episodios)
| Política | Recall @FA~15 | FA/año real |
|---|---|---|
| Calendario (cadencia 14, de val) | **0,774** | 14,2 |
| régimen | 0,742 | 12,7 |
| solo-vol | 0,710 | 14,2 |
| supervivencia | 0,613 | 10,4 |
| combinación | 0,581 | 12,5 |
| **Nulo (mismo cooldown/nº)** | media 0,598 · **p95 0,742** | — |

- Contraste primario: combinación 0,581 vs calendario 0,774 → delta **−0,194**, IC95 bloques **[−0,419, −0,065]**.
- La combinación **no supera el nulo** correcto (0,742). La supervivencia **no aporta**.

**Veredicto: Gate 1 NO pasa (confirmatorio).** Para anticipar caídas adversas a 10 sesiones de una
posición larga en Brent, ni la supervivencia ni la combinación baten a la revisión periódica ni a un
nulo bien construido, a igual tasa de falsas alarmas. Coherente con el paseo aleatorio: la geometría
describe el régimen, no anticipa el movimiento adverso.

Sin claims de ahorro/alpha/Sharpe. v1/v2 quedan exploratorios. Pendiente de challenge de B.
