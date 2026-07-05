# Ejecución local — BRENT Pattern System v2 (resumen de la sesión)

Repositorio clonado en `/home/wadie/Escritorio/brent-capsule`.

## Entorno
- **`.venv/`** — venv CPU (Python 3.12). PyTorch 2.2.2+cpu, torchvision 0.17.2+cpu,
  numpy 1.26.4, pandas 2.2.2, openpyxl 3.1.5, pyyaml 6.0.2. (pip se bootstrapeó con
  get-pip.py porque el sistema no traía ensurepip; no requirió sudo).
- **`.venv-gpu/`** — se crea automáticamente al lanzar `run_gpu.sh` (ver GPU abajo).

## Configuraciones (rutas adaptadas a local; las originales usan `/data` y `/results`)
- `code/config_local_cpu.yaml` — **baseline** reproducible (equivale a config_codeocean:
  CPU, sin pretrained, imagen 96, 3 folds). Salida → `results/`.
- `code/config_local_cpu_opt.yaml` — **optimizada** (ver más abajo). Salida → `results_opt/`.
- `code/config_gpu_local.yaml` — régimen GPU (device cuda, AMP, imagen 160, 5 folds,
  pretrained ImageNet, pre-entrenamiento sintético). Salida → `results_gpu/`.

## Cómo se ejecutó (CPU)
```bash
cd code
PYTHONHASHSEED=0 ../.venv/bin/python -m brent_pattern_system.train_torch \
    --config config_local_cpu.yaml        # baseline  -> results/
PYTHONHASHSEED=0 ../.venv/bin/python -m brent_pattern_system.train_torch \
    --config config_local_cpu_opt.yaml    # optimizada -> results_opt/
```

## Optimización de hiperparámetros (baseline -> optimizada)
El baseline colapsaba a clases mayoritarias (macro-F1 ~0.18) y mostraba overfitting
(PBO 0.73). La config optimizada corrige esto:
| Hiperparámetro          | Baseline | Optimizada | Motivo                                    |
|-------------------------|----------|------------|-------------------------------------------|
| pretrained_backbone     | false    | **true**   | features ImageNet vs. pesos aleatorios    |
| use_synthetic_pretrain  | false    | **true**   | la cabeza aprende formas de patrón        |
| image_size              | 96       | **128**    | más resolución                            |
| use_focal_loss          | false    | **true**   | combate el desbalance de clases           |
| dropout                 | 0.30     | **0.40**   | más regularización -> menos overfit       |
| unfreeze_last_blocks    | 2        | **3**      | fine-tuning más profundo                  |
| epochs / fine_tune      | 6 / 4    | **10 / 8** | más entrenamiento                         |
| n_splits (walk-forward) | 3        | **4**      | validación más robusta                    |
| grad_clip / cosine LR   | —        | **sí**     | estabilidad                               |

## GPU (requiere reinicio)
El kernel en ejecución `6.17.0-23` no tiene módulo NVIDIA (no existe en los repos).
El kernel `6.17.0-22` (ya instalado) **sí** tiene el módulo firmado por Canonical.
- GRUB se dejó por defecto en `6.17.0-22` (backup: `/etc/default/grub.bak.claude`).
- **Tras reiniciar**, ejecuta:
  ```bash
  bash /home/wadie/Escritorio/brent-capsule/run_gpu.sh
  ```
  El script verifica `nvidia-smi`, crea `.venv-gpu`, instala la rueda CUDA de PyTorch
  adecuada a la GPU, y lanza `config_gpu_local.yaml`. Resultados → `results_gpu/`.

### Revertir GRUB (cuando termines)
```bash
sudo cp /etc/default/grub.bak.claude /etc/default/grub && sudo update-grub
```

## Salidas generadas por cada run (`results*/`)
- `reports/brent_resultados.xlsx` — Excel académico (11 hojas: resumen, configuración,
  entorno, clasificación, matriz de confusión, regresión, backtest, robustez DSR/PBO,
  Sharpe por fold, folds, predicciones OOS).
