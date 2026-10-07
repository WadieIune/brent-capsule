# Hallazgo · Cross-asset a múltiples objetivos — robusto en stale, dependiente del par en decoplamiento

- **Autor:** A · **Fecha:** 2026-10-07 · `code/applications/experiments/dq_cross_asset_multi.py`.
- 10 objetivos del panel, FP=5 %, ground truth por inyección, REPS=30.

## Mediana sobre 10 objetivos
| Familia | 3σ | cross-asset |
|---|---|---|
| stale | 0,00 | **1,00** |
| decoplamiento | 0,04 | 0,57 |
| salto | **1,00** | 0,53 |

## Decoplamiento, recall cross-asset POR objetivo
| alto (>0,8) | medio | bajo (<0,2) |
|---|---|---|
| DAX 0,99 · EUROSTOXX50 0,99 · SILVER 0,90 · GOLD 0,87 | WTI 0,62 · BRENT 0,52 · SP500 0,34 · COPPER 0,31 | **NATGAS 0,07 · EURUSD 0,15** |

## Lectura honesta (refina el framework)
1. **stale: cross-asset es robusto (1,0 en los 10 objetivos)** donde 3σ es ciego.
   Control universal.
2. **decoplamiento: el cross-asset solo funciona si el objetivo tiene pares
   fuertemente correlacionados.** NATGAS y EURUSD quedan bajos porque un panel de
   commodities no es su grupo natural: EURUSD necesita pares FX, NATGAS su propio
   complejo energético/estacional. **No es un control universal; depende de los pares.**
3. **salto: usar 3σ** (universal 1,0).
4. Matiz de protocolo: el número de decoplamiento de BRENT aquí (0,52) es menor que
   en el experimento temporal riguroso (0,98) porque este es un barrido de amplitud
   con estandarización global y split aleatorio; el estimador riguroso por objetivo
   usa el protocolo temporal (train-only). La lectura cualitativa (dependencia del
   par) se mantiene.

## Consecuencia para el framework de control
La capa DQ asigna a cada defecto el control que lo caza mejor, y para el
decoplamiento **selecciona los pares correctos por objetivo** (no un panel genérico):
- rachas/repetidos → **TRIM** (universal) / cross-asset stale (universal);
- decoplamiento → **cross-asset con pares del grupo natural** del objetivo;
- saltos → **3σ**.

## Dónde encajan canales y supervivencia (honesto)
- **Detección de canales (shape, AUC 0,97):** su valor en DQ es como **control de
  forma**, natural para **curvas de tipos (ZC/OIS-RFR)** —detectar formas imposibles,
  kinks, no-monotonía—. Extensión separada: antes hay que resolver tenor/instrumento/
  calendario/convenciones (caveat de B); no tratar DGS2/5/10/30 como nodos sin eso.
- **Supervivencia del canal (C-index 0,664):** **marginal para DQ.** Una serie
  congelada tiene canal "infinito", pero eso ya lo caza el TRIM de rachas; la
  supervivencia no añade un control de dato nuevo. Se documenta como herramienta de
  riesgo, no como control de DQ.
