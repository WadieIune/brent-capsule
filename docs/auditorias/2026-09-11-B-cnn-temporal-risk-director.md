# Evaluacion B: CNN temporal para Risk Director

Fecha: 2026-09-11. Estado: provisional, pendiente de challenge de A.

## Entorno

El usuario autorizo instalar dependencias cuando fueran necesarias. Se instalo PyTorch CPU en `.venv`:

- torch 2.14.0+cpu
- torchvision 0.29.0+cpu

Panel usado: `data/panel_extendido_2026-09-09.csv`.
Hash: `b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3`.
`data/verify_panel.py` pasa completo.

## Diseño ejecutado

Script: `code/applications/experiments/risk_director_temporal_cnn.py`.
Salida: `code/applications/outputs_cnn/risk_director_temporal_cnn/summary.json`.

La CNN ya no opera sobre precio bruto ni canales. Usa ventanas de 64 observaciones con:

- riesgo propio: `rv1`, `rv5`, `rv22`, `ret5`, `ret20`, `vol20`;
- informacion externa: WTI, spread WTI-Brent, VIX, dolar amplio, tipos, SOFR, gas, metales e indices;
- edad de cada variable externa.

La primera parametrizacion directa fallo por escala en 2026. Se corrigio a una forma mas estable: la CNN predice un ajuste multiplicativo sobre EWMA/HAR. La incertidumbre se estima con Monte Carlo dropout. Esto es una aproximacion bayesiana ligera, no una red bayesiana completa.

## Resultado

Delta QLIKE = perdida CNN menos comparador. Negativo favorece CNN.

- CNN vs tabular externo: `+0.035244`.
- IC 95 % bloques 20: `[-0.072384, +0.153587]`.
- CNN vs baseline EWMA/HAR: `+0.082530`.
- IC 95 % bloques 20: `[+0.007051, +0.177041]`.

Por anos, CNN vs tabular externo:

- 2024: `+0.159633`.
- 2025: `-0.050910`.
- 2026: `-0.024497`.

Lectura: la CNN temporal no gana globalmente y no puede entrar como resultado positivo confirmatorio. Sin embargo, mejora frente al tabular externo en 2025 y 2026. En las ultimas fechas del episodio 2026, la CNN residual reduce la sobreestimacion del baseline y del tabular; por ejemplo, del 2026-08-19 al 2026-08-25 todos los deltas CNN-tabular son negativos.

## Veredicto supervisor

Estado: `provisional/degradado`.

La CNN temporal sobre volatilidad/riesgo es viable y ya no es una CNN de precio/canal. Pero el gate cientifico no esta superado: la media global no mejora al tabular y CNN vs baseline sigue siendo peor. El resultado util para el paper es:

1. La arquitectura correcta es CNN temporal residual sobre riesgo, no CNN sobre precio.
2. La CNN muestra senal en los anos recientes y durante el episodio 2026, pero no suficiente para afirmacion confirmatoria.
3. La capa bayesiana ligera entrega incertidumbre, pero aun no demuestra calibracion superior.
4. La aplicacion Risk Director sigue apoyada como monitor/politica de vigilancia; la CNN queda como componente prometedor pero pendiente de challenge y mejora.

## Siguiente paso

A debe desafiar:

- si la comparacion tabular usa exactamente el baseline justo;
- si las edades y variables externas introducen retardos operativos insuficientes;
- si el resultado 2026 es caso de estudio post-hoc o evidencia OOS aceptable;
- si el criterio de utilidad debe pasar de QLIKE a coste de cobertura con exposicion real.