- `reports/run_manifest.json` — manifiesto de reproducibilidad (config + entorno + git).
- `reports/torch_walkforward_summary.json` — métricas clasificación/regresión/backtest.
- `reports/torch_oos_predictions.csv` — predicciones out-of-sample por fold.
- `models/` — un modelo `.pt` por fold + reportes de entrenamiento.
- `metadata/` — window_table, metadatos del dataset, plantillas de outliers, validación.

## Experimentos de mejora (GPU) — resumen y conclusión

Se exploró superar el azar direccional y, luego, riesgo y clasificación.

### Dirección (signo del retorno forward) — target multi-día
Configs `code/config_gpu_trend_h{5,10,20}.yaml` (embargo=horizonte, reg_weight 1.5).
Salidas `results_gpu_trend_h{5,10,20}/`.
| H | hit direccional | base rate | edge | corr |
|---|---|---|---|---|
| 5 | 0.511 | 0.546 | −0.035 | −0.01 |
| 10 | 0.506 | 0.547 | −0.041 | +0.01 |
| 20 | 0.482 | 0.528 | −0.046 | −0.08 |
**No supera el base rate en ningún horizonte** (corr≈0). Dirección no predecible OOS.

### Riesgo (volatilidad realizada forward) — CNN vs persistencia
Configs `code/config_gpu_vol_h{5,10,20}.yaml` (reg_weight 2.0, sin synthetic).
Salidas `results_gpu_vol_h{5,10,20}/`.
| H | hit CNN | hit persistencia | corr CNN | corr persistencia |
|---|---|---|---|---|
| 5 | 0.476 | 0.581 | −0.01 | 0.32 |
| 10 | 0.472 | 0.652 | −0.08 | 0.40 |
| 20 | 0.470 | 0.710 | −0.05 | 0.45 |
La volatilidad ES predecible, pero **el CNN no la captura** (corr≈0, R²≪0); una
persistencia trivial lo supera con holgura.

### Clasificación de patrones (macro-F1)
Mejor: `results_gpu_trend_h5/` macro-F1 **0.319** (config estándar + más datos).
El refinado `code/config_gpu_cls.yaml` (focal, synth 12k, min_conf 0.30) → 0.232 (peor).
Techo ~0.32, limitado por clases raras con ~0 soporte real.

### Conclusión metodológica
Con walk-forward purgado (embargo≥horizonte) + DSR/PBO, **no hay señal direccional ni
de volatilidad explotable por este CNN** sobre imágenes de patrón + 180 features macro.
Resultado robusto y honesto: el valor está en *haberlo demostrado con rigor*, no en un
modelo de trading. La volatilidad sí es forecastable, pero pide otro enfoque
(GARCH/persistencia/modelo de vol dedicado), no este pipeline de clasificación de imágenes.

### Histórico extendido (2007-2026) — la clave estaba en el histórico inicial
Debilidad detectada: 8 features (SOFR desde 2018, ESTR desde 2019) recortaban el
entrenamiento a 2019+. Quitándolas por config (`feature_regex_drop: ['^SOFR','^ESTR']`)
el histórico usable pasa de 2290 a 6726 ventanas (2007-09 → 2026-02, ~2.9×).
Configs: `code/config_gpu_ext_trend_h10.yaml`, `code/config_gpu_ext_cls.yaml`.
Salidas: `results_gpu_ext_trend_h10/`, `results_gpu_ext_cls/`.

- **Dirección (H10):** con 3× datos sigue en azar (hit 0.509 vs base 0.534, corr≈0).
  No-predictibilidad direccional CONFIRMADA como estructural, no por falta de datos.
- **Clasificación por patrón (2007+):** accuracy global 0.508→0.692. Los CANALES se
  disparan: ascending_channel F1 0.42→**0.80** (sup 2369), descending F1 0.36→**0.75**
  (sup 2013), range 0.45. Patrones de reversión (head&shoulders sup=1, flags sup=3)
  siguen a 0: problema de FRECUENCIA en el Brent, no de modelo.

Fuente de datos real: **FRED** (Brent=DCOILBRENTEU) + **ECB** (EURUSD), no Yahoo.
Datos terminan 2026-03-06; para test out-of-time en meses recientes hace falta
descargar de FRED/ECB (requiere FRED API key gratuita).

