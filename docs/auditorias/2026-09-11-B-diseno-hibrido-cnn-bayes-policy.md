# Diseño híbrido B: CNN temporal, capa bayesiana y política Risk Director

Fecha: 2026-09-11. Estado: protocolo supervisor para la siguiente batería.

## Decisión técnica

Sí se puede montar un híbrido CNN + capa probabilística + política. Lo que no es defendible todavía es venderlo como aprendizaje por refuerzo completo. Tenemos una sola trayectoria histórica de mercado y pocos shocks geopolíticos independientes; un agente RL puede memorizar episodios, explotar solapamientos y aprender una política que no tiene soporte fuera de muestra.

La versión defendible es una pila de tres niveles:

1. **Representación**: CNN temporal 1D sobre ventanas de riesgo, no sobre precio bruto. Entradas: retornos, r², log-varianza, semivarianzas, vol20/vol60, cambios de vol, spreads, VIX, dólar, tipos, edades y máscaras de disponibilidad. Se compara contra un tabular con exactamente las mismas entradas.
2. **Capa bayesiana/probabilística**: calibrar incertidumbre y combinar modelos. No hace falta empezar con una red bayesiana grande; basta una mezcla bayesiana/stacking temporal con pesos aprendidos solo en validación pasada. Objetivo: distribución de riesgo y probabilidad de excedencia, no una clase rígida.
3. **Política Risk Director**: no RL puro; primero contextual bandit/offline policy. Acciones: monitor, revisar exposición, cobertura ligera, cobertura fuerte. Recompensa/coste: pérdida extrema no cubierta, coste de cobertura, falsas alarmas y oportunidad perdida. La política se evalúa walk-forward con umbrales congelados antes del test.

## Por qué no RL completo aún

RL requiere estados, acciones, recompensas y transiciones. En mercado real solo observamos una acción histórica implícita, no contrafactuales: no sabemos qué habría pasado si hubiéramos cubierto otro porcentaje. Además, los shocks de oferta son pocos. Con RL completo, la señal puede venir de simulador o de supuestos, no del dato.

Por eso el orden correcto es:

- primero **policy evaluation** con políticas fijas;
- después **contextual bandit** con acciones discretas y coste declarado;
- solo después RL, si construimos un simulador de exposición/shock y lo validamos contra episodios reales.

## Hipótesis nuevas

- H1-CNN: una CNN temporal sobre variables de riesgo mejora QLIKE o probabilidad de excedencia frente a un tabular con las mismas entradas.
- H2-Bayes: una combinación probabilística calibrada reduce mala calibración y mejora cobertura de intervalos frente al mejor modelo individual.
- H3-Policy: una política fija alimentada por la señal híbrida reduce coste esperado o déficit de cobertura a igual presupuesto de alertas.

## Gate supervisor

La CNN no sobrevive por estética. Debe ganar contra tabular. La capa bayesiana no sobrevive si solo suaviza sin mejorar calibración. La política no sobrevive si su mejora desaparece al igualar presupuesto de alertas/coste. Cualquier mejora en el episodio Irán/Ormuz debe declararse caso de estudio si el diseño se ajustó después de verlo.


## Primer laboratorio de política ejecutado

Script: `code/applications/experiments/risk_director_policy_lab.py`.
Entrada: `code/applications/outputs_scientific/risk_director_scientific_eval/forecasts.csv`.
Salida: `code/applications/outputs_policy/risk_director_policy_lab/summary.json`.

Resultado diagnóstico:

- Observaciones evaluadas: 671.
- Tasa de evento: 29.66 %.
- La política con señal externa mejora el coste proxy en el 100 % de los grids de sensibilidad.
- Mejor ventaja externa frente a base: `-4.61e-06` de coste proxy medio.
- Ventaja mediana: `-1.82e-06`.
- Ganancia máxima de captura: `0.0`.

Lectura supervisora: no hay todavía política RL ni mejora fuerte. Sí hay una señal pequeña de ordenación de severidad a igual presupuesto de alertas. Esto justifica continuar con política offline y costes de negocio reales, pero no permite escribir que el híbrido CNN/info/RL esté validado.

Siguiente paso: ejecutar H1-CNN con una CNN temporal real sobre volatilidad/riesgo cuando haya entorno torch disponible o se habilite el entorno usado por `regime_cnn_causal.py`. Hasta entonces, la contribución viva es: panel auditado + monitor Risk Director + política diagnóstica, con CNN pendiente de representación temporal.
