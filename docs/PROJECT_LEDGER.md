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

## Corrección de la pata de VaR (revisión de `code/applications`)

Tres correcciones sobre los resultados previamente publicados:

1. **Bug de dato — WTI negativo.** El 2020-04-20 el WTI liquidó a −37,63 USD.
   `common.log_returns` acota a 1e-9, generando dos log-retornos artificiales de
   |r|≈23 (±2300%) que dominaban la covarianza (WTI aparecía con el **98,4%** del
   riesgo de cartera en vez del 24%) e inflaban la vol EWMA durante meses.
   Fix: `drop_nonpositive()` en `portfolio_var_alert.py`, aplicado también en
   `portfolio_var.py`.
2. **Calendario vs días hábiles.** `dataset_wide_with_target.csv` es de calendario
   con forward-fill: 365 obs/año y ~32% de retornos exactamente cero. Sesga el
   cuantil empírico, contamina el test de independencia (en un día de retorno cero
   no puede haber excepción) y desescala el semáforo de Basilea, que cuenta 250
   sesiones de negociación. Fix: `to_trading_days()` → 251,6 obs/año.
   La serie de un activo (`brent_fred_daily.csv`) ya era de hábiles; se le eliminan
   los 476 rellenos por ffill.
3. **Faltaba el control de nivel.** Se añade `constant_equivalent`: una constante
   con el MISMO VaR medio que el overlay. Y la batería de backtesting se completa
   con **LR_cc** y el **DQ de Engle–Manganelli** (el «DQ» de la literatura de VaR;
   no confundir con `dq_price_control`, que es calidad de dato).

### Resultado corregido — el overlay de canal no aporta timing
La fragilidad de canal **no concentra excepciones**: lift ≈ 1,00 a todos los
cuantiles en el activo único y **0,00** en cartera (en los días de alerta ocurren
CERO excepciones), mientras la vol EWMA da lift 3,19. corr(fragilidad, vol) = −0,12:
el canal se comprime cuando hay calma y las excepciones ocurren en volatilidad alta.

Brent (n=1472): `predicted` y `constant_equivalent` son indistinguibles —15
excepciones, 1,019%, Kupiec 0,942, Christoffersen 1,0000, mismo VaR medio—.
Cartera (n=1393): histórico 1,292% · FHS-EWMA **1,005%** · predicted 0,933%;
Christoffersen 0,0011 → **0,1284** → 0,1080; capital del overlay **+5,3%** vs
histórico. `portfolio_var` pasa de `accept` a **`reject`**.

**Conclusión:** el objetivo (menos excepciones y menos capital) SÍ se alcanza, pero
con **FHS-EWMA** —cobertura 1,005%, arregla el agrupamiento y ahorra **−1,8%** de
capital—, no con el canal. La capa de alertas discreta sobre VaR histórico tampoco
lo logra (+0,2%): el fallo del histórico es de agrupamiento y eso se corrige con
escalado continuo de volatilidad, no con saltos discretos.
Nota: el test DQ rechaza a todos los estimadores de cartera.

## FRTB como aplicación exportable (`frtb_capital.py`)

Nueva aplicación 7: deja preparada la migración de *modelos internos Basilea 2.5*
(`k·VaR 99%`) a **FRTB IMA**, para que un cambio de modelo de riesgo sea una
decisión cuantificada y no una reimplementación.

**Calculado:** ES 97,5% 1-día por FHS-EWMA (0,04232) → 10 días (0,13383) →
horizonte de liquidez (0,18927); periodo de estrés identificado
**2008-03-13 .. 2009-03-11** (retorno acumulado −0,7149) → ES estresado 0,27185;
IMCC (MAR33.6, ratio reducido/completo = 1); backtesting FRTB (14 excepciones al
99% = 3/250d, **zona verde**, m_c = 1,5); proxy RFET/NMRF.

**Horizontes de liquidez:** los fija la norma (MAR33.12) — 20 sesiones para
energía, metales preciosos y no férreos; 60 para otras materias primas. La vida
mediana del canal (11 sesiones) se reporta **solo como evidencia empírica de
apoyo** al cubo prescrito; presentarla como estimación propia invalidaría el
cálculo regulatorio.

**Impacto del cambio de modelo (comparación homogénea):** ambos lados a 10
sesiones y con componente estresado —
Basilea 2.5 `k·(VaR10d + sVaR10d)` = 0,94981 (k=3,0) vs FRTB `m_c·IMCC` = 0,40778
→ **−57,1%**. *Aviso:* el delta es **PARCIAL**; el lado FRTB omite SES (NMRF), DRC
y RRAO, que son los componentes que elevan el cargo IMA. La caída refleja sobre
todo la duplicidad VaR+sVaR con k=3 de Basilea 2.5 frente a un único ES estresado
con m_c=1,5. Por eso la decisión del experimento se mantiene en `review`.

