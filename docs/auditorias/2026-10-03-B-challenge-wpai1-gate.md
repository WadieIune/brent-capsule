# Challenge B · WP-AI1 gate de horizonte adaptativo

- **Fecha:** 2026-10-03
- **Objeto:** `code/applications/experiments/_wpai1_gate/wpai1_gate.py`
- **Estado:** el resultado publicado queda **provisional**; este gate no adjudica
  la hipótesis operativa de WP-AI1.

## Hallazgos

1. **Desfase de una sesión en la etiqueta.** `rets[j]` es el retorno de
   `prices[j]` a `prices[j+1]`, pero `reg_r = reg.to_numpy()[1:]` condiciona ese
   retorno por el régimen calculado al cierre de `prices[j+1]`. Además,
   `var_ratio` acumula retornos forward que arrancan en `j`. Para una señal
   disponible al inicio del horizonte, la etiqueta debe corresponder a
   `reg[j]` (`reg[:-1]`), con tratamiento explícito de los valores sin etiqueta.
   La implementación actual usa información del cierre final para clasificar
   retornos que ya incluyen ese cierre.

2. **Nulo no conserva la dependencia temporal.** La permutación aleatoria de
   etiquetas individuales destruye la agrupación de episodios y presupone
   intercambiabilidad. Las etiquetas de canal son persistentes; por tanto, los
   p-valores reportados no son una prueba calibrada frente a un nulo temporal
   apropiado. Usar bloques o permutar episodios requeriría fijar antes el
   esquema, tamaño de bloque y estadístico.

3. **El estimando no es el de la propuesta WP-AI1.** El script compara
   `VR(h)` entre etiquetas de régimen. No consume predicciones de supervivencia,
   no elige un horizonte sesión a sesión y no evalúa cobertura, capital,
   Kupiec/Christoffersen, nulo de horizonte ni baseline solo-vol. El resultado
   puede servir como diagnóstico exploratorio de dependencia, pero no como
   backtest del binomio capital-cobertura descrito en
   `docs/PROPUESTA_CAPA_IA_MOTOR_CALCULO.md`.

## Veredicto supervisor

El gate observado no muestra una diferencia significativa bajo su permutación,
pero los defectos anteriores impiden interpretar sus p-valores como evidencia
confirmatoria. No queda demostrado que el horizonte adaptativo falle, ni que
funcione. El lenguaje del hallazgo debe limitarse a: **este diagnóstico
exploratorio no encontró una diferencia detectable y requiere corrección de
alineación/nulo**. No usarlo para cerrar la vía de parametrización en el paper.

La ejecución ya realizada se conserva como exploratoria; no se modifica el
pre-registro histórico para aparentar que el diseño fue fijado antes. Antes de
cualquier nueva ejecución confirmatoria, congelar en un addendum la señal
as-of, la política de selección de horizonte, la métrica primaria capital-
cobertura, los comparadores (fijo, solo-vol y nulo de igual media), el esquema
temporal de inferencia y los umbrales de decisión. El harness debe evaluar la
hipótesis operativa completa, no solo `VR(h)`.

## Acción solicitada a A

Revisar el desfase temporal y la inferencia del nulo; proponer una corrección
reproducible y devolver el diseño antes de correrla. Mantener separados el
diagnóstico exploratorio ya publicado y cualquier evaluación confirmatoria.
