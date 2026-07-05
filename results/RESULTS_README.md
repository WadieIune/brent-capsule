# /results — Salidas (formato Code Ocean)

Resultados del BRENT Pattern System v2. El capsule original (código en `/code`) está
**intacto**; estas salidas son las generadas por los experimentos.

## reports/
**Excel**
- `brent_canal_resultados.xlsx` — **entregable principal** (8 hojas): resumen, comparativa
  out-of-time, OOS abril–junio 2026, recalibración, dos ramas cross-asset, predicciones OOS,
  ventana adaptativa y argumento bootstrap solo-precio > cross-asset.
- `oos_recent_canal.xlsx` — test out-of-sample abr–jun 2026 (F1/recall/accuracy + confusión).
- `brent_resultados.xlsx` — salida del pipeline base (run reproducible CPU).

**JSON (métricas)**
- `detector_solo_precio.json` — detector de canal solo-precio (AUC 0.97/0.96).
- `detector_canal_out_of_time.json` — imagen 3-canal + curva de recalibración.
- `oos_reciente_2026.json` — métricas OOS abr–jun 2026.
- `dos_ramas_crossasset.json` — imagen vs tabular vs ambas (cross-asset ≈ azar).
- `argumento_precio_vs_crossasset.json` — bootstrap ΔAUC (precio > cross-asset, IC95).
- `multipatron.json` — detectabilidad por patrón (capa 2).
- `backtest_canal_dsr_pbo.json` — backtest estrategia de canal (DSR=0, no pasa).
- `ventana_adaptativa.json` — fija 32 vs multi-escala vs gating.
- `run_manifest.json`, `torch_walkforward_summary.json` — trazabilidad del run base.

## predictions/
- `oos_recent_predictions.csv` — predicción diaria del detector, abr–jun 2026.
- `demo_predictions.csv` — inferencia sobre el histórico Brent completo (FRED).

## models/
- `detector_canal_heads.joblib` — cabezas logísticas entrenadas (ascendente/descendente),
  usar con `code/channel_detector.py predict`.
- `brent_efficientnet_b1_torch_fold*.pt` — modelos por fold del pipeline base.

## Documentación (`/docs`)
- `CCN_BRENT_canal/` — documento LaTeX del proyecto (Overleaf); incluye el marco
  de riesgo de 4 capas + dashboard (§6) y anexos de métricas y reproducibilidad.
- `presentacion_brent.html` — presentación visual autocontenida.

## Reproducir
Ver `REPRODUCING.md` para el run base de la cápsula (`code/run`).

**Detector de canal** (`code/channel_detector.py`): reproduce el resultado principal.
```bash
# reentrena las cabezas y reproduce detector_solo_precio.json (out-of-time):
python code/channel_detector.py train --config code/config_codeocean.yaml --cutoff 2020-08-20
# inferencia sobre una serie de precios (CSV date,BRENT):
python code/channel_detector.py predict --prices brent.csv --out preds.csv
```

Los estudios complementarios (dos ramas cross-asset, ventana adaptativa,
multipatrón, backtest de la estrategia de canal, OOS abr–jun 2026) se ejecutaron
con scripts de experimentación externos a la cápsula; sus métricas completas
quedan registradas en los JSON de `reports/` y su metodología en
`docs/PROJECT_LEDGER.md` y en el documento LaTeX de `docs/`.
