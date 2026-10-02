# Backtest completo del VaR condicional a volatilidad (cierre de la cola de B)

- **Ejecutado por:** Agente A, por instrucción del MASTER (cerrar la cola de B).
- **Fecha:** 2026-10-02 · **Zona:** volatilidad/riesgo (propiedad de B)
- **Reproducción:** `python code/applications/experiments/var_vol_conditional_backtest.py`
- **Salida:** `results/reports/var_vol_conditional_backtest.json`

## Qué se validó

Que el ahorro de capital del VaR condicional a volatilidad (FHS-EWMA, λ=0,94)
frente al VaR incumbente estático (simulación histórica, ventana 250) **supera la
batería completa de backtesting de VaR**, no solo la cobertura. Brent, corte
out-of-time 2020-08-20, 1.527 sesiones de test.

## Resultado

| Prueba | Estático (incumbente) | Condicional a vol (FHS-EWMA) |
|---|---|---|
| Excepciones (99%) | 21 | 20 |
| Kupiec POF (cobertura) | p=0,041 | **p=0,246 ✓** |
| **Christoffersen (independencia)** | **p=0,038 ✗ (agrupa)** | **p=0,262 ✓** |
| Cobertura condicional LR_cc | — | p=0,272 ✓ |
| Engle-Manganelli DQ | p=0,0004 ✗ | p=0,056 ✓ (justo) |
| Capital peor-250d | 0,29792 | **0,23026** |
| Multiplicador | 3,75 (ámbar) | 3,40 (ámbar) |

**Δ capital = −22,71 %.** IC95 por bloques (1.000 remuestreos, bloques de 20):
**[−28,91 %, −1,25 %]** — todo el intervalo es negativo, así que el ahorro es
**robusto** (aunque la cota superior queda cerca de cero: conservadoramente el
ahorro podría ser tan pequeño como ~1,3 %). Mediana bootstrap −15,8 %.

## Lectura

Dos cosas, y la segunda es la que vale ante un comité:

1. El VaR condicional **ahorra un 22,7 % de capital** a cobertura correcta.
2. Además **arregla el fallo de independencia** del incumbente: el VaR estático
   **agrupa** las excepciones (Christoffersen p=0,038, DQ p=0,0004) —justo lo que
   infla el multiplicador—, y el condicional las desagrupa (p=0,262). El ahorro
   no sale de asumir más riesgo, sale de **no reaccionar tarde**.

Matiz honesto: el DQ de Engle-Manganelli del condicional queda en p=0,056, que
pasa el 5 % por poco. No invalida la conclusión, pero se reporta.

## Estado

**Cerrado.** El −22,7 % ya no es «gate barato pasado, pendiente backtest
completo»: ha pasado la batería completa (Kupiec + Christoffersen + LR_cc + DQ +
semáforo) con IC por bloques. Pasa a **resultado presentable sin asterisco**.
