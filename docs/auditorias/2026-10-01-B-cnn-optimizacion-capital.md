# Modelo de optimización de capital con CNN visual

Fecha 2026-10-01. Estado: implementado y ejecutado; resultado exploratorio sin ventaja económica CNN demostrada. Supervisor B y revisión independiente shock_research.

## Modelo entregado

Exposición ilustrativa: importador, un millón EUR equivalente de petróleo comprado en USD. Cada diez observaciones comunes se eligen cobertura petróleo hp, cobertura divisa hf y reserva R. Restricciones: hp,hf en {0,.25,.5,.75,1}, hp+hf<=1 y R+coste de cobertura<=150000 EUR. Es un límite experimental de capacidad; requiere sustitución por límites de negocio.

La pérdida física relativa es exp(rBrent-rEURUSD)-1. La cobertura se aproxima mediante dos instrumentos ideales con pago relativo hp*(exp(rBrent)-1)+hf*(exp(-rEURUSD)-1). No representa liquidaciones negociables de futuros ni márgenes intermedios.

Para escenarios s con pesos p_s, el optimizador minimiza:

J(hp,hf,R) = coste_cobertura + (0.05*10/252)*R + 2*sum_s p_s*max(perdida_residual_s-R,0).

Coste cobertura = 0.001*exposicion*(hp+hf). Reserva en malla de 5000 EUR. Financiación bajo convención diez sesiones/252, no días calendario. El nivel implícito de reserva sin restricciones es próximo al cuantil 99.90%, muy exigente para esta muestra; no se presenta como ES calibrado.

## Participación real de CNN

Ventanas pasadas de 64 observaciones de retornos y varianza media de cinco observaciones para Brent y EURUSD. Imágenes GASF/GADF por variable, escalado train-only y transformación acotada fija [0,1], sin normalización por ventana. La CNN 2D produce probabilidades de seis clases de escenarios conjuntos; los clusters se ajustan únicamente en entrenamiento. Dentro de cada clase se mantienen todos los escenarios realizados de entrenamiento, no solo su centro. Mezcla fija de 20% con distribución histórica. El mismo optimizador y restricciones se aplican al histórico, logit de ventana completa, CNN1D y CNN visual.

El helper independiente del otro agente añade soporte de máscaras y escalado robusto; no se utilizó en esta primera ejecución, que usa fechas de precios conjuntamente observados sin rellenar. Las imágenes del run son generadas por el propio script. No mezclar ambas implementaciones en la descripción del experimento.

## Backtest

Train desde 2015, validación anual previa, purga de etiquetas de diez observaciones en ambos límites. Información hasta la observación anterior a la decisión. Calendario global cada diez observaciones evita reiniciar posiciones en enero. Horizonte en observaciones comunes, no días hábiles garantizados. La demora de una observación no equivale a una auditoría de disponibilidad/vintage.

67 decisiones evaluadas en 2024-2026; una semilla (42). La muestra histórica ya inspeccionada es exploratoria. Coste evaluado incluye financiación, tarifas de cobertura y penalización de déficit, no P&L contable total.

| Modelo | Reserva media EUR | Coste objetivo realizado medio EUR | Déficits |
|---|---:|---:|---:|
| Histórico | 60000.00 | 1119.0476 | 0/67 |
| Logit ventana completa | 59925.37 | 1118.8995 | 0/67 |
| CNN1D | 59328.36 | 1117.7150 | 0/67 |
| CNN visual | 60000.00 | 1119.0476 | 0/67 |

Todos seleccionan hp=1,hf=0 en todas las decisiones. Pérdida media de los peores 5% casos observados: 21745.54 EUR en todos. Cero déficits en 67 decisiones no acredita calibración extrema ni ausencia de riesgo.

Delta coste CNN visual menos histórico: 0 EUR. Frente a logit +0.1481 EUR; frente a CNN1D +1.3326 EUR. Los pequeños contrastes no constituyen ventaja económica ni confirmación estadística con esta muestra. Bootstrap por bloques de tres decisiones; no protege contra selección de diseño ni escasez de shocks.

## Convergencia y decisión supervisora

Ambos agentes coinciden: imagen como representación, escenarios futuros conjuntos, objetivo económico, normalización causal, mismos comparadores/restricciones, y capital económico separado de capital regulatorio. El challenge corrigió solapamiento anual y pérdida de signo GAF, y añadió comparaciones pareadas completas.

Veredicto: optimizador funcional, incorporación CNN verificable, utilidad incremental no demostrada. No introducir límites/costes artificiales después del test para fabricar una ventaja. Siguiente protocolo: sensibilidad de costes/penalizaciones declarada previamente y exposición/instrumentos/capacidad genuinos; exigir que probabilidades distintas produzcan cambios de decisión útiles. Falta curva riesgo-coste, calibración, sensibilidad por semillas, trayectorias de colateral e instrumentos negociables. Ninguna reducción regulatoria atribuida a CNN.

## Reproducibilidad

Script code/applications/experiments/risk_director_capital_cnn.py. Outputs code/applications/outputs_capital/risk_director_capital_cnn/{summary.json,decisions.csv}. Hash panel b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3. Summary contiene hash del script y particiones.

Ejecutar: .venv/bin/python code/applications/experiments/risk_director_capital_cnn.py --panel data/panel_extendido_2026-09-09.csv --out code/applications/outputs_capital/risk_director_capital_cnn --seed 42

Verificación: cuatro pruebas del optimizador (sin riesgo, presupuesto/capacidad, ampliación presupuesto, signo imagen) y cinco pruebas helper independiente superadas. Pruebas conservadas en tests/test_risk_director_capital_optimizer.py y tests/test_cnn_capital_images.py.
