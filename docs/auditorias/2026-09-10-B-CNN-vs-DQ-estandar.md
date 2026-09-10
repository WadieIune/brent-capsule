# CNN frente a data quality estadística — alcance industrial

## Regla de diseño

La CNN **no sustituye** los controles básicos de calidad. Repetidos,
repetidos consecutivos, retornos cero, outliers a 3σ, máximos/mínimos, número
de registros, huecos y duplicados deben resolverse primero con reglas y
estadísticos transparentes.

## Qué aporta cada capa

| Capa | Detecta bien | Ventaja | Decisión FRTB |
|---|---|---|---|
| DQ estadístico | esquema, duplicados, faltantes, ceros, stale, outliers marginales, extremos | explicable y auditable | `block`/`review` inmediato |
| CNN contextual | combinación de forma, secuencia, volatilidad y ruptura anómala que no es extrema punto a punto | contexto temporal y multivariable | prioriza revisión humana; nunca certifica RFET |
| Gate conjunto | conflicto entre precio, calendario, señal CNN y procedencia | trazabilidad | evidencia para RFET/NMRF/PLA |

## Qué gana realmente la CNN

Solo gana si, sobre un conjunto con verdad conocida y fuera de muestra, reduce
falsos negativos **después** de controlar la carga de alertas y de compararla
contra los estadísticos estándar. Ejemplos plausibles: un desplazamiento
gradual de régimen, una secuencia de precios internamente incoherente aunque
ningún punto supere 3σ, o una combinación multiactivo que univariante no ve.

Si no supera ese test, se conserva como señal exploratoria y no aporta valor
industrial demostrable. La librería estadística sigue siendo la primera línea.
