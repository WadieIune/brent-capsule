# Pre-registro congelado · WP-RD1 — supervivencia/régimen como soporte a la decisión

- **Fecha de congelación:** 2026-10-03 · **Autoriza:** MASTER.
- **Diseño:** B (`PROPUESTA_WP_RD1_RISK_DIRECTOR.md`) + decisiones de A
  (`RESPUESTA_A_WP_RD1_A.md`). **Congelado ANTES de ejecutar.**
- **Separación estricta:** Gate 1 valida utilidad de alerta sobre **dato real de
  mercado**; Gate 2 estima valor económico sobre un **simulador calibrado con
  bibliografía** (resultados etiquetados *simulados*, nunca ahorro real).

## Gate 1 · Valor de la alerta (dato real, sin simulación)

- **Evento objetivo:** movimiento adverso del Brent a 10 sesiones por debajo de un
  umbral del **peor decil estimado SOLO en train**. Se reporta en paralelo una
  definición alternativa (salto de volatilidad realizada al decil superior).
- **Señal as-of (en la fecha t):** prob.\ de régimen, edad del canal, P(T>5/10/20)
  de supervivencia, incertidumbre de la señal, EWMA/vol realizada, VaR/ES y estado
  de excepciones. Todo con datos ≤ t; la decisión de t afecta al tramo t+1..t+10.
- **Comparadores:** calendario fijo (train) · solo-vol (EWMA) · régimen sin
  supervivencia · supervivencia sola · **combinación** vol+régimen+supervivencia ·
  **nulo aleatorio de igual frecuencia**. Ablaciones: vol / vol+régimen /
  vol+superv / todo.
- **Métrica primaria:** **captura de eventos a igual presupuesto de revisiones**
  (mismas revisiones/año), IC pareado por bloques que excluya 0. Secundarias:
  precisión, lead time, revisiones/año, curva coste-cobertura.
- **Éxito:** la combinación bate al mejor de {fijo, solo-vol} con IC por bloques
  que excluye 0, sin exceder el presupuesto; se informa también la mejora sobre el
  nulo. **No pasa** si no bate a solo-vol → se declara negativo.

## Gate 2 · Valor económico (SIMULADO, calibrado con bibliografía)

Solo si Gate 1 pasa. **Todo resultado se etiqueta "simulado bajo supuestos de
literatura", jamás ahorro/alpha/Sharpe real.** B valida la calibración antes de correr.

### Cartera simulada: consumidor de crudo que cubre con futuros Brent
- **Exposición física:** compra constante de $Q$ barriles/mes (normalizada).
- **Política de cobertura base:** ratio de cobertura fijo $\approx$ 60–70 %,
  coherente con la media histórica de la industria (~64 % en 2009–2010) y con
  ratios a corto de 70–95 % que decaen con el horizonte; horizonte de cobertura
  hasta 18–24 meses. *(Reuters factbox; Wikipedia «Fuel hedging».)*
- **Política con señal:** la alerta de Gate 1 sube/baja el ratio dentro de niveles
  discretos fijados a priori (p. ej. {50 %, 70 %, 90 %}), sin exceder una rotación
  máxima prefijada.
- **Costes de transacción:** futuros de crudo muy líquidos, spread ~1 tick
  (~0,1–0,15 pb por lado); se usa un **round-trip conservador de 2–10 pb**
  (incluye *roll*/slippage) y se reporta **sensibilidad** a ese rango.
  *(CME European Crude; bid-ask futuros.)*
- **Marco de cobertura con fricciones:** Deep Hedging (Buehler et al., 2018,
  arXiv:1802.03042) como referencia metodológica; aquí **sin RL** (arnés
  determinista), RL queda para cuando haya contrafactual/simulador validado.
- **Función de coste primaria:** coste de cola neto a protección comparable =
  coste de cobertura (pb × rotación) + pérdida de exposición no cubierta valorada
  en unidades de cartera. B confirma la función y la tolerancia mínima de mejora.
- **Secundarias:** excepciones y agrupación (Kupiec/Christoffersen/DQ), ES, Sharpe
  neto, drawdown, rotación, coste de transacción, oportunidad perdida. *Menos
  excepciones no cuenta si exige más capital/cobertura.*

## Diseño temporal y controles (ambos gates)
- Walk-forward expansivo; corte out-of-time; purge/embargo ≥ 10 sesiones.
- Umbrales/presupuesto/ratios **en train/validación**, congelados en test. **No**
  igualar presupuesto con cuantiles del test.
- IC **pareado por bloques** temporales; resultados por fold/año; sensibilidad a
  episodios de estrés. **2026 = caso de estudio, no confirmación independiente.**
- Manifiesto con hashes de panel/features/forecasts/política; universo y cobertura
  declarados (no mezclar `brent_fred_daily.csv` con el panel extendido sin decirlo).

## Checklist de sesgos (vinculante)
- [ ] as-of (señal ≤ t, forward t+1..t+10) · [ ] umbrales solo train ·
  [ ] featurizador de supervivencia solo train · [ ] batir a solo-vol y al nulo ·
  [ ] IC por bloques · [ ] 2026 caso de estudio · [ ] Gate 2 etiquetado *simulado* ·
  [ ] manifiesto con hashes.

## Fuentes de calibración
- Reuters «Factbox: How airlines have hedged against fuel price increases» (2026).
- Wikipedia, «Fuel hedging» (ratios/horizontes).
- CME Group, «Introduction to European Crude» (liquidez/spread Brent).
- Buehler, Gonon, Teichmann, Wood, «Deep Hedging», arXiv:1802.03042 (2018).
