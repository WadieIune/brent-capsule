# Challenge B · calibración por clase y discriminación DQ

- **Fecha:** 2026-10-16
- **Estado:** 🟠 evidencia prometedora, alcance degradado; pendiente de respuesta A
- **Artefactos revisados:** `dq_discrimination_vs_calibration.py`,
  `dq_rolling_gate.py`, `dq_representation_stack.py`,
  `dq_cnn1d_supervised.py`, sus tests y summaries asociados.

## Veredicto

Se acepta como arquitectura de investigación separar **controles/detectores**,
**combinador** y **calibrador**, y distinguir controles semánticos deterministas
de scores estadísticos continuos. No se acepta todavía la afirmación de que la
IA aporte superioridad operacional ni que la recalibración rodante por clase
resuelva el gate. Los resultados de discriminación a FPR igualada son
diagnósticos con umbral oráculo; la evaluación operativa sigue por encima del
presupuesto nominal y la calibración no tiene resolución efectiva demostrada.

## Hallazgos del challenge

1. **El FPR emparejado es oráculo y está bien rotulado como no desplegable.**
   `dq_discrimination_vs_calibration.py` fija el umbral en el limpio de test.
   Esto permite comparar la ordenación de defectos con FPR común, pero no
   demuestra que un despliegue pueda conseguir ese punto. La ventaja del
   combinador XGBoost (recall medio 0,613 frente a 0,440 CNN y 0,119 3σ) queda
   como evidencia de capacidad discriminante en el protocolo sintético, no como
   resultado operativo.

2. **La prueba LOFO no equivale a test por activo/fuente/tiempo independiente.**
   Se reservan familias de defectos, lo cual es útil, pero los scores de umbral
   siguen calibrándose con el limpio del test y los activos base siguen siendo
   los mismos. La generalización a series externas permanece abierta.

3. **La resolución de 236 ventanas está sobrecontada.** El pipeline usa
   ventanas de 20 sesiones con stride 5. En 236 scores consecutivos hay solo
   59 ventanas de una fase no solapada (y dependencia residual de mercado).
   Por tanto, `1/236 = 0,0042` no es una resolución inferencial defendible para
   el umbral por control `0,05/7 = 0,00714`. El límite conservador basado en
   59 puntos es `1/59 = 0,0169`; aun antes de dependencia serial, el share está
   por debajo de esa granularidad. La prueba unitaria que compara `1/n` con el
   share verifica aritmética de ventanas, no tamaño muestral efectivo.

4. **El gate mejora modestamente, pero incumple el objetivo.** En las métricas
   del summary revisado, el gate congelado uniforme da FPR OOS 0,129 y recall
   0,629; el rodante por clase da FPR 0,116 y recall 0,646. La diferencia debe
   reportarse descriptivamente: 124 ventanas test solapadas no son 124 ensayos
   independientes, y tres semillas no reparan esa dependencia.

5. **“Determinista no consume FPR” es condicional al contrato, no una
   propiedad universal.** Vintage y retícula pueden tener score constante en
   este panel limpio, pero un tick/metadata incorrecto, cambio legítimo de
   convención o revisión de snapshot puede producir alertas. Su tasa debe
   medirse por tipología y contrato en una población independiente; la
   semántica evita calibrar una constante por cuantil, no garantiza FPR cero en
   producción.

6. **La contaminación del calibrador necesita challenge más amplio.** La prueba
   de `dq_discrimination_vs_calibration.py` contamina 10% con una única
   familia/modo (`keys[0]`, `stale|restated`). No basta para afirmar robustez
   ante mezcla real de defectos, cambios de régimen o cambios de fuente.

## Acción solicitada a A

- Mantener la conclusión como **provisional**: “hay señal discriminante
  complementaria; la transferencia de calibración es el cuello de botella
  observado en este panel”, no “la IA supera el estado del arte”.
- Repetir el análisis de calibración con bloques temporales/no solapados o
  inferencia por bloques; reportar intervalos por episodio y sensibilidad a las
  cuatro fases del stride 5.
- Comparar: calibración marginal por score, calibración directa de la unión,
  subset de controles seleccionado solo en validación y reglas semánticas con
  contratos perturbados. No asumir de antemano que repartir α entre siete es
  óptimo.
- Ampliar contaminación a familias y direcciones múltiples con inyecciones
  pareadas y purga; no usar el bloque evaluado para fijar su propio umbral.
- Mantener separadas las cifras oráculo de discriminación de los resultados
  desplegables. El siguiente gate debe ser un test externo por activo/fuente y
  periodo, con adjudicación de incidencias y carga de revisión real.

## Respuesta supervisora

**Decisión:** aprobar la separación detector–combinador–calibrador como diseño
del framework; degradar los claims de mejora de gate y ventaja general de IA a
exploratorios hasta superar los puntos anteriores. El objetivo de la próxima
iteración es identificar un calibrador block-aware que mantenga una carga
operativa defendible, no forzar el 5% nominal con resolución insuficiente.
