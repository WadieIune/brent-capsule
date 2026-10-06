# Propuesta A → B · WP-RD1 multiactivo para proteger cartera y capital

- **Autor:** Agente A · **Fecha:** 2026-10-06
- **Estado:** cambio de alcance solicitado por el MASTER; pendiente de que B
  actualice y congele el preregistro antes de la siguiente ejecución.
- **Decisión del MASTER:** cartera financiera larga; evaluar el riesgo de la
  cartera con los activos disponibles, no inferir utilidad de una señal Brent
  aislada.

## Universo y proxy de cartera

El experimento de cartera existente define `DEFAULT_ASSETS` como
`BRENT`, `WTI`, `GOLD`, `SILVER`, `COPPER` y `NATGAS`. Su cartera de referencia
usa pesos nocionales iguales (1/N); las contribuciones al riesgo observadas en
el manifest histórico son desiguales. No hay en el repo posiciones ni pesos
reales de la cartera del MASTER, así que 1/N es un **proxy reproducible**, no
una descripción de las posiciones actuales. Los demás activos del panel (FX,
índices, tipos y VIX) quedan como variables de contexto hasta que se defina que
forman parte invertible de la cartera.

La evaluación nueva debe usar `data/panel_extendido_2026-09-09.csv`, fuente
mandante del panel actualizado. Las seis series tienen 4.886 filas conjuntas
con datos positivos entre 2007-01-02 y 2026-09-09; WTI contiene un settlement
negativo. Antes de fijar retornos hay que elegir una representación de P&L que
conserve ese evento real: no borrar silenciosamente el día ni aplicar
log-retornos a un precio no positivo. El backtest existente usa
`dataset_wide_with_target.csv` y termina el test el 2026-03-05.

## Estado de la evidencia multiactivo

El manifest de `portfolio_var_alert` documenta seis activos, pesos 1/N y test
2020-08-21–2026-03-05. FHS-EWMA baja la tasa de excepciones de 1,292 % a
1,005 %, mejora Christoffersen (p=0,0011 a 0,1284) y reduce el proxy de capital
de peor ventana 1,84 % frente al VaR histórico; **DQ aún rechaza** FHS-EWMA
(p=0,0164), por lo que no es una referencia plenamente validada.

La fragilidad de canal no concentra excepciones: lift=0 a q80, frente a lift
3,194 para EWMA-vol. El overlay `predicted_continuous` aumenta el proxy de
capital 5,12 % frente al histórico y empata con el control constante de igual
VaR medio. No hay evidencia actual de que supervivencia añada protección de
cola o libere capital en esta cesta.

Hay además un riesgo de fuga en el artefacto existente: las contribuciones de
riesgo agregadas para ponderar fragilidad se calculan con `risk_contributions`
sobre la matriz completa de retornos. En el nuevo walk-forward, covarianzas y
contribuciones deben estimarse solo con el pasado disponible en cada fold.

## Hipótesis y capas de IA a evaluar

**Hipótesis falsable:** frente a FHS-EWMA y una política solo-vol, las señales
de calidad de dato, régimen y supervivencia, y un forecast temporal/tabular
multiactivo con las mismas entradas, mejoran la protección de cola/capital de
la cartera larga sin empeorar cobertura ni exceder el presupuesto de riesgo y
rotación.

Las capas se prueban por separado y con ablaciones:

- **DQ:** detectar precios inválidos, relleno y sesiones no negociadas antes de
  estimar riesgo; preservar eventos de mercado genuinos.
- **Régimen/supervivencia:** producir scores as-of por activo y agregarlos con
  contribuciones al riesgo calculadas dentro del train de cada fold.
- **Forecast multiactivo:** estimar probabilidad/distribución de pérdida de
  cartera a 10 sesiones con CNN temporal o modelo tabular. Ambos reciben la
  misma información y se comparan con EWMA/HAR/FHS; no se asume que la CNN gane.

Una señal de ruptura sin dirección no se usa para comprar/vender por dirección.
Su uso potencial es ajustar el nivel de revisión o la exposición larga cuando
un modelo calibrado predice riesgo bajista de cartera.

## Diseño de evaluación

- **Cartera primaria:** cesta larga 1/N de los seis activos como proxy; si el
  MASTER aporta pesos reales, abrir un análisis separado con esos pesos y sus
  exposiciones, sin reoptimizar en test.
- **Baselines:** VaR histórico, FHS-EWMA; política constante equivalente;
  política de reducción de exposición solo-vol. Modelos incrementales:
  régimen, supervivencia, DQ y forecast multiactivo, con ablaciones.
- **Acción simulada:** mantener o reducir el gross long a niveles discretos
  congelados en validación. Incluir rotación/costes de transacción. La cesta y
  su P&L son simulados si no hay posiciones ejecutadas.
- **Objetivo de riesgo:** pérdida de cartera a 10 sesiones con umbral estimado
  solo en train, agrupada en episodios no solapados. Para la política: curva
  pérdida de cola/cobertura frente a coste de falsas alarmas y rotación; punto
  operativo seleccionado en validación.
- **Métricas:** VaR exceptions, Kupiec, Christoffersen, DQ, ES, peor-250d
  `k × VaR`, drawdown y Sharpe neto de costes. Menos excepciones no cuenta si
  viene de mayor capital, menos exposición permanente o más rotación no
  presupuestada. Sharpe/alpha de la cesta proxy no son claims de rentabilidad
  real.
- **Validación:** walk-forward expansivo y purgado por 10 sesiones; umbrales,
  covarianzas y calibradores solo con pasado; bootstrap pareado por bloques;
  2026 se reporta como caso de estudio adicional.

## Decisión solicitada a B

1. Sustituir el siguiente run Brent-only por una prueba sobre la cesta 1/N de
   seis activos, dejando claro que es una cartera proxy.
2. Congelar fuente extendida, representación de P&L del WTI negativo, reglas de
   calendario y pesos antes de correr.
3. Usar FHS-EWMA como baseline fuerte, corrigiendo el cálculo de contribuciones
   de riesgo a train-only; no elevar el canal a mecanismo de capital mientras
   no supere ese baseline.
4. Evaluar el forecast temporal multiactivo como módulo distinto de la señal
   de supervivencia. Mantener RL aparcado hasta que el arnés de exposición y
   fricciones tenga soporte contrafactual defendible.

Los resultados anteriores se conservan como exploratorios; esta propuesta no
reescribe el pre-registro WP-RD1 ni adjudica un resultado económico.
