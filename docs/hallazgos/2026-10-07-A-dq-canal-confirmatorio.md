# DQ en representación de canal: prueba confirmatoria inicial

- **Fecha:** 2026-10-07
- **Estado:** corrida reproducible completada; evidencia inicial, no promoción a producción.
- **Código:** `code/applications/experiments/dq_channel_confirmatory.py`
- **Artefacto:** `results/reports/dq_channel_confirmatory/summary.json`
- **Datos:** `data/panel_extendido_2026-09-09.csv` y `data/brent_fred_daily.csv`.

## Diseño y cierre de brechas

Se reemplazaron las 124 ventanas solapadas por ventanas de 20 sesiones con
stride 20. Split temporal: train hasta 2018-12-31 (140 ventanas), validación
limpia 2019-01-01–2020-08-20 (19), test desde 2020-09-21 hasta el final
disponible (71). Los umbrales se fijan solo con validación limpia y quedan
congelados en test. Las 7 familias sintéticas se inyectan en precios crudos;
se recalculan normalización y scores. XGBoost DQ se entrena con tres familias
y reserva cuatro como holdout.

La serie completa de Brent se vuelve a pasar por la extracción existente de
episodios bajo cada corrupción. Un XGB-AFT único, ajustado con episodios limpios
anteriores/al 2018-12-31 y censura administrativa en ese corte, queda congelado
para todos los escenarios. Se mide cambio de fechas/volumen de episodios y
cambio en `P(T>10)` para episodios con fecha de inicio coincidente. Esto mide
distorsión de la representación y del modelo congelado; **no** es una métrica de
detección DQ ni prueba de capacidad predictiva bajo corrupción.

El impacto downstream usa cartera proxy equiponderada BRENT/COPPER/EUROSTOXX50/
GOLD/SP500, VaR histórico 99% con ventana 250 sesiones y el mismo calendario de
estrés (1 de cada 4 ventanas test). Excepciones se contrastan contra retornos
limpios. Sin posiciones/notional no se informa capital EUR ni capital
regulatorio.

## Resultados observados

- FPR test limpio: CNN1D 0/71; XGBoost DQ 0/71; controles de canal:
  coherencia 0/71, ruptura 6/71 (8.45%), geometría 9/71 (12.68%) y déficit de
  oscilación 5/71 (7.04%). Rejilla, 1−R² y 3σ: 0/71.
- IC Clopper–Pearson exacto 95% para 0/71: [0%, 5.06%]. Ruptura 6/71:
  [3.16%, 17.49%]; geometría 9/71: [5.96%, 22.70%]; oscilación 5/71:
  [2.33%, 15.67%]. Los intervalos son amplios y se solapan: no permiten
  ordenar detectores por FPR con precisión.
- XGBoost DQ: recall por familia `stale` 53.5%, salto reversible 54.9%,
  desacople 12.7%, desfase calendario 2.8%, weekly fill 9.9%, cambio de fuente
  11.3%, cuantización 0%. Esos recalls no demuestran ventaja: la CNN obtiene
  0% para la mayoría de familias y los controles específicos dominan en varios
  defectos (p. ej., rejilla 100% en quantize, sin alertas limpias en este test).
- El AFT parte de 91 episodios test limpios. Frente al limpio, el cambio de
  fuente produce 55 inicios añadidos y 55 eliminados; stale, 58 y 54. En
  inicios coincidentes, el cambio absoluto medio de `P(T>10)` va de 0.0045
  (quantize) a 0.0287 (source switch). La corrupción puede alterar materialmente
  qué episodios existen, no solo el score de supervivencia.
- El VaR proxy medio cambia entre −2.10% (stale), +8.29% (salto reversible),
  +2.75% (desacople), +1.14% (lag), −0.18% (weekly fill), +2.06% (cambio de
  fuente) y −0.09% (quantize). Las excepciones contra retornos limpios van de
  13 a 20, frente a 16 en el histórico limpio. El signo depende del defecto:
  una serie sucia puede inflar o reducir riesgo estimado.

## Lectura y límites

Esto cierra las brechas de protocolo señaladas en el piloto: test no solapado,
calibración separada, XGBoost DQ, recálculo de episodios/supervivencia y un
impacto explícito en riesgo proxy. **No confirma que CNN/XGBoost mejoren el
estado del arte.** Solo hay 19 ejemplos limpios para calibrar cada umbral al 5%;
con el rank finito empleado, no se permiten falsas alarmas en validación, así
que el umbral resulta conservador. En test hay 71 observaciones, por lo que 0/71
no implica FPR poblacional cero. El IC exacto 95% de 0/71 llega a 5.06%, casi
todo el presupuesto nominal; hacen falta más validación y evaluación
multi-activo/multi-periodo.

La mezcla de múltiples ventanas estresadas para el proxy de VaR es una prueba
de sensibilidad sintética, no P&L de una cartera mantenida ni capital
regulatorio. El AFT es un único ajuste, el extractor conserva la definición
existente y los defectos son sintéticos. Antes de una afirmación final hay que
desafiar el diseño con B, ampliar validación limpia y añadir activos/curvas.
Resultado recomendado para el paper por ahora:
**la calidad del dato sí puede cambiar el inventario de episodios del canal y
la estimación de riesgo; no se ha establecido que IA detecte esos cambios con
mejor FPR/recall que los controles específicos.**