### Detector binario de canal + frecuencia de recalibración
Script no invasivo `code/binary_channel_study.py` (reutiliza pipeline; extrae features
del backbone en GPU una vez y entrena cabezas logísticas). Salida `results_binary/`.
Datos 2007-2026 (drop SOFR/ESTR), features frozen ImageNet + LogisticRegression.

Out-of-time (train ≤2020-08, test 2020-08→2026-03, incluye COVID/guerra):
| Detector | AUC | F1 | prec | recall |
|---|---|---|---|---|
| ascending_channel | 0.947 | 0.848 | 0.79 | 0.91 |
| descending_channel | 0.929 | 0.803 | 0.83 | 0.77 |

Recalibración (65 cortes rolling-origin, AUC por edad del modelo):
| edad | ascend | descend |
|---|---|---|
| 1-3m | 0.883 | 0.867 |
| 3-6m | 0.908 | 0.892 |
| 6-12m | 0.919 | 0.908 |
**Sin decaimiento con la edad** -> la geometría del canal es invariante al régimen;
recalibrar la cabeza ~anualmente basta. La adaptación a shocks importa para
dirección/riesgo (no predecibles), no para la detección de patrones.

PENDIENTE (requiere datos nuevos): test en abr-jun 2026 necesita descargar FRED/ECB
(FRED API key) y recomputar las 180 features con las mismas medias/desv (z-score).

### Ventana adaptativa por régimen (tarea 1) — NO mejora
Script `code/adaptive_window_study.py` (multi-escala 16/32/64 + régimen vol, features frozen).
Salida `results_adaptive/`. Out-of-time (train ≤2020, test 2020-2026):
| enfoque | ascend AUC/F1 | descend AUC/F1 |
|---|---|---|
| lookback fijo 32 | 0.947/0.851 | 0.930/0.806 |
| multi-escala 16/32/64 | 0.944/0.845 | 0.935/0.792 |
| multi + régimen(vol) | 0.944/0.845 | 0.935/0.791 |
| gating por régimen (3 cabezas) | 0.880/0.763 | 0.870/0.691 |
La ventana fija 32 ya es óptima; multi-escala empata, gating por régimen empeora
(fragmenta datos). Refuerza que la geometría del canal es invariante al régimen.

### Estado de tareas
1. Ventana adaptativa -> HECHO (no mejora; fijo 32 gana).
2. Test out-of-time abr-jun 2026 -> BLOQUEADO: necesita FRED API key para descargar
   datos nuevos + recomputar 180 features con las mismas medias/desv.
3. Cerrar métricas/Excel (F1/recall/accuracy) con el out-of-sample nuevo -> tras tarea 2.

### Tareas 2 y 3 — Test out-of-sample meses recientes + métricas/Excel — HECHO
Descubrimiento clave: el detector de canal funciona MEJOR con imagen SOLO-PRECIO
(ascending AUC 0.973/F1 0.900, descending 0.956/0.844) que con el canal macro -> solo
necesita el precio del Brent. Fuente: FRED DCOILBRENTEU (misma serie del training),
datos hasta 2026-06-29. Nota: FRED difiere del CSV training ~$1.19 medio (vintage);
se usa FRED como fuente ÚNICA (train+test) para evitar mezcla.
Scripts: `code/price_only_test.py`, `code/build_recent_oos_test.py`. Salidas
`results_priceonly/`, `results_oos_recent/` (JSON, CSV predicciones, Excel).

Out-of-sample REAL (entrena ≤2026-03-06, test 2026-04-08..2026-06-29, n=83, nunca visto):
| detector | AUC | accuracy | F1 | precision | recall |
|---|---|---|---|---|---|
| ascending_channel | 1.00 | 0.976 | 0.875 | 1.000 | 0.778 |
| descending_channel | 0.90 | 0.819 | 0.851 | 0.827 | 0.878 |
Caveat: muestra pequeña (~3 meses). Confirma que el modelo entrenado ≤marzo generaliza
al trimestre siguiente sin recalibrar -> recalibración ~trimestral/anual suficiente.
Excel: results_oos_recent/oos_recent_canal.xlsx.

