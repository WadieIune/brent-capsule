# Mejoras propuestas — BRENT Pattern System

Lista priorizada tras la revisión completa del proyecto (2026-07-05). Se separa
investigación, código y datos. Las marcadas ✔ ya se aplicaron en esta revisión.

## Investigación (prioridad alta)

1. **Ampliar el etiquetador geométrico** (`brent_pattern_system/patterns.py`).
   Es el cuello de botella de la "capa 2" del chartismo: solo define 8 figuras y
   en el Brent las de vuelta apenas existen (soporte 1–6 en 6.726 ventanas).
   Añadir triángulos (simétrico/ascendente/descendente), cuñas, banderines,
   rectángulos y taza-con-asa, con pretraining sintético de las nuevas clases
   (`synthetic_patterns.py` ya tiene la infraestructura de plantillas).
2. **Restricción de orden en las salidas continuas** de la CNN multitarea:
   `pred_low ≤ pred_return ≤ pred_high` (p. ej. parametrizar
   `low = ret − softplus(a)`, `high = ret + softplus(b)`). Elimina las
   inversiones low/high documentadas y es una crítica fácil de un revisor.
3. **Ampliar el OOS real** trimestre a trimestre (jul–sep 2026, etc.) con el
   mismo procedimiento FRED-única-fuente, acumulando evidencia de estabilidad.
   El coste marginal es mínimo (`channel_detector.py predict` + métricas).
4. **Calibración de probabilidades** (Platt/isotónica sobre validación purgada) y
   reporte de curvas de fiabilidad: para uso en riesgo, la probabilidad diaria
   debe estar calibrada, no solo ordenar bien (AUC).
5. **Baselines no-CNN para el comité**: una regresión logística sobre features
   geométricas simples (pendiente, R², nº extremos — ya calculadas en
   `pattern_metrics.py`) como control. Si el embedding CNN no supera claramente
   a esas features, el argumento EfficientNet se debilita; si las supera,
   la elección queda blindada.
6. **Volatilidad con modelo dedicado** (GARCH / HAR-RV / persistencia) como
   módulo separado del dashboard de riesgo: quedó demostrado que es forecastable
   (corr 0.32–0.45 con persistencia trivial) pero que este pipeline no la captura.

## Código

7. ✔ **`channel_detector.py`**: eliminada la ruta absoluta hardcodeada
   (`/home/wadie/...` → `RESULTS_DIR`/`/results`/repo-relativo), corregido el
   crash de `train` (`os.path.exists(None)`) y el desalineamiento
   features/etiquetas del fallback; añadida evaluación out-of-time (`--cutoff`)
   que reproduce `detector_solo_precio.json`; imports muertos eliminados.
8. ✔ **Dependencias**: `scikit-learn` y `joblib` añadidos a
   `environment/requirements.txt` (los importa `channel_detector.py`).
9. ✔ **`.gitignore`**: whitelisting de `results/` (Excel, JSON, predicciones,
   joblib de 12 KB) manteniendo fuera los `.pt` de 27 MB y la caché.
10. ✔ **Referencias rotas**: `results/RESULTS_README.md` citaba 8 scripts de
    estudio inexistentes en el repo; ahora documenta qué es reproducible desde la
    cápsula y dónde está registrado el resto. `REPRODUCING.md` citaba un
    `BIBLIOGRAFIA.md` inexistente (→ `docs/CCN_BRENT_canal/references.bib`).
11. **Duplicidades a vigilar (sin pérdida de funcionalidad)**:
    - `config_codeocean.json` ≡ `config_codeocean.yaml` (verificado en sincronía).
      Riesgo de deriva: tratar el YAML como fuente de verdad y regenerar el JSON,
      o eliminar el JSON cuando Code Ocean no lo exija.
    - Dos `requirements.txt` (entorno de la cápsula vs orientativo del paquete):
      aceptable, pero conviene una nota cruzada de cuál manda (el del entorno).
    - Rama TensorFlow (`tf_model.py`, `train_tf.py`, 386 líneas): funcional pero
      no ejercitada por ningún resultado entregado. Candidata a extraerse a una
      rama/carpeta `contrib/` en la versión de revista para reducir superficie.
    - `image_encoding.recurrence_plot` y `_interp_resize_1d`: sin llamadores
      (codificación alternativa documentada; decidir si se citan o se eliminan).
12. **Tests mínimos**: el repo no tiene tests. Tres smoke tests con pytest
    (etiquetador sobre ventanas sintéticas conocidas; purga/embargo sin
    solapamiento de spans; encoding determinista) darían mucha confianza a
    revisores por poco coste.
13. **CI ligera** (GitHub Actions): `python -m compileall` + smoke tests + run
    de 1 época con dataset truncado, para que el badge de build acompañe al repo.

## Datos

14. **Vintages FRED**: documentar la diferencia media de ~1.19 USD entre el CSV
    original y FRED actual (ya se mitigó usando FRED como fuente única para
    train+test del OOS). Fijar fecha de descarga en el manifiesto.
15. **Nodos BCE AAA ausentes** (EUR_AAA_2Y/5Y/10Y/30Y): o recuperarlos o
    eliminar su mención del descargador; hoy son una promesa incumplida que un
    revisor puede señalar.
16. **`load_brent` y festivos**: la versión anterior reindexaba a calendario
    natural con ffill (los CSV de demo incluyen sábados); ✔ ahora usa días
    hábiles (B), coherente con el bundle de entrenamiento. Regenerar
    `demo_predictions.csv` en la próxima corrida para eliminar los fines de
    semana heredados.
