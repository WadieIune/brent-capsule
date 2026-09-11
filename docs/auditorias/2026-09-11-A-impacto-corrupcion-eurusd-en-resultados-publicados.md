# Auditoría · alcance de la corrupción de `EURUSD` sobre los resultados ya publicados

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-09-11
- **Motivo:** instrucción del MASTER tras detectarse 10 prints imposibles en `EURUSD`
- **Origen del defecto:** [`hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md`](../hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md)
- **Reproducible con:** `python data/verify_panel.py` y los contrastes de este documento

## Veredicto

**Ningún resultado publicado cambia de signo ni de conclusión.** El defecto está
confinado a 2008 y **ningún dato corrupto entra en el entrenamiento ni en la
evaluación de la CNN**, que viven íntegramente en 2019-2026. Queda **una vía de
contagio real pero menor**: la escala de estandarización de 6 de las 180
features.

No es un «no afecta». Es un «afecta por un canal acotado y cuantificado».

## 1. Los días corruptos

Diez, todos en 2008, en pares consecutivos (el print malo y su reversión):
2008-01-08/09, 02-08/11, 09-08/09, 10-08/09, 12-08/09.

En el espacio estandarizado son los **diez mayores atípicos de su columna**:

| Fecha | z de `EURUSD_logret1` |
|---|---|
| 2008-12-08 | **+21,10** |
| 2008-12-09 | **−18,91** |
| 2008-10-08 | +12,70 |
| 2008-10-09 | −12,56 |
| 2008-02-08 | +9,62 |

El máximo absoluto de esa columna en toda la muestra es **21,1 sigma**, y es uno
de ellos.

## 2. Quién consume `EURUSD` en el repositorio

| Consumidor | ¿Usa `EURUSD`? | ¿Afectado? |
|---|---|---|
| `portfolio_var.py` | **No** — `DEFAULT_ASSETS` = BRENT, WTI, GOLD, SILVER, COPPER, NATGAS | No |
| `dq_capital_impact.py` | No — trabaja sobre el Brent | No |
| `part2_channel_survival` | No — Brent | No |
| `risk_director_daily.py` | Sí, como variable exógena descriptiva | No: informa niveles recientes (2026) |
| `series_bundle.py` → **CNN** | **Sí**: 6 features de 180 | **Sí, parcialmente — ver §4** |

Las seis: `EURUSD`, `EURUSD_logret1`, `EURUSD_vol20`, `EURUSD_rangepct`,
`EURUSD_ma520` y `BRENT_EURUSD_RATIO`.

## 3. El dato corrupto NO entra en train ni en test

Las fechas de los tensores no estaban documentadas, así que se recuperaron
casando cada ventana de `X_train`/`X_test` contra la matriz z-score. La
coincidencia es **exacta** (distancia 0,0):

| Partición | Rango |
|---|---|
| `X_train` (986) | 2019-12-02 → 2024-11-20 |
| `X_test` (247) | 2024-11-21 → 2026-03-04 |

Lo confirma de forma independiente el propio artefacto del repositorio,
`results/metadata/bundle_validation.json`: `reconstructed_first_date`
2019-12-02, `reconstructed_last_date` 2026-03-04, 1.233 ventanas,
`train_matches_reconstruction: true`.

**Los 10 días corruptos son de 2008. Cero de ellos cae dentro.** Lo mismo vale
para los 3 *folds* de walk-forward y las 922 ventanas fuera de muestra de
`torch_walkforward_summary.json`, que son un subconjunto del mismo rango.

En consecuencia, **no cambian**: los Sharpe por fold (0,286 / −1,005 / 0,235),
el DSR, el PBO, ni la clasificación de los 8 patrones.

## 4. La vía que sí contagia: la escala de estandarización

El fichero z-score es exactamente `(raw − feature_means) / feature_stds`
(verificado, error máximo 3·10⁻¹⁵). Y la desviación típica de las columnas
estandarizadas es ≈ 0,94, lo que indica que **la ventana de estandarización
abarca toda la muestra, 2008 incluido**.

Por tanto los 10 atípicos inflan la escala, y esa escala se aplica también a las
filas de 2019-2026. Efecto medido:

| Feature | σ con corruptos | σ sin ellos | Inflación | z comprimidos |
|---|---|---|---|---|
| `EURUSD_vol20` | 0,004368 | 0,002828 | **×1,545** | **−35,3 %** |
| `EURUSD_logret1` | 0,007144 | 0,006139 | ×1,164 | −14,1 % |
| `EURUSD_ma520` | 0,010833 | 0,010297 | ×1,052 | −5,0 % |
| `EURUSD` | 0,136293 | 0,136062 | ×1,002 | −0,2 % |
| `EURUSD_rangepct` | 0,014946 | 0,014998 | ×0,997 | +0,4 % |
| `BRENT_EURUSD_RATIO` | 17,2777 | 17,2803 | ×1,000 | −0,0 % |

Lectura honesta: **dos features (`EURUSD_vol20` y `EURUSD_logret1`) entran a la
red sistemáticamente encogidas**, un 35 % y un 14 %. Las otras cuatro son
indiferentes. Son 2 de 180 canales, y la 1ª pata ya había concluido que el
*cross-asset* **degradaba** la detección de la geometría del canal, de modo que
el sentido del sesgo —atenuar dos variables cross-asset— no favorece la
conclusión publicada, la refuerza.

## 5. Lo que hay que decir en el paper

1. **No hay que recalcular nada**, y conviene decir por qué con números, no con
   un «no afecta».
2. Hay que declarar la **ventana de estandarización**: está indocumentada. Las
   `feature_means` publicadas no coinciden ni con la media de la muestra
   completa (1,2219) ni con la de entrenamiento (1,1100), sino con 1,2552. Eso
   es un hueco de procedencia independiente de este defecto, y hay que cerrarlo.
3. **Estandarizar sobre toda la muestra es, en sí mismo, una fuga leve**: la
   escala de test se calcula con datos de test. No cambia estas conclusiones,
   pero un comité lo va a preguntar. Conviene adelantarse.

## 6. Sugerencias a B (decide él)

- **Recalcular `feature_means`/`feature_stds` solo con entrenamiento** y
  reejecutar los 3 folds. No para corregir este defecto —que es marginal— sino
  para cerrar el punto 3 de arriba, que sí es una objeción de comité.
- **Documentar la ventana de estandarización** en el manifiesto del bundle.
- **Añadir las fechas de train/test a `dataset_metadata.json`**: han tenido que
  reconstruirse casando tensores, lo cual no es aceptable en una cápsula
  reproducible.
