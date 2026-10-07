#!/usr/bin/env python3
"""Validación REAL del control cross-asset con el defecto de EURUSD (2008).

El defecto de EURUSD (10 saltos imposibles en 2008, serie corrupta de
dataset_wide_with_target.csv) atravesó el pipeline porque el control desplegado
era de correlación de niveles (0,9989, parecía bien). Aquí se comprueba, sobre
dato REAL (no inyectado), qué control lo habría cazado:
  - 3σ sobre log-rendimientos (benchmark, σ móvil causal 60);
  - cross-asset: residuo causal de EURUSD sobre pares (DTWEXBGS/GOLD/DAX/EUROSTOXX50).
Hipótesis: en 2008 (crisis) el 3σ puede perder los saltos corruptos pequeños
porque su umbral sube con la volatilidad real; el cross-asset los aísla quitando
el factor común. Ground truth = 10 días corruptos. FP emparejada sobre días limpios.
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PEERS = ["DTWEXBGS", "GOLD", "DAX", "EUROSTOXX50"]
WIN = 120


def rolling_sigma(r, w=60):
    return pd.Series(r).rolling(w, min_periods=30).std().shift(1).to_numpy()


def cross_asset_z(rt, RP, w=WIN):
    n = len(rt); z = np.full(n, np.nan)
    for t in range(w, n):
        X = RP[t-w:t]; y = rt[t-w:t]
        m = ~(np.isnan(X).any(1) | np.isnan(y))
        if m.sum() < 40 or np.isnan(RP[t]).any():
            continue
        Xo = np.column_stack([np.ones(m.sum()), X[m]])
        beta, *_ = np.linalg.lstsq(Xo, y[m], rcond=None)
        res = y[m] - Xo @ beta; s = res.std()
        if s < 1e-9:
            continue
        pred = beta[0] + beta[1:] @ RP[t]
        z[t] = (rt[t] - pred) / s
    return z


def recall_fp(score, gt, fp):
    s = np.abs(score); clean = ~gt & ~np.isnan(s)
    thr = np.nanquantile(s[clean], 1 - fp)
    flagged = s >= thr
    return float(flagged[gt].mean()), flagged


def main():
    corr = pd.read_csv(os.path.join(ROOT, "data", "dataset_wide_with_target.csv"), parse_dates=["date"]).set_index("date")["EURUSD"]
    pan = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"]).set_index("date")
    clean = pan["EURUSD"]
    df = pd.concat([corr.rename("eur_corrupt"), clean.rename("eur_clean")] +
                   [pan[p].rename(p) for p in PEERS], axis=1).dropna()
    idx = df.index
    rc = np.log(df["eur_corrupt"]).diff().to_numpy()
    rl = np.log(df["eur_clean"]).diff().to_numpy()
    RP = np.column_stack([np.log(df[p]).diff().to_numpy() for p in PEERS])
    # ground truth: salto corrupto > 5 % que la limpia no tiene
    gt = (np.abs(rc) > 0.05) & (np.abs(rl) < 0.05)
    gt_dates = [str(d.date()) for d in idx[np.where(gt)[0]]]

    z3 = np.where(rolling_sigma(rc) > 0, rc / rolling_sigma(rc), 0.0)
    zx = cross_asset_z(rc, RP)

    out = {"fuente_corrupta": "dataset_wide_with_target.csv", "peers": PEERS,
           "n": int(len(df)), "n_defectos": int(gt.sum()), "dias_defecto": gt_dates}
    tabla = {}
    for fp in (0.005, 0.01, 0.02):
        r3, fl3 = recall_fp(np.nan_to_num(z3), gt, fp)
        rx, flx = recall_fp(np.nan_to_num(zx), gt, fp)
        tabla[f"FP={fp}"] = {"recall_3sigma": round(r3, 3), "recall_cross_asset": round(rx, 3)}
    out["recall_a_FP"] = tabla
    # detalle por día: ¿cada control caza cada defecto a FP=0.5%?
    _, fl3 = recall_fp(np.nan_to_num(z3), gt, 0.005)
    _, flx = recall_fp(np.nan_to_num(zx), gt, 0.005)
    det = []
    for i in np.where(gt)[0]:
        det.append({"dia": str(idx[i].date()), "ret_corrupt": round(float(rc[i]), 3),
                    "z_3sigma": round(float(z3[i]), 1), "caza_3sigma": bool(fl3[i]),
                    "z_cross": round(float(zx[i]), 1) if zx[i] == zx[i] else None, "caza_cross": bool(flx[i])})
    out["detalle_por_dia_FP_0.5pct"] = det
    miss3 = [d["dia"] for d in det if not d["caza_3sigma"]]
    missx = [d["dia"] for d in det if not d["caza_cross"]]
    out["veredicto"] = {
        "3sigma_pierde": miss3, "cross_asset_pierde": missx,
        "lectura": (f"El cross-asset caza {sum(d['caza_cross'] for d in det)}/{len(det)} y 3σ "
                    f"{sum(d['caza_3sigma'] for d in det)}/{len(det)} a FP=0,5 %. "
                    + ("El cross-asset recupera defectos que 3σ pierde en 2008." if set(miss3) - set(missx)
                       else "Ambos cazan los mismos; el defecto era de salto, no de decoplamiento puro.")),
    }
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_eurusd_validation.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
