# Risk Director: contraste CNN con procedencia regenerada

Fecha: 2026-09-10. Estado: exploratorio provisional, pendiente de auditoría cruzada.
Conclusión: el criterio diagnóstico fijado antes de evaluar CNN **no se cumple**.
El resultado se obtuvo inicialmente en local. La coordinación posterior con A se
registra en `2026-09-10-B-plan-CNN-info-Risk-Director.md`.

## Qué se ha ejecutado

Se han generado 6.722 imágenes de ventanas de 32 cierres observados, usando las
funciones originales de codificación de `brent_pattern_system.image_encoding` y
etiquetado de `patterns`, umbral 0.30. No se rellenan días ausentes ni se normaliza
con datos futuros. Son las mismas fechas/precios que el experimento de riesgo.

Se carga explícitamente el checkpoint local `efficientnet_b1-c27df63c.pth` en
EfficientNet-B1 de torchvision, con `load_state_dict(strict=True)`, extractor
congelado y modo evaluación. No se usa el cargador con fallback de `torch_model`.
Ese cargador permite pasar a pesos aleatorios si falla la carga preentrenada;
por tanto, el nombre del backbone no basta para certificar el modelo original.
No se afirma haber probado que el artefacto anterior usase pesos aleatorios.

Para cada año 2005–2026 se entrenan dos regresiones logísticas independientes,
C=1 y ponderación balanceada, exclusivamente sobre etiquetas anteriores al
inicio de la primera ventana predicha. Hay separación de 31 observaciones para
que las imágenes de entrenamiento y del nuevo bloque no se solapen. Se producen
5.438 pares de scores; no se impone suma uno ni se usa argmax. La ponderación
balanceada implica que no deben interpretarse como probabilidades calibradas de
un evento real sin validación adicional. Heads, pesos, imágenes, embeddings,
datos y transformaciones quedan identificados por hash.

El backbone ImageNet y el diseño se eligen retrospectivamente. La prueba acredita
separación temporal del ajuste sobre Brent; **no** acredita que este modelo
estuviese disponible históricamente en 2005. Es una regeneración trazable de la
arquitectura, no una certificación retrospectiva del backbone del artefacto viejo.

## Contrato y comparación

Antes de ejecutar el contraste de riesgo se guardó `protocol.json`. Objetivo:
media de los diez retornos logarítmicos cuadrados estrictamente futuros. Es un
segundo momento realizado: no se presenta como ES, capital o varianza del retorno
agregado a diez días. Las diez sesiones son intervalos de observación del CSV,
no un calendario bursátil verificado.

Cuatro variantes sobre las mismas fechas y con la misma familia base:

1. Base EWMA/log-HAR.
2. Base + geometría OLS de 32 cierres.
3. Base + dos scores CNN.
4. Base + geometría + dos scores CNN.

Familia EWMA/log-HAR elegida exclusivamente en las 252 observaciones de validación
anteriores a cada año. Purga de etiquetas antes de validación y test; ajuste del
corrector y escalado solo con datos anteriores. Las probabilidades del periodo
de entrenamiento del corrector también proceden del cross-fitting anual, nunca
de cabezas que hayan visto su futuro. Se mantienen L2=0.01 y el resto de decisiones
del piloto. No se añade ni evalúa GARCH en esta entrega.

Al exigir disponibilidad común de scores, la historia de entrenamiento del motor
de riesgo comienza en 2005, frente a 2000 en el piloto sin CNN. Se recalculan todos
los controles sobre esa misma historia: los resultados no deben restarse a los
del piloto anterior. El test común contiene 2.651 pronósticos, de 2016-01-04 a
2026-06-15. El objetivo del último pronóstico usa los diez cierres siguientes.

## Resultado

Delta QLIKE = pérdida de variante ampliada menos pérdida del comparador.
Un valor negativo favorece añadir las variables.

| Contraste | Delta medio | IC 97.5%, bloques de 20 |
|---|---:|---:|
| Base+CNN frente a base | +0.007189 | [-0.000688, +0.015696] |
| Base+geometría+CNN frente a base+geometría | -0.001481 | [-0.009432, +0.005297] |
| Base+geometría frente a base (descriptivo) | +0.007586 | [-0.016556, +0.034975] |

