# Propuesta A → B · WP-RD1: supervivencia de canal para decisiones del Risk Director

- **Autor:** Agente A · **Fecha:** 2026-10-03
- **Estado:** propuesta para revisión de B; no es un preregistro ni se ha ejecutado.
- **Motivación:** conservar la detección y supervivencia como señales útiles
  para decidir cuándo revisar una exposición y, si hay datos reales, cuándo
  ajustar su cobertura. No se presupone que el canal prediga la dirección del
  precio ni que deba alterar la fórmula de VaR.

## Hipótesis

Condicionada a la misma carga operativa y a las mismas restricciones de riesgo,
una política que añade régimen y supervivencia del canal a un baseline de
volatilidad puede priorizar mejor las revisiones y, en una evaluación con
exposiciones y costes observados, reducir el coste neto de cola sin empeorar la
cobertura del riesgo.

La hipótesis tiene dos gates separados. Superar el primero solo valida utilidad
operativa de la señal; no demuestra ahorro, alpha ni mejora del Sharpe.

## Gate 1 · Valor de la alerta

**Pregunta:** con el mismo número de revisiones por año, ¿la supervivencia ayuda
a avisar antes de episodios de riesgo material frente a calendario y solo-vol?

- **Estado as-of:** probabilidad de régimen, edad del canal, probabilidades de
  supervivencia a 5/10/20 sesiones, incertidumbre de la señal, EWMA/volatilidad
  realizada, VaR/ES y estado de excepciones disponible en la fecha. Toda
  transformación se calcula con datos pasados.
- **Acción:** `sin alerta` o `revisar exposición`. La política solo prioriza
  revisión; no simula una cobertura que no se observó.
- **Evento objetivo:** episodio de pérdida o coste de compra a 10 sesiones que
  supera un umbral estimado únicamente en train. B debe confirmar que este
  objetivo y el proxy disponible representan el uso del Risk Director.
- **Comparadores:** calendario fijo calibrado en train; alerta solo-vol
  (EWMA); régimen sin supervivencia; supervivencia sola; combinación
  vol+régimen+supervivencia; y alerta aleatoria con igual frecuencia.
- **Métrica primaria propuesta:** captura de episodios a igual presupuesto de
  revisiones, dentro de una tolerancia de aviso fijada antes del test. Reportar
  además precisión, revisiones por año, lead time y curva coste-cobertura.
- **Éxito propuesto:** la combinación mejora la captura frente al mejor
  baseline fijo/solo-vol con IC pareado por bloques que excluye cero, sin
  exceder el presupuesto de revisiones. Se informa también si la mejora frente
  al nulo aleatorio de igual frecuencia es positiva.

## Gate 2 · Valor económico de la decisión

Solo se abre si Gate 1 pasa y hay datos de portfolio adecuados. Reproducir las
políticas en walk-forward con exposición, operaciones y costes reales o con un
simulador calibrado y validado por separado.

- **Acciones candidatas:** mantener, revisión humana o niveles discretos de
  cobertura. Los niveles, límites de rotación y restricciones de liquidez se
  fijan antes del test.
- **Comparadores:** política actual/fija, solo-vol, régimen, supervivencia y
  combinación. Mismo capital disponible, límites, calendario de información y
  costes de ejecución.
- **Métrica económica primaria propuesta:** coste de cola neto a protección
  comparable, con el coste de cobertura y la pérdida de exposición sin cubrir
  valorados en unidades del portfolio. B debe confirmar la función de coste y
  la tolerancia mínima de mejora antes de congelar el diseño.
- **Secundarias:** excepciones y agrupación (Kupiec, Christoffersen y DQ),
  expected shortfall, Sharpe neto, drawdown máximo, rotación, coste de
  transacción y oportunidad perdida. Menos excepciones por sí solo no cuenta
  como mejora si requiere más capital o cobertura.

## Diseño temporal y controles

- Walk-forward expansivo; señal y umbrales solo con información disponible en
  cada fecha; purge/embargo mínimo igual al horizonte objetivo de 10 sesiones.
- Umbrales y presupuestos elegidos en train/validación y congelados en test.
  No se iguala el presupuesto usando cuantiles del propio test.
- Comparaciones pareadas con bootstrap por bloques temporales; informar
  resultados por fold/año y sensibilidad a los episodios de estrés. El tramo
  2026 ajustado después de observarlo se etiqueta como caso de estudio, no como
  confirmación independiente.
- Aislar el aporte incremental con ablaciones: vol; vol+régimen;
  vol+supervivencia; vol+régimen+supervivencia.
- Hashes de panel, features, forecasts y política en el manifiesto. No mezclar
  `brent_fred_daily.csv` con `panel_extendido_2026-09-09.csv` sin declarar
  universo y cobertura.

## Datos que faltan para afirmar alpha o Sharpe

El panel de mercado y los forecasts actuales no bastan para calcular el P&L de
una política de cobertura empresarial. Para Gate 2 hacen falta: serie temporal
de exposiciones/compras y divisa; cobertura ya ejecutada; instrumentos y
precios ejecutables; comisiones, spreads y roll; límites de liquidez/margen; y
regla de valoración de compras no cubiertas. Sin esto, Gate 1 puede validar
priorización de alertas, pero Sharpe/alpha y ahorro económico quedan sin
identificar.

## Secuencia y decisión solicitada a B

1. Revisar el evento objetivo y la métrica de Gate 1; confirmar si se usa coste
   de compras a 10 sesiones o una definición de riesgo ya existente.
2. Confirmar qué datos reales de exposición/cobertura existen y quién los
   aporta. Si no existen, aprobar Gate 1 como alcance independiente y no
   atribuirle resultados económicos.
3. Validar comparadores, umbrales de éxito, bloques y calendario walk-forward;
   después congelar un preregistro antes de ejecutar.
4. Autorizar el desarrollo del arnés determinista. RL queda para una etapa
   posterior, cuando haya soporte contrafactual suficiente o un simulador
   validado. La literatura de evaluación offline advierte que el rendimiento
   histórico puede no transferir bajo cambio de distribución
   ([Si et al., ICML 2020](https://proceedings.mlr.press/v119/si20a.html));
   para cobertura con fricciones, véase
   [Deep Hedging](https://arxiv.org/abs/1802.03042).

## Evidencia previa que motiva, no confirma, la propuesta

El laboratorio existente usa costes hipotéticos y presupuestos de alerta
igualados ex post; su máxima ganancia de captura externa fue 0. En la batería
científica, el forecast externo tuvo ΔQLIKE `+0.0473` frente al baseline (peor,
con IC por bloques que cruza cero), mientras que precisión/captura de alertas
mejoraron solo marginalmente. Esto no justifica RL todavía; sí motiva medir si
la señal cambia decisiones a carga comparable, con objetivos económicos
observables.