### Dos ramas (imagen + tabular cross-asset) — la correlación cross-asset NO aporta
Script `code/two_branch_study.py`, salida `results_two_branch/`. Rama tabular = 34
correlaciones Brent↔activo (DAX/SP500/EURUSD/GOLD/VIX/rates...) + retornos, por ventana.
Out-of-time (train ≤2020):
| variante | ascend AUC/F1 | descend AUC/F1 |
|---|---|---|
| imagen 3-canal (CNN) | 0.947/0.848 | 0.929/0.803 |
| tabular cross-asset sola | 0.504/0.556 | 0.468/0.398 |
| imagen + tabular | 0.934/0.835 | 0.909/0.776 |
La tabular cross-asset da AUC≈0.50 (azar) y COMBINADA EMPEORA. Confirma: la correlación
cross-asset no ayuda a detectar geometría de precio (canal). Su sitio sería dirección/
riesgo (no predecibles). Mejor modelo = solo-precio (ch0 GASF + ch1 GADF dominantes).

### Excel final consolidado
`code/build_final_excel.py` -> `results_final/brent_canal_resultados.xlsx` (7 hojas):
00_Resumen, 01_Comparativa_OOT (imagen completa vs price-only vs dos ramas),
02_OOS_reciente (abr-jun 2026), 03_Recalibracion, 04_Dos_ramas_crossasset,
05_Predicciones_OOS, 06_Ventana_adaptativa. Sin descargas nuevas: consolida métricas ya
calculadas (imagen 3-canal histórica AUC 0.93-0.95 junto a price-only y OOS reciente).

### Argumento significativo: solo-precio > cross-asset (bootstrap)
`code/price_vs_crossasset_argument.py` -> `results_final/precio_vs_crossasset.json` +
hoja `07_Precio_vs_CrossAsset` en el Excel. Mismo test out-of-time (cutoff 2020-08-20),
IC95 bootstrap (3000) sobre ΔAUC = precio − rival:
| patrón | vs imagen macro | vs imagen+tabular | vs tabular sola |
|---|---|---|---|
| ascendente | +0.026 [.019,.033] | +0.039 [.030,.048] | +0.470 |
| descendente | +0.026 [.018,.035] | +0.046 [.036,.057] | +0.488 |
Todos los IC95 excluyen 0 y son positivos; P(precio gana)=100%. Solo-precio Brent es
significativamente mejor -> el macro/cross-asset degrada la detección de canal.

### Entrega revista, backtest, inferencia y chartismo por capas
- **Capsule Code Ocean intacto**: `git diff` vacío (0 ficheros originales modificados).
  Export limpio para la revista: `/home/wadie/Escritorio/brent-capsule-ocean-ENTREGA.zip`
  (`git archive HEAD`, solo ficheros versionados). Mis scripts/experimentos son untracked.
- **Backtest DSR/PBO de la estrategia de canal** (`code/channel_backtest.py`,
  `results_channel_backtest/`): largo-ascendente/corto-descendente, OOS no solapado 2020-2026.
  Sharpe 0.33 vs buy&hold 1.00; retorno +1.7% vs +97%; **DSR=0.00**; PBO 0.38.
  -> Detectar canal (AUC 0.97) NO es estrategia rentable; el chartismo no da edge robusto
  (coherente con dirección no predecible). Resultado publicable (eficiencia de mercado).
- **Detector empaquetado** `code/channel_detector.py` (train/predict, solo-precio).
  Artefacto `results_inference/heads.joblib`; demo `results_inference/demo_predictions.csv`.
- **Chartismo por capas (capa 2)** `code/multi_pattern_detectors.py`, `results_multipattern/`:
  detectables = canales (AUC 0.96-0.97) y rango (0.83); doble techo/suelo señal débil
  (AUC 0.64-0.68, F1=0, ~100 casos); cabeza-hombros/flags casi inexistentes (soporte 1-6).
  Cuello de botella = el etiquetador `patterns.py` solo define 8 clases y el Brent tiene
  pocos patrones de reversión. Para la lista completa (triángulos, cuñas, banderines,
  rectángulo, taza-asa) hay que AÑADIR reglas geométricas al labeler + pretraining sintético.