**No calculable con los datos actuales:** PLA test (exige P&L hipotético y
risk-theoretical por mesa), SES (escenarios por factor no modelizable) y DRC.

**Exportable:** `results/frtb_export/frtb_export.json` (schema `frtb-ima-export/v1`)
+ `frtb_daily_series.csv` con la serie diaria de ES 97,5%, VaR 97,5% y VaR 99%.

### Estado de la suite tras la revisión
`dq_price_control` reject · `channel_vol_forecast` accept · `predicted_var` review ·
`portfolio_var` **reject** (antes accept) · `portfolio_var_alert` reject ·
`frtb_applications` review · `frtb_capital` review. Smoke tests: 5/5 OK.

## Reorientación: DQ con impacto, ruptura como tarea propia y capa de régimen

FRTB queda fuera del alcance del paper: bajo el **método estándar** el cargo es
formulaico (sensibilidades × ponderaciones y correlaciones prescritas), de modo
que ningún modelo puede alterarlo; buscar mejora ahí es estéril. `frtb_capital.py`
(IMA) queda documentado y congelado, sin más inversión.

### Aplicación 8 — `dq_impact.py`: Data Quality con impacto medido (accept)
El control geométrico se evalúa por lo que cambia en el motor de riesgo, no por
recuento de alertas:
- **Print no positivo** (WTI, 2020-04-20): detectado por dos reglas
  (`atr_jump_reverting`, `out_of_band`) con severidad frente al canal proyectado.
  El control convencional también lo marca, pero sin atribución ni severidad.
- **Relleno de calendario**: 1.145 marcas `stale`, **88,6% en fin de semana**.
  El control convencional **no puede** verlo: un retorno cero nunca es outlier de cola.
- **Impacto**: la concentración de riesgo en WTI pasa de **0,9845** (datos crudos)
  a **0,2405** (depurados) — **74,4 puntos porcentuales** de distorsión; los
  retornos cero, del 31,12% al 0%.

### Aplicación 9 — `breakout_detection.py`: la ruptura como tarea propia (accept)
Nunca se había medido. Con 8.852 filas de hazard (ruptura en ≤5 sesiones, tasa
base 0,307), escalera de baselines:
| modelo | AUC |
|---|---|
| actuarial (solo tiempo en episodio) | 0,496 |
| volatilidad | 0,482 |
| forma del canal | 0,518 |
| gradient boosting (todo) | 0,668 |
| **solo distancia al borde `\|pos−0,5\|`** | **0,677** |

**Hallazgo:** la tasa de ruptura por posición en la banda es una **U** —0,542 en el
borde inferior, 0,115 en el centro, 0,527 en el superior—. Al ser **no monótona**,
ningún modelo lineal puede capturarla: eso explica por qué todos los overlays
lineales previos (incluido el add-on de VaR) no veían nada. Una única variable
interpretable supera al gradient boosting con todas las features.
Operativamente: **lead time mediano de 6 sesiones** con cobertura del 97,8% de los
episodios, precisión 0,489 y recall 0,435.

*Caveat necesario:* la potencia procede en buena medida de la **proximidad
geométrica al borde de la banda**, que está cerca de la propia definición del
evento (romper = salir de la banda). Es un indicador de alerta temprana válido y
auditable, pero debe presentarse como tal y no como un descubrimiento profundo.

**Lo que NO ocurre:** la ruptura **no expande la volatilidad** — log-ratio −0,226
tras ruptura frente a −0,231 en fecha aleatoria, Welch **t=0,166**. La vía directa
«ruptura → pico de vol → mejor VaR» queda cerrada por los datos.

### Aplicación 10 — `regime_markov.py`: capa de régimen (accept)
Paso previo e interpretable para GARCH/XGBoost. Estados = dirección × zona de banda.
- **Matriz de transición**: fuerte persistencia (diagonal 0,69–0,73), cambios de
  dirección muy raros (~0,02), permanencia esperada 3,2–3,7 sesiones por estado.
- **Markov vs i.i.d.** en test: −987 frente a −1.785 de log-verosimilitud
  (**+0,61 por observación**): la estructura de estados aporta.
- **Homogeneidad del hazard por edad**: chi²=13,34 (gl=5), **p=0,0204**. Hay
  heterogeneidad marginal pero **no monótona** (el hazard oscila 0,23–0,37 sin
  tendencia), lo que explica que el modelo actuarial quede en AUC 0,50.
