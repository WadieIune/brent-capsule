#!/usr/bin/env python3
"""Batería TRIM completa de controles deterministas de serie temporal.

Aplica a cada serie del panel los controles del estándar TRIM/DQ y reporta los
defectos REALES encontrados. Son el estrato barato y determinista del framework
(cierran los huecos que 3σ no ve: rachas, repetidos). La capa ML/DL (autoencoder
+ IsolationForest) se evalúa aparte para el decoplamiento, que es lo que estos
checks no capturan. Ejecutable: `python code/applications/experiments/dq_trim_checks.py`.
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ZERO_RUN_TRIM = 20     # >=20 sesiones con rendimiento 0 -> P&L mensual repetido
SIGMA_K = 3.0


def max_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def checks(series: pd.Series) -> dict:
    s = series.dropna()
    px = s.to_numpy(float)
    if len(px) < 30:
        return {"n": int(len(px)), "insuficiente": True}
    r = np.diff(np.log(np.clip(px, 1e-12, None)))
    zero_ret = (r == 0)
    # repetidos de valor exacto (consecutivos)
    rep_consec = (np.diff(px) == 0)
    sig = np.std(r)
    out = {
        "n_registros": int(len(px)),
        "precios_no_positivos": int((px <= 0).sum()),
        "min": round(float(np.min(px)), 4), "max": round(float(np.max(px)), 4),
        "rendimientos_cero": int(zero_ret.sum()),
        "pct_rend_cero": round(100 * zero_ret.mean(), 2),
        "racha_max_rend_cero": int(max_run(zero_ret)),
        "ALERTA_TRIM_racha>=20": bool(max_run(zero_ret) >= ZERO_RUN_TRIM),
        "racha_max_precio_repetido": int(max_run(rep_consec)),
        "repetidos_valor_total": int(rep_consec.sum()),
        "outliers_3sigma": int((np.abs(r) > SIGMA_K * sig).sum()),
        "salto_max_abs_rend": round(float(np.max(np.abs(r))), 4),
    }
    return out


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"]).set_index("date")
    rep = {c: checks(df[c]) for c in df.columns}
    alerts = {c: v for c, v in rep.items() if v.get("ALERTA_TRIM_racha>=20")}
    nonpos = {c: v["precios_no_positivos"] for c, v in rep.items() if v.get("precios_no_positivos", 0) > 0}
    out = {"panel": "panel_extendido_2026-09-09.csv", "zero_run_trim": ZERO_RUN_TRIM,
           "series_con_ALERTA_racha>=20": list(alerts), "series_con_precio_no_positivo": nonpos,
           "detalle": rep}
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_trim_checks.json"), "w"), indent=2, ensure_ascii=False)
    print("Series con ALERTA TRIM (racha de rendimiento 0 >= 20):", list(alerts) or "ninguna")
    print("Series con precio no positivo:", nonpos or "ninguna")
    print("\nTop rachas de rendimiento 0 por serie:")
    for c in sorted(rep, key=lambda k: -rep[k].get("racha_max_rend_cero", 0))[:8]:
        print(f"  {c:<20} racha_max={rep[c].get('racha_max_rend_cero',0):>3}  %cero={rep[c].get('pct_rend_cero',0):>5}  outliers3σ={rep[c].get('outliers_3sigma',0)}")


if __name__ == "__main__":
    main()
