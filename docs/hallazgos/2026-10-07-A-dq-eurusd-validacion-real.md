# Hallazgo · Validación REAL del cross-asset con el defecto de EURUSD (2008)

- **Autor:** A · **Fecha:** 2026-10-07 · dato REAL (no inyectado).
- **Reproducción:** `code/applications/experiments/dq_eurusd_validation.py`,
  `results/reports/dq_eurusd_validation.json`.
- **Ground truth:** 10 días corruptos de 2008 en `dataset_wide_with_target.csv`
  (saltos de ±5,3 % a ±16 % que la serie limpia del BCE no tiene).

## Resultado (FP emparejada sobre días limpios)
Recall sobre los 10 defectos:
| FP | 3σ | cross-asset |
|---|---|---|
| 0,5 % | **1,00** | **1,00** |
| 1 % | 1,00 | 1,00 |
| 2 % | 1,00 | 1,00 |

**Ambos cazan los 10/10.** El defecto era de **salto**, y 3σ caza saltos; por eso
aquí **no hay ventaja de recall** del cross-asset.

## La ventaja que sí hay: separación (señal/ruido)
El |z| del cross-asset es **sistemáticamente mayor** que el de 3σ, porque quita el
factor dólar/mercado común de 2008 y aísla el movimiento propio de EURUSD:

| día | ret corrupto | z 3σ | z cross-asset |
|---|---|---|---|
| 2008-09-08 | +5,3 % | 6,1 | **10,5** |
| 2008-10-08 | +9,6 % | 6,8 | **12,4** |
| 2008-02-08 | +7,3 % | 5,9 | **8,5** |

Mediana |z|: **3σ ≈ 6,0 vs cross-asset ≈ 8,7** (~1,4×). A umbral más estricto o en
un régimen aún más volátil, el cross-asset **retiene poder de detección más tiempo**.

## Lectura honesta (sin sobreafirmar)
1. **El framework queda validado en dato real:** un control de rendimientos (3σ
   o cross-asset) habría cazado el defecto que el pipeline dejó pasar. El incidente
   ocurrió porque el control desplegado era **correlación de niveles** (0,9989,
   parecía bien) — el control equivocado.
2. **Para este defecto (salto), 3σ basta**; la ventaja decisiva del cross-asset en
   **recall** es para **stale/decoplamiento** (sintético: cross-asset 0,98 vs 3σ
   0,05), no para saltos. Aquí su aporte es **mayor separación**, no mayor recall.
3. Es la validación real que complementa la sintética: juntas sostienen que la
   capa DQ = TRIM + 3σ + **cross-asset** cubre saltos, rachas y decoplamiento,
   cada uno con el control que lo caza mejor.
