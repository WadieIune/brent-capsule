# Propuesta de investigación — DQ en representación de canal

- **Fecha:** 2026-10-07
- **Objetivo del paper:** mejorar la confianza y exactitud de series históricas
  de precios con controles DQ complementarios. No se busca demostrar alpha,
  rentabilidad ni que el canal prediga retornos.
- **Estado:** primera corrida confirmatoria inicial completada; no se promueve a producción ni se afirma superioridad de IA.

## Tesis

El dato puede parecer correcto en precio/retorno y, sin embargo, alterar la
estructura inferida por un canal: régimen, pendiente, anchura, residuo,
posición, límites y duración del episodio. Esa estructura es una segunda
representación del mismo historial y puede revelar inconsistencias,
especialmente al contrastar activos que deberían co-moverse. CNN y XGBoost son
candidatos para aprender patrones DQ en esa representación; no se presuponen
mejores que reglas, controles cross-asset ni el benchmark actual.

Canal y supervivencia contextualizan los rendimientos observados en activos
correlacionados; no son recomendación de posición, modelo de alpha ni promesa de
mejora de P&L.

## Hipótesis falsable

En datos con etiqueta conocida (series observadas limpias con defectos
inyectados), una representación de canal calculada estrictamente *as-of* añade
recall/precisión frente al conjunto de controles baratos de precio, retorno,
TRIM y cross-asset, a una FPR común. La mejora debe sostenerse en test temporal,
familias no vistas y cambios legítimos de régimen.

Si el canal solo amplifica la misma señal de 3σ o residuo cross-asset, o la
mejora desaparece con FPR emparejada, no se reclama valor incremental de deep
learning.

## Evidencia exploratoria inicial

Hay un prototipo exploratorio en `code/applications/experiments/dq_channel_representation.py`
y un reporte en `results/reports/dq_channel_representation/summary.json`. A FPR
nominal emparejada de 5% sobre 124 ventanas de test, los controles de canal son
complementarios: coherencia de posición-en-banda da recall 1,00 en `stale` y
0,58 en `decoupling`; déficit de oscilación da 1,00 en `stale` y 0,99 en
`weekly_ffill`; residuo cross-asset en retornos normalizados logra 0,90 en
`decoupling` y 0,85 en `lag1_calendar`; rejilla de precio alcanza 1,00 en
`quantize`. CNN1D logra 0,93 en `decoupling`, pero solo 0,41 en `source_switch`.
Esto apoya investigar una matriz de representaciones complementarias, no la
afirmación de que una red o el canal dominen.

Ese piloto no es evidencia confirmatoria: tenía ventanas solapadas y umbrales
estimados sobre el mismo test limpio. Sus proxies de canal tampoco recalculaban
episodios/supervivencia.

## Corrida confirmatoria inicial

El protocolo revisado y el resultado están en
`docs/hallazgos/2026-10-07-A-dq-canal-confirmatorio.md`; código en
`code/applications/experiments/dq_channel_confirmatory.py` y números completos
en `results/reports/dq_channel_confirmatory/summary.json`. Se usan ventanas
disjuntas 20/20, umbrales calibrados en validación limpia independiente, CNN1D,
XGBoost DQ (tres familias conocidas y cuatro holdout), recálculo de episodios
Brent y predicciones de un XGB-AFT limpio congelado, más VaR histórico 99% como
proxy equiponderado de cinco activos.

La validación solo contiene 19 ventanas limpias y test 71: FPR test es 0/71
para CNN y XGBoost, pero excede el 5% nominal en controles de ruptura de banda
(8.45%), geometría (12.68%) y oscilación (7.04%). La CNN no detecta la mayoría
de familias y XGBoost apenas transfiere a las familias reservadas; los
controles específicos ganan en familias concretas. El XGB-AFT encuentra cambios
de episodios (p. ej. cambio de fuente: +55/−55 inicios) y el VaR proxy oscila
entre −2.10% y +8.29% según defecto, pero no es impacto en capital en euros.
Los IC Clopper–Pearson 95% están en el JSON; para 0/71, el límite superior es
5.06%, así que tampoco se descarta que la FPR real supere el 5% nominal.