Los intervalos también incluyen cero con bloques de 10 y 60 observaciones.
Se usan 2.000 réplicas de bloques móviles y semilla 1729. Los intervalos de
97.5% aplican Bonferroni a los dos contrastes CNN principales, por longitud de
bloque; el tercer contraste es descriptivo. Son intervalos condicionados a los
pronósticos ajustados y no corrigen la búsqueda histórica del proyecto.

El criterio local exigía mejora de al menos 0.01 unidades QLIKE y límite superior
negativo en ambos contrastes CNN para las tres longitudes de bloque. **No se
cumple**. Ese umbral es diagnóstico, no una materialidad económica estimada ni
un criterio regulatorio. No se ha validado un despliegue.

CNN frente a base mejora solo en 2020 y 2024 (2 de 11 años, 2026 parcial).
La pequeña ventaja media al añadir CNN a geometría tampoco es estable por año.
No hay evidencia suficiente de utilidad incremental en esta configuración. Un
intervalo que contiene cero no prueba equivalencia ni imposibilidad universal.
La capacidad de reconocer etiquetas de la propia ventana es otra pregunta.

## Integridad y reproducibilidad

Catorce pruebas específicas superadas: objetivo exactamente futuro; invariancia
de features al perturbar el futuro; purga de diez etiquetas; no lectura de los
objetivos de test; scores independientes; rechazo de violaciones temporales,
probabilidades inválidas y modificaciones de datos o cabezas.
Suite completa de aplicaciones: **19/19 pruebas superadas** en 36.36 segundos.

Scripts nuevos, propiedad B:

- `code/applications/experiments/regime_cnn_causal.py`: prepare/extract/heads.
- `code/applications/experiments/regime_cnn_forward_variance.py`: contrato, validación y contraste.
- `code/applications/test/test_regime_cnn_forward_variance.py`: pruebas del puente.

`regime_forward_variance.py` admite ahora columnas adicionales opcionales; el
camino anterior conserva su comportamiento. Los artefactos pesados regenerables
permanecen en `results/regime_cnn_causal/`. Los entregables ligeros se copian a
`results/reports/regime_cnn_forward_variance/` para revisión y versionado.

Se usaron dos entornos locales ya existentes: el estadístico con numpy/pandas/
scipy/sklearn y el entorno torch con PyTorch/torchvision. No se instalaron paquetes.
Los paths siguientes se proporcionan por el usuario/entorno y no están fijados
en el código:

```bash
# Desde la raíz de track-b; STAT_PY y TORCH_PY apuntan a los entornos respectivos.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
"$STAT_PY" code/applications/experiments/regime_cnn_causal.py prepare --prices data/brent_fred_daily.csv --out results/regime_cnn_causal
CUBLAS_WORKSPACE_CONFIG=:4096:8 "$TORCH_PY" code/applications/experiments/regime_cnn_causal.py extract --weights "$CNN_WEIGHTS" --out results/regime_cnn_causal
"$STAT_PY" code/applications/experiments/regime_cnn_causal.py heads --out results/regime_cnn_causal
# Solo en directorio nuevo: el comando rechaza sobrescribir un contrato existente.
"$STAT_PY" code/applications/experiments/regime_cnn_forward_variance.py --out results/regime_cnn_forward_variance --freeze-contract
"$STAT_PY" code/applications/experiments/regime_cnn_forward_variance.py --prices data/brent_fred_daily.csv --scores results/regime_cnn_causal/causal_predictions.csv --provenance results/regime_cnn_causal/provenance.json --out results/regime_cnn_forward_variance
"$STAT_PY" -m pytest code/applications/test/test_regime_forward_variance.py code/applications/test/test_regime_cnn_forward_variance.py -q
```

## Para la revisión de A

Revisar el contrato temporal completo, la carga explícita del checkpoint y la
comparación sobre historia común; comprobar que no se atribuye el cambio frente
al piloto a CNN cuando también cambia el inicio de entrenamiento. Desafiar el
supuesto de utilidad de las etiquetas débiles, el baseline elegido, la suficiencia
de los controles de volatilidad y la inferencia por bloques. Mantener este
resultado fuera de afirmaciones firmes del paper hasta esa revisión. No buscar
umbrales o modelos adicionales en este mismo test para rescatar el resultado.
