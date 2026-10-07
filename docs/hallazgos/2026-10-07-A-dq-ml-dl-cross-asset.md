# Hallazgo · DQ con ML/DL — el control cross-asset de ventana domina; ML/DL no aportan

- **Autor:** A · **Fecha:** 2026-10-07 · foco DQ (MASTER: mejorar el control con ML/DL).
- **Reproducción:** `code/applications/experiments/dq_ml_dl_detectors.py`,
  `results/reports/dq_ml_dl_detectors.json`. Ground truth por inyección, FP=5 %
  emparejada, modelos ajustados SOLO en train (≤2018), test > 2020-08, REPS=30.

## Recall por familia (nivel ventana, FP=5 %)
| Detector | decoplamiento | stale | salto |
|---|---|---|---|
| 3σ (benchmark) | 0,05 | 0,05 | 0,05 |
| **cross-asset ventana (1−R²)** | **0,98** | **1,00** | **0,93** |
| IsolationForest (ML) | 0,06 | 0,03 | 0,10 |
| Autoencoder conv 1D (DL) | 0,07 | 0,06 | 0,08 |

## Lectura
1. **La mejora sobre 3σ es real y grande, pero viene del control cross-asset
   estadístico de ventana (1−R² de BRENT sobre sus pares)**, no del ML/DL. Capta
   decoplamiento y stale casi perfecto porque mide justo lo que se rompe: la
   co-movimiento con los pares. Es **invariante de escala**, así que robusto al
   cambio de régimen de volatilidad train→test.
2. **ML (IsolationForest) y DL (autoencoder) NO baten** a esa estadística: quedan
   al nivel del FP. El modelo complejo no añade sobre la feature correcta.

## Autocrítica (por qué el ML/DL rinde tan bajo, y por qué no cambia la conclusión)
- El test (2020–2026) es mucho más volátil que el train (2007–2018), así que para
  los modelos no supervisados (AE/IForest) **casi todo el test parece anómalo** y
  se pierde la señal. Un AE con normalización por ventana o ajustado a vol
  rendiría más —pero el cross-asset 1−R² ya está en ~0,98–1,00, así que **hay poco
  margen para batirlo**.
- El 3σ falla incluso en saltos porque, calibrado en train, el umbral queda
  altísimo en un test tan volátil: argumento adicional a favor de controles
  **adaptativos/estructurales** frente al 3σ estático.

## Consecuencia para el paper y el reparto
- **Capa de control DQ = checks TRIM estructurales + cross-asset 1−R² de ventana.**
  Es una mejora demostrada, barata y robusta sobre el benchmark 3σ.
- La **CNN 1D / generativo (B)** debe batir al cross-asset 1−R² (~0,98) para
  justificarse: es un **listón muy alto**. Si no lo supera, el mensaje honesto del
  paper es que el valor está en la feature cross-asset correcta, no en la
  complejidad del modelo.