### Cierre en formato Code Ocean (con resultados y docs)
- Capsule ORIGINAL intacto (git diff vacío). NO se entrega .zip: la carpeta
  `brent-capsule/` ES el capsule (code/ data/ environment/ metadata/ results/ docs/).
- `results/` poblado: reports/ (Excels brent_canal_resultados.xlsx + oos_recent_canal.xlsx
  + JSONs de métricas), predictions/ (OOS + demo), models/ (detector_canal_heads.joblib).
  Índice en `results/RESULTS_README.md`.
- `docs/risk_framework.tex` (Overleaf) + `docs/RISK_FRAMEWORK.md`: marco de riesgo 4 capas
  + spec de dashboard. Preferencia usuario: PDF vía .tex/Overleaf (no tooling local).

## Revisión pre-commit + documentación v3 (2026-07-05)

- **Fixes de código para el commit** (tercero debe poder ejecutar):
  - `code/channel_detector.py` reescrito: sin ruta absoluta hardcodeada (usa
    RESULTS_DIR / /results / repo-relativo), `train` funcional (antes crasheaba
    con `os.path.exists(None)` y desalineaba features/etiquetas), nuevo
    `--cutoff` que reproduce `detector_solo_precio.json`, `load_brent` a días
    hábiles (B).
  - `environment/requirements.txt`: + scikit-learn==1.4.2, joblib==1.4.2.
  - `.gitignore`: whitelisting de results/ (Excels, JSONs, predicciones, heads
    joblib 12K, training reports); `.pt` de 27MB y caché siguen fuera.
  - `results/RESULTS_README.md` y `REPRODUCING.md`: eliminadas referencias a los
    8 scripts de estudio que no están en el repo (los JSON quedan como registro;
    metodología en ledger + LaTeX).
- **Documentación nueva**:
  - `docs/CCN_BRENT_canal/` — documento LaTeX v3 completo (Overleaf, pdfLaTeX +
    bibtex): consolida TODO el arco (detector solo-precio, bootstrap
    cross-asset, OOS 2026, recalibración, multipatrón, backtest DSR/PBO), con
    Anexo A (formulación matemática), Anexo B (justificación de métricas para
    comité) y Anexo C (reproducibilidad). 11 figuras en figures/ generadas desde
    los resultados reales (script en scratchpad de la sesión).
  - `docs/JUSTIFICACION_METRICAS.md` — resumen standalone del Anexo B.
  - `docs/presentacion_brent.html` — presentación visual autocontenida.
  - `docs/MEJORAS_PROPUESTAS.md` — mejoras priorizadas (investigación/código/datos).
- Duplicidades verificadas: config JSON≡YAML en sincronía; rama TF sin
  ejercitar (candidata a contrib/); `recurrence_plot` y `_interp_resize_1d` sin
  llamadores. No se eliminó funcionalidad.

## Consolidación de docs + figuras legibles (2026-07-05, 2ª parte)

- **docs/ limpiado a proyecto único** (todo recuperable de git, commit 5238de6):
  eliminados `CCN_BRENT_pattern/` (doc v2 corta), `main.tex`+`references.bib`+
  `README.md` (manuscrito elsarticle v2, absorbido) y `risk_framework.{tex,md}`
  (integrado). Nuevo `docs/README.md` como índice.
- **Risk framework integrado**: §6 del LaTeX (tabla evidencia→implicación,
  diagrama TikZ de 4 capas, tabla de 5 paneles del dashboard, gobernanza) y
  sección 08 del HTML (capas anidadas en CSS + tabla de paneles + regla de oro).
- **Hoja de ruta integrada**: Anexo D del LaTeX y sección 09 del HTML.
- **Figuras corregidas** (leyendas superpuestas → fuera del área de datos):
  brent_timeline (leyenda debajo), comparativa_variantes (leyenda inferior común
  con entrada "Azar"), oos_2026 (leyenda bajo el panel de probabilidades),
  multipatron (soporte n+ dentro de las etiquetas del eje), backtest_canal
  (4 paneles con escalas separadas — antes el Sharpe quedaba aplastado por el %).
