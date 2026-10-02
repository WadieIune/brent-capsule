# Estado al cierre del 2026-09-11 — para continuar

Resumen de dónde quedó todo, qué está en `main` y qué falta. Lo escribe A.

## En `main` y cerrado

| Entregable | Estado | Fichero |
|---|---|---|
| Panel extendido a 2026-09-10 (21 vars) + EURUSD desde BCE | ✅ | `data/panel_extendido_2026-09-09.csv`, `data/verify_panel.py`, `data/INVENTARIO_PANEL.md` |
| Auditoría: la corrupción de EURUSD no invalida nada publicado | ✅ | `docs/auditorias/2026-09-11-A-impacto-corrupcion-eurusd-en-resultados-publicados.md` |
| Supervivencia de canal reproducida | ✅ C-index **0,664 ± 0,007** | `code/part2_channel_survival/validation.py` |
| Gate barato H1/H3 (negativo honesto) | ✅ | `docs/hallazgos/2026-09-11-A-H1-H3-gate-barato-capital.md`, `code/applications/experiments/_h1h3_gate/` |
| Arquitectura del sistema (figura + doc) | ✅ | `docs/ARQUITECTURA_SISTEMA.md`, `docs/figuras/sistema_productivo_cnn_gate_capital.svg` |
| Metodología del backtest | ✅ | `docs/BACKTEST_METODOLOGIA.md` |
| Propuesta CNN↔capital (H1/H3/H2) | ✅ | `docs/PROPUESTA_CNN_CAPITAL.md` |

## Resultados clave (los que pasan el backtest)

- Detección de canal (CNN): AUC **0,97 / 0,956** OOT.
- Supervivencia (XGB-AFT): C-index **0,664 ± 0,007**.
- DQ → capital: el dato sucio infradota **13,4 %**.
- VaR vol-condicional (FHS-EWMA): **−22,7 %** de capital a igual cobertura
  (gate barato pasado; **pendiente backtest completo — zona de B**).
- H1 (clustering) y la geometría sobre la vol: **no pasan** el gate.

## ✅ RESUELTO el 2026-10-02 — validación del refit por fold

Ejecutados control (refit off) y refit (refit on) en el mismo entorno:

| Métrica | Control (off) | Refit (on) | Publicado |
|---|---|---|---|
| Sharpe por fold | [−0,336, −0,553, 1,010] | [−0,317, −0,553, 0,930] | [0,286, −1,005, 0,235] |
| DSR | 0,087 | 0,095 | 0,084 |
| PBO | 0,830 | 0,821 | 0,729 |
| macro-F1 | 0,145 | 0,145 | 0,181 |

Dos conclusiones:

1. **El control (refit off) NO reproduce lo publicado** — y como refit off es el
   comportamiento original, la causa **no es mi cambio**: es **deriva de versión
   de PyTorch**. El Dockerfile del capsule fija `torch==2.2.2` (el entorno que
   generó `results/`); mi `.venv` local tiene 2.14.0. El entrenamiento CPU es
   sensible a la versión. **El capsule reproduce bajo su Dockerfile pineado; mi
   venv local no es ese entorno.** No hay nada que arreglar en el capsule.
2. **El refit, comparado limpio (mismo venv, off vs on), es marginal**: DSR
   0,087→0,095, PBO 0,83→0,82, macro-F1 idéntico. No desestabiliza, pero tampoco
   cambia la historia.

**Decisión:** el refit se queda **OPT-IN y por defecto OFF** (ya está así). No se
promueve a la pipeline publicada. Una validación definitiva exigiría el entorno
pineado (torch 2.2.2); no merece la pena porque el efecto es marginal y no es un
resultado de titular. El `image_cache::_data_fingerprint` se mantiene (mejora de
correctitud, sin efecto con el default).

## ~~⚠️ WIP sin validar~~ (histórico, ya resuelto arriba)

En `code/brent_pattern_system/` quedaron dos cambios de pipeline, ahora **seguros
pero sin validar**:

1. `train_torch.py` — función `refit_zscore()` + reestandarización por fold +
   escritura de fechas train/test en `dataset_metadata.json`.
   **`cv.refit_zscore_per_fold` está por defecto en `False`**, así que el capsule
   reproduce los `results/` publicados tal cual. Es OPT-IN.
2. `image_cache.py` — `_data_fingerprint()`: la clave de caché ahora incluye el
   **contenido** de las features, no solo sus nombres (antes, al reestandarizar,
   devolvía imágenes viejas). Mejora de correctitud, sin efecto con el default.

**Por qué están sin validar:** el run de control (escala global, para confirmar
que reproduce los Sharpe publicados 0,286 / −1,005 / 0,235 **antes** de activar
el refit) se interrumpió. 

**Próximos pasos, en orden:**
1. Lanzar el run de control (`refit_zscore_per_fold: false`) y confirmar que
   reproduce `results/reports/torch_walkforward_summary.json`.
2. Si reproduce, lanzar el run con `refit_zscore_per_fold: true` y comparar
   (capital, Sharpe, independencia). Decidir con B si se promueve.
3. Configs de trabajo en `scratchpad/config_control.yaml` y `config_refit.yaml`
   (recrear; el scratchpad es efímero).

**Nota de proceso:** estos dos ficheros se colaron en `main` en el commit
`e21dce2` vía `git add -A` con el flag en `True` (habría roto la reproducción).
Corregido a `False`. Lección: no usar `git add -A` con cambios de pipeline a
medias; añadir por ruta.

## Decisiones pendientes de B (supervisor), en su bandeja

- Formalizar el VaR vol-condicional (−22,7 %) con backtest completo (DSR/PBO +
  Christoffersen). Es su zona.
- ¿Cerrar H1 o pedir la prueba cara de textura de imagen? (recomendación de A:
  cerrar).
- ¿Promover el refit por fold tras validarlo?
- Revisar `BACKTEST_METODOLOGIA.md` y decir si falta algún test de track-b.