- **Red bayesiana** `P(ruptura≤5d | estado, vol)`: AUC 0,627 y **Brier 0,2031
  frente a 0,2130** del prior constante → mejora la calibración. Las CPT son
  legibles: `asc_borde` 0,39–0,42 · `desc_borde` 0,32–0,35 · `asc_centro` 0,22–0,26
  · `desc_centro` 0,16 (prior 0,29). La volatilidad apenas mueve la probabilidad;
  manda la geometría.

### Estado de la suite (10 experimentos)
accept: `channel_vol_forecast`, `dq_impact`, `breakout_detection`, `regime_markov` ·
review: `predicted_var`, `frtb_applications`, `frtb_capital` ·
reject: `dq_price_control`, `portfolio_var`, `portfolio_var_alert`. Smoke tests 5/5.

## Reorientación final: DQ operativo + límites de la capa de régimen

### El fin de régimen NO anticipa cambios de correlación (test negativo)
Tercer mecanismo contrastado y descartado, tras expansión de volatilidad y saltos
extremos. Sobre el panel depurado, comparando la matriz de correlación 60 sesiones
antes y después del evento frente a fechas aleatorias:

| Evento | \|Δcorrelación\| tras evento | fecha aleatoria | t |
|---|---|---|---|
| ≥1 activo rompe (n=1.229) | 0,1530 | 0,1545 | −0,68 |
| ≥2 activos rompen (n=249) | 0,1549 | 0,1573 | −0,52 |
| ≥3 activos rompen (n=33) | 0,1573 | 0,1572 | 0,01 |

La alerta de fin de régimen **no sirve como disparador anticipatorio** de recálculo
de correlaciones: un calendario aleatorio avisaría igual de bien.

### La ruptura tampoco señala cambio de tendencia
- P(el canal siguiente cambia de dirección) = **0,351** → la tendencia **continúa**
  el 65% de las veces.
- Canal ascendente rompe hacia abajo el **66,3%**; descendente hacia arriba el
  **70,3%** → la ruptura es típicamente un retroceso *contra* la tendencia, no un giro.
- La dirección de la ruptura **no anticipa el retorno posterior**: acierto
  direccional 0,477 / 0,520 / 0,514 / 0,549 a 1/5/10/20 sesiones; el único t=2,12
  (20d) no sobrevive a corrección por contrastes múltiples ni es fuera de muestra.
- *Nota de método*: predecir la dirección de ruptura con las features de la última
  sesión del episodio da AUC 1,000 — **fuga de datos**, no resultado. Con antelación
  real: 0,778 (3 sesiones) y 0,743 (5), con n=73 y 64, y todavía con proximidad
  geométrica al borde. Reportable solo con esos caveats.

### Aplicación 11 — `dq_daily_monitor.py`: monitor DQ diario (accept)
Sistema operativo que responde a «¿por dónde deberían ir los rendimientos hoy?»:
proyecta el canal un paso adelante (sin fuga) y publica centro esperado, banda
admisible y **rango de rendimiento esperado**, marcando lo que se sale.
- Umbrales **calibrados a carga objetivo** (1%), no por convención: k=5,0σ y
  tol_atr=2,5. Un control sin calibrar satura o no dispara nunca.
- **Modo operativo** (sesiones de negociación): 459 alertas sobre 28.086
  observaciones = **1,63% de carga**; cobertura de la banda 98,99%.
- **Modo auditoría** (`dq_audit_mode`, panel crudo): 25,86%, porque detecta el
  relleno de calendario — hallazgo de auditoría del histórico, no alerta diaria.
- El control convencional emite 30 marcas y es **ciego** al precio congelado y al
  relleno. Valor cuantificado en `dq_impact`: 74,4 pp de distorsión evitada.

### Arquitectura resultante (quién hace qué, según la evidencia)
| Capa | Herramienta | Estatus |
|---|---|---|
| Higiene del dato | control geométrico / CNN | **demostrado** (74,4 pp) |
| Cuantificación de riesgo | EWMA / GARCH (FHS) | **demostrado** (18→14 excepciones, −1,8% capital; AUC 0,81 en saltos) |
| Etiqueta de régimen | CNN-canal | **descriptivo**: no anticipa vol, ni saltos, ni correlaciones |

### Suite (11 experimentos)
accept: `channel_vol_forecast`, `dq_impact`, `breakout_detection`, `regime_markov`,
`dq_daily_monitor` · review: `predicted_var`, `frtb_applications`, `frtb_capital` ·
reject: `dq_price_control`, `portfolio_var`, `portfolio_var_alert`. Smoke tests 5/5.
FRTB queda fuera del paper (SA formulaico; IMA documentado y congelado).
