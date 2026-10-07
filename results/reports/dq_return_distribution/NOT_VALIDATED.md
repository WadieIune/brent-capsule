# Uso restringido

El resumen JSON mezcla estadística descriptiva de colas con una extrapolación
hipotética de distorsión residual. No usar sus porcentajes de «distorsión
corregida» o «ganancia de precisión» como validación del framework: suponen
corrección perfecta, agregan ventanas no pareadas/solapadas, pesos uniformes y
FPR no equivalentes. Ver `docs/auditorias/2026-10-07-A-challenge-dq-return-distribution.md`.

El panel descriptivo de rendimientos puede reutilizarse con sus limitaciones;
para la comparación multi-activo, utilizar el artefacto
`results/reports/dq_return_distributions/`.