**Conclusión provisional:** queda demostrado que defectos sintéticos pueden
alterar episodios del canal y riesgo estimado; no que CNN/XGBoost sean mejores
detectores. La validación pequeña, intervalos amplios, un único panel y una
sola cartera proxy impiden una conclusión confirmatoria fuerte. Ver el
hallazgo para las cifras completas y límites.

## Representaciones y controles

1. **Precio/retorno:** 3σ causal, límites/positividad, TRIM (incluidos 20
   retornos cero), salto/reversión y rejilla/tick cuando aplique.
2. **Cross-asset:** regresión/hedge ratio estimado en train y residuo
   contemporáneo; `1-R²` de ventana donde corresponda. Pares fijados con train
   y metadatos económicos, no con test.
3. **Canal:** residuos proyectados hacia delante, z-residuo, slope normalizada,
   R², anchura, posición, turns/curvatura y edad. Cada feature usa solo precios
   disponibles en t; supervivencia no se usa como etiqueta DQ.
4. **Aprendizaje:** CNN 1D sobre secuencia de residuo/anchura/posición y/o
   canales multiactivo; XGBoost sobre features explícitas de DQ, precio, par,
   canal, TRIM y procedencia. La CNN productiva de canales y el XGBoost-AFT de
   supervivencia no se reutilizan como detectores DQ sin entrenamiento y
   evaluación nuevos.

## Etiquetas y splits

Inyectar sobre precio crudo y recomputar retornos, canales y supervivencia en
cada serie corrupta:

- spikes aislados y spikes que revierten;
- stale/repetición y huecos/rellenos de calendario;
- offset o cambio de escala de proveedor;
- ajuste histórico/back-adjustment y cambio de tick/split cuando haya vintage;
- decoplamiento de un miembro de un par hedgeado;
- cambios de régimen reales, movimientos comunes y rupturas legítimas como
  controles negativos (no etiquetarlos automáticamente como corrupción).

Separar por tiempo, activo/familia y fuente cuando haya datos suficientes.
Inyecciones/parametrización se generan después del split. Escala, pares,
umbrales, canal y selección de modelos son train-only; calibración en validación
limpia separada; test incluye defectos OOD y datos limpios de estrés. La
observación t nunca entra en su propia proyección. Intervalos por bloques y
bootstrap por activo/episodio, no IID.

## Métricas y decisión

- Recall, precisión, AUC-PR y retraso por familia.
- FPR por activo-día/curva-fecha a presupuesto común y FPR realizada OOS con IC.
- Si se localiza: error de índice e IoU en tiempo/tenor.
- **Fidelidad de representación:** cambios falsos de canal, variación de
  slope/anchura/posición y error de supervivencia entre serie limpia y
  corrupta; una diferencia no demuestra por sí sola detección útil.
- **Impacto DQ downstream, no alpha:** cambio inducido en retornos,
  covarianzas/contribuciones de riesgo, volatilidad, VaR/ES y cobertura frente
  al historial limpio de referencia. No borrar/imputar automáticamente en
  producción.

Promover CNN/XGBoost solo si añaden cobertura en una familia no resuelta por los
controles baratos, respetan FPR y sobreviven al test temporal/familias. Si gana
una regla sencilla, esa regla es el hallazgo. El VAE solo entra tras validar
marginales, colas, ACF, estados y duración de regímenes; el probado hasta ahora
comprimió colas y no justifica augmentación.

## Secuencia de trabajo

1. Congelar el benchmark de B (TRIM + controles cross-asset) y definir pares.
2. Añadir vista de canal al arnés de inyección: medir cambios de régimen,
   features y supervivencia *as-of*.
3. Probar reglas baratas en espacio de canal y declarar sus espacios nulos.
4. Entrenar/evaluar CNN y XGBoost en exactamente esos splits y cargas FPR.
5. Medir propagación del defecto a métricas de riesgo y cerrar el paper con una
   matriz de coberturas, resultados positivos/negativos y limitaciones.

No modificar el flujo productivo hasta que este gate pase auditoría y challenge
cruzado.
