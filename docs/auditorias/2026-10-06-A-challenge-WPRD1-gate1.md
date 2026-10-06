# Challenge A · WP-RD1 Gate 1 y enmienda de métrica

- **Fecha:** 2026-10-06
- **Revisión:** `code/applications/experiments/wprd1_gate1.py`,
  `docs/PREREGISTRO_WPRD1.md` y el resultado publicado.
- **Estado:** Gate 1 ejecutado, pero **no adjudica valor para el Risk Director**
  hasta fijar el signo de riesgo y una evaluación por episodio. No recomiendo
  reejecutar con AUC-PR diaria como única métrica primaria.

## Hallazgos

1. **El evento adverso no corresponde al consumidor de crudo del Gate 2.**
   `theta` es el percentil 10 de retornos Brent a 10 sesiones y `forward_event`
   marca `fwd < theta`: son caídas del precio. Eso es adverso para una posición
   larga en Brent, pero normalmente favorable para un comprador físico de
   crudo. El Gate 2 describe precisamente a ese comprador. El objetivo debe
   declarar la perspectiva y el signo antes de evaluar una política; si se
   mantiene el retorno bajo como objetivo, el alcance será riesgo de una
   posición financiera larga, no coste de aprovisionamiento.

2. **La ventaja del calendario no prueba por sí sola que la métrica esté
   sesgada.** Con 20 revisiones/año, el intervalo es aproximadamente 13
   sesiones. Una ventana previa al evento de 10 sesiones da una probabilidad
   geométrica cercana a 10/13 = 0,77 de que una revisión periódica caiga dentro
   de la ventana. La captura observada de 0,804 es compatible con este efecto.
   Si el producto puede revisar periódicamente, calendario es un baseline
   operativo válido y ganar es parte del objetivo. El resultado sí revela que
   las alertas agrupadas pueden cubrir menos episodios con la misma carga.

3. **El test no alcanzó igual carga realizada.** Los umbrales se fijaron en
   train, pero en test la combinación tuvo 17,4 revisiones/año, calendario 19,3
   y solo-vol 23,8. No debe describirse el contraste observado como captura a
   presupuesto igualado. Mantener umbrales causales congelados y reportar la
   curva coste-cobertura completa; cualquier punto operativo común debe
   seleccionarse solo en validación.

4. **AUC-PR diaria no resuelve por sí sola el problema de decisión.** Las
   etiquetas se derivan de retornos forward solapados a 10 sesiones; varias
   fechas pueden describir el mismo episodio. AUC-PR sobre días puede ponderar
   episodios largos varias veces y no representa una revisión accionable. Si se
   adopta como métrica de ranking, usar un score por episodio y ventanas de
   control emparejadas, con inferencia por bloques temporales. Mantenerla como
   métrica secundaria hasta congelar esa construcción.

## Diseño que propongo para la enmienda

- Fijar primero la cartera objetivo y el sentido de pérdida: consumidor físico
  (subida de coste Brent/FX) o posición financiera larga (caída de P&L Brent).
- Construir episodios no solapados del evento a partir del umbral fijado en
  train; unir excedencias cercanas mediante una regla de separación de 10
  sesiones congelada antes del nuevo run.
- Para la política de revisión, reportar captura de episodios, falsas alarmas,
  lead time y revisiones por año. Mantener calendario cada 13 sesiones como
  baseline válido; añadir comparación de curva coste-cobertura en puntos
  elegidos en validación. Desduplicar alertas con una regla fija de cooldown.
- Para medir targeting, calcular precisión-recall a nivel de episodio (un
  score por evento/ventana), no tratar cada día de los retornos forward
  solapados como un caso independiente. Usar bootstrap pareado de bloques de
  fechas con longitud al menos igual al horizonte de 10 sesiones; informar el
  número efectivo de episodios.
- Comparar vol, régimen, supervivencia y sus ablaciones con exactamente las
  mismas fechas, horizonte y perspectiva de pérdida. La supervivencia del canal
  predice persistencia geométrica; su valor de riesgo depende de que añada
  información sobre eventos adversos, no se presume por su C-index.
- Registrar como resultado exploratorio el gate ya corrido. Congelar esta
  enmienda antes de la única reevaluación confirmatoria.

## Lectura del valor añadido hoy

La supervivencia de canal tiene evidencia de discriminación de duración
(C-index publicado 0,664), pero eso aún no equivale a reducir pérdidas ni a
mejorar el Sharpe. En el Gate 1 actual, combinación y solo-vol tienen la misma
precisión (0,238), mientras supervivencia aislada queda en 0,023; estos datos
son exploratorios porque el evento está orientado a caídas y la asignación de
alertas está en revisión. No afirmar ahorro, alpha o Sharpe a partir de este
resultado. Gate 2 sigue siendo simulado porque no hay exposiciones ni P&L reales
de cartera en el repo.

## Solicitud a B

Confirmar la perspectiva de cartera y el signo del evento; decidir si acepta la
evaluación por episodios con calendario como baseline válido y AUC-PR diaria
solo como secundaria; y devolver la enmienda para congelarla antes de otra
ejecución. No reescribo el preregistro original ni reejecuto el experimento.
