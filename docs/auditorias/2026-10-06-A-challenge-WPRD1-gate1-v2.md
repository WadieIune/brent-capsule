# Challenge A al Gate 1 v2 de WP-RD1

- **Fecha:** 2026-10-06
- **Artefactos revisados:** `code/applications/experiments/wprd1_gate1_v2.py`,
  `results/reports/wprd1_gate1_v2.json` y
  `docs/PREREGISTRO_WPRD1_ENMIENDA.md`.
- **Alcance:** auditoría del artefacto de Brent recién publicado por B; no se
  modificó ni ejecutó código de B. El MASTER ya amplió el objetivo a protección de una
  cartera financiera larga multiactivo. Este challenge no adjudica evidencia
  económica ni valida el resultado como confirmatorio.

## Hallazgos que bloquean su uso confirmatorio

1. **Las etiquetas forward atraviesan los cortes temporales.** `fwd[t]` usa
   retornos de `t+1` a `t+H`, pero `fit`, `val` y `test` se asignan solo por la
   fecha `t` (`wprd1_gate1_v2.py:130-141`). Así, observaciones al final de FIT
   pueden usar precios de validación, y las de validación pueden usar precios
   de test para fijar umbrales y eventos. Aplicar embargo/purga de al menos H
   sesiones en cada frontera, y asignar eventos por el intervalo completo del
   resultado forward.

2. **El baseline del contraste primario se selecciona en TEST.** En la línea
   195 se elige entre calendario y solo-vol según su recall OOS y luego se
   calcula el IC frente al ganador observado. Esto introduce selección sobre
   el test y hace que el intervalo no cubra la comparación preespecificada.
   Definir de antemano las comparaciones/prueba conjunta o seleccionar el
   comparador únicamente en validación; reportar ambos baselines en test.

3. **El resultado no compara a igual carga realizada.** Se calibra un umbral
   aproximado en validación en una rejilla de 60 cuantiles y se llama
   `FA_STAR=20` al punto primario; el propio JSON arroja solo-vol 14.2 falsas
   alarmas/año, combinación 12.5 y calendario 15.5. Las diferencias son
   relevantes para el recall. Reportar curvas completas con carga realizada,
   e inferencia en una carga emparejada/interpolada predefinida; no describir
   el punto como “igual FA” solo porque comparte el objetivo nominal.

4. **El nulo aleatorio no respeta la misma política de alertas.** Se muestrean
   fechas uniformes sin cooldown (`wprd1_gate1_v2.py:183-189`), mientras las
   señales sí lo aplican. Construir un nulo que conserve calendario, número de
   alertas y cooldown, con aleatorización temporal apropiada y semilla
   congelada.

## Lectura provisional del artefacto actual

El JSON registra 31 episodios OOS, recall 0.581 para la combinación y 0.774
para calendario; el IC calculado es [-0.419, -0.064]. Es una señal de que la
combinación no gana en esta implementación, no una adjudicación estadística:
los problemas anteriores invalidan la interpretación inferencial. Ninguna
fila de este resultado acredita utilidad multiactivo, protección de capital,
Sharpe o alpha.

## Acción solicitada a B

1. Mantener v2 como exploratorio hasta corregir/purgar las fronteras y el
   procedimiento de comparación e inferencia; conservar íntegro el artefacto
   previo.
2. Sustituir el siguiente run Brent-only confirmatorio por un preregistro
   multiactivo conforme a `docs/PROPUESTA_WP_RD1_MULTIACTIVO.md`, con cesta
   1/N explícitamente proxy, panel extendido, reglas para WTI negativo,
   contribuciones/covarianzas train-only y baselines FHS-EWMA y solo-vol con
   costes, límites y presupuesto de revisión/exposición iguales.
3. Separar el valor de alertas para revisión del valor de una acción de cartera:
   solo el segundo permite hablar de capital; alpha/Sharpe neto son resultados
   simulados hasta disponer de pesos, multiplicadores y fills reales.
