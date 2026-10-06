# Preregistro exploratorio: representación generativa de Brent y cartera

- **Fecha:** 2026-10-06
- **Autor:** Agente A
- **Estado:** diseño para revisión de B; resultados de alerta/anomalía aún exploratorios.
- **Universo financiero:** seis futuros/commodities en cartera larga proxy 1/N
  (BRENT, WTI, GOLD, SILVER, COPPER, NATGAS). No representa posiciones,
  multiplicadores ni límites reales del MASTER.

## A. Evaluación multiactivo para Risk Director

La pregunta operativa es si el score as-of por activo puede priorizar revisión
o reducir gross long cuando sube el riesgo bajista conjunto, y si esa decisión
protege el capital **neto** de fricciones frente a FHS-EWMA y solo-vol. Régimen y
supervivencia son inputs/ablations, no beneficios asumidos.

- Fuente: `data/panel_extendido_2026-09-09.csv`; congelar hash, rango y calendario
  tras auditar columnas, duplicados, días faltantes y procedencia.
- La feature de supervivencia basada en ratios se excluye para WTI en todos los
  folds porque la serie cruza cero; su P&L y la feature geométrica de anchura en
  unidades de precio se conservan. El universo de features queda fijo entre
  folds, no condicionado a cuándo aparece el settlement negativo.
- Proxy invertible no disponible. Mantener 1/N nocional solo como referencia
  histórica cuando todos los settlement sean positivos. Para no borrar el
  settlement negativo WTI de abril 2020, una evaluación común alternativa usa
  variación de precio diaria ΔP, escalada por la desviación típica de ΔP de cada
  activo estimada exclusivamente en el train del fold y pesos iguales sobre
  esas unidades de riesgo. Esto mide una cesta larga en **unidades de riesgo**,
  no euros ni capital real; reportar también resultados excluyendo el activo
  conflictivo/día como sensibilidad, sin eliminar silenciosamente el evento.
- Baselines: VaR FHS-EWMA de cartera (cuantil inferior de bloques solapados de
  10 residuos filtrados EWMA, ventana trailing de 252 sesiones, escalado por la
  sigma EWMA actual) y overlay solo-vol. Candidatos: régimen,
  supervivencia, DQ y combinación; seleccionar umbrales de alerta/exposición
  únicamente en validación. Covarianzas, escalas y cualquier contribución al
  riesgo se ajustan con pasado disponible en cada fold.
- Walk-forward expansivo, con purga de al menos el horizonte forward (10
  sesiones) en fronteras. Mismo calendario, presupuesto de alertas/exposición,
  límites gross/net y cooldown para todos. Comparar curva pérdida de cola vs
  turnover/falsas alarmas, no solo un punto favorable.
- Métricas: VaR exceptions + Kupiec/Christoffersen/DQ, ES, drawdown, rotación,
  P&L neto y `k × VaR` solo como proxy. Sharpe/alpha únicamente descriptivos,
  simulados y acompañados de costes/sensibilidades.
- Criterio: sin pesos, multiplicadores, posiciones y fills del libro, no se
  afirmará capital ahorrado ni alpha financiero. RL no entra hasta que se
  demuestre un simulador contrafactual defendible y las políticas deterministas
  tengan valor incremental.

## B. Modelo generativo: VAE de trayectorias de Brent

La implementación `code/applications/experiments/brent_regime_autoencoder.py`
usa ventanas causales de 32 log-retornos diarios. Un VAE denso comprime
32→16→4→16→32, optimizado con MSE + `0.01 × KL` y prior latente `N(0,I)`. El
espacio latente y cuatro clusters train-only describen configuraciones recientes
de trayectoria; la decodificación desde el prior y el ruido gaussiano de
observación calibrado en la validación pre-2000 permiten generar ventanas
sintéticas para inspeccionar dispersión, colas y autocorrelación. **Esto no es
explicación causal de factores de Brent**.

- **Adaptación candidata:** recalibrar anualmente (252 sesiones), reutilizando
  solo los últimos cinco años disponibles; fijar escala, pesos y clusters en el
  train del fold. Selección de épocas con el año de validación inmediatamente
  anterior y purge ≥ 32 sesiones entre train/validación.
- **Comparadores:** VAE congelado (fit inicial anterior a 2000) y EWMA λ=0.94.
  Para la señal de anomalía, fijar el umbral en validación a una carga objetivo
  lo más cercana posible a 20 revisiones/año tras cooldown, con el mismo
  procedimiento y cooldown de 10 sesiones. La carga puede saltar por la
  agrupación temporal; publicar la carga alcanzada en validación y test, sin
  llamarla igualada si no lo es. Reportar recall por episodio de pérdidas acumuladas a
  10 sesiones (peor decil rolling train), falsas alarmas/año, revisiones/año y
  MSE de reconstrucción. AUC-PR/ROC diarias son secundarias por el solapamiento.
- **Interpretación de valor:** mejora de reconstrucción y estabilidad del
  espacio latente evidencia adaptación descriptiva, no predicción de riesgo.
  Solo una mejora repetida de captura de episodios a igual frecuencia de
  revisión justifica elevar la señal a revisión humana; una reducción de gross
  long exige además un overlay de cartera neto de costes frente a FHS-EWMA.
- Sin cambios de cadencia elegidos post-hoc: anual es el test primario; trimestral
  y semestral quedan para sensibilidad separada, no seleccionar retrospectivamente.

## C. Evidencia y límites

La literatura de adaptación a distribución cambiante advierte que series con
dependencia temporal no satisfacen sin más las garantías i.i.d.; un ajuste
periódico debe contrastarse con un modelo congelado y respetar purga/orden
temporal ([Huang et al., UAI/PMLR 2026](https://proceedings.mlr.press/v337/huang26b.html),
[Qin et al., ICML/PMLR 2022](https://proceedings.mlr.press/v162/qin22a.html)).
El VAE se considera modelo descriptivo experimental y no reemplaza al
incumbente FHS-EWMA.
