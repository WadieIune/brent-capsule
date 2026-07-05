# Justificación de las métricas de evaluación — BRENT Pattern System

> Versión resumida del **Anexo B** de `docs/CCN_BRENT_canal/main.tex` (allí con
> formulación matemática y bibliografía completa). Pensado para responder a la
> primera pregunta de un comité de publicación: *¿por qué estas métricas?*

El criterio rector es doble: (i) el problema es **clasificación con desbalance
fuerte y umbral operativo no fijado a priori**; (ii) toda afirmación económica
debe corregirse por **sesgo de selección y solapamiento temporal**.

## 1. AUC-ROC — métrica primaria de detección

- Interpretación probabilística exacta: `AUC = P(score(positivo) > score(negativo))`
  (equivalente al estadístico de Mann–Whitney; Hanley & McNeil 1982).
- **Independiente del umbral**: el punto de corte operativo lo fija el usuario de
  riesgo, no el modelo; el AUC evalúa la calidad del *ranking* completo.
- **Insensible a la prevalencia**: permite comparar canal ascendente (base rate
  0.40), descendente (0.33) y el OOS 2026 (0.11) en una escala común, con el
  azar anclado en 0.5.
- Estándar en evaluación de clasificadores ML (Bradley 1997; Fawcett 2006).

## 2. Precisión / Recall / F1 — el punto operativo

Con clases desbalanceadas la exactitud es engañosa (predecir siempre "no canal"
acierta 60–90%). La tripleta responde a preguntas distintas:

| Métrica | Pregunta |
|---|---|
| Precisión | Cuando el sistema marca canal, ¿cuánto me fío? (usuario) |
| Recall | ¿Cuántos canales reales se escapan? (supervisor) |
| F1 | Media armónica: penaliza desequilibrios; criterio de selección de umbral |

Saito & Rehmsmeier (2015, PLoS ONE) muestran que con desbalance el espacio
precisión-recall es más informativo que el ROC → se reportan ambas familias.

## 3. Balanced accuracy y macro-F1 — multiclase con 8 patrones

La accuracy global queda dominada por las clases mayoritarias (canales, rango).
- **Balanced accuracy** = media de recalls por clase (Brodersen et al. 2010).
- **Macro-F1** = media no ponderada de F1 por clase: obliga a rendir en clases raras.
- El pipeline selecciona modelo por macro-F1 en validación (`monitor_metric`) y
  reporta matriz de confusión completa + soporte por clase, para que cualquier
  revisor recalcule métricas derivadas.

## 4. Bootstrap ΔAUC — comparación estadística entre modelos

La afirmación "solo-precio > cross-asset" no se apoya en una diferencia puntual:
- Bootstrap estratificado del **mismo** conjunto de test (B=3000), preservando la
  proporción de positivos → respeta la correlación entre los errores de ambos
  modelos (misma lógica que el test de DeLong 1988, sin asumir normalidad).
- Se reporta IC 95% percentil de ΔAUC y P(Δ>0). IC que excluye 0 ⇔ rechazo de
  igualdad de AUCs al 5%.
- Resultado: ΔAUC = +0.026…+0.046 a favor de solo-precio, todos los IC95
  excluyen 0, P(gana) = 100%.

## 5. Métricas económicas corregidas por overfitting (López de Prado)

Un Sharpe atractivo puede fabricarse probando configuraciones hasta que una
funcione (White 2000 "Reality Check"; Harvey & Liu 2015 "Backtesting"). Por eso:

- **PSR** (Bailey & López de Prado 2012): probabilidad de que el Sharpe verdadero
  supere un umbral, corrigiendo por longitud de muestra, asimetría y curtosis.
- **DSR** (Bailey & López de Prado 2014): PSR contra el máximo Sharpe esperable
  por azar tras N pruebas. En el backtest de canal: DSR ≈ 1.7e-6 con
  E[max SR por azar] = 4.04 → el Sharpe 0.33 observado es atribuible a la búsqueda.
- **PBO vía CSCV** (Bailey et al. 2017): probabilidad de que la mejor
  configuración in-sample quede bajo la mediana out-of-sample (12.870
  combinaciones de 16 bloques). PBO = 0.38 en el backtest de canal.

## 6. CV purgada + embargo — por qué no vale un K-fold

Con stride 1, dos ventanas contiguas comparten 31/32 observaciones y la etiqueta
depende de hasta 5 días futuros. Una CV aleatoria colocaría en entrenamiento
réplicas casi exactas del test → todas las métricas quedarían infladas.
- **Purga**: se elimina del train toda ventana cuyo intervalo de información
  solape con el de test.
- **Embargo** (5 posiciones): correlación serial residual.
- **Walk-forward multipath**: predicciones OOS concatenadas de folds temporales.
(López de Prado 2018, caps. 7 y 12.)

## 7. Tres niveles de exigencia temporal

1. **Out-of-time** (corte 2020-08): un solo corte, test 2020–2026 con COVID/guerra.
2. **Rolling-origin** (65 cortes): AUC por edad del modelo → sin decaimiento,
   justifica recalibración anual.
3. **Out-of-sample real** (abr–jun 2026): datos descargados tras cerrar el
   diseño; la prueba más dura contra el data snooping.

## Tabla resumen métrica → pregunta del comité

| Métrica | Pregunta que responde | Referencia clave |
|---|---|---|
| AUC-ROC | ¿Ordena bien sin fijar umbral ni depender de prevalencia? | Hanley & McNeil 1982 |
| Prec/Rec/F1 | ¿Fiabilidad y cobertura del punto operativo? | Saito & Rehmsmeier 2015 |
| Balanced acc / macro-F1 | ¿Rinde también en clases raras? | Brodersen et al. 2010 |
| Bootstrap ΔAUC | ¿La mejora entre modelos es real? | Efron & Tibshirani 1994; DeLong 1988 |
| Sharpe + PSR | ¿Rendimiento distinguible de 0 con no-normalidad? | Bailey & LdP 2012 |
| DSR | ¿Sobrevive a la corrección por nº de pruebas? | Bailey & LdP 2014 |
| PBO (CSCV) | ¿P(mejor config IS falle OOS)? | Bailey et al. 2017 |
| CV purgada + embargo | ¿Métricas libres de fuga por solapamiento? | López de Prado 2018 |
