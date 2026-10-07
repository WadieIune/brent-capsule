#!/usr/bin/env python3
"""Cross-asset DQ control a MÚLTIPLES objetivos del panel (robustez).

Extiende el gate barato (3σ vs cross-asset de ventana 1−R²) a cada serie de
precio líquida del panel, con sus pares como control. Ground truth por inyección
(stale / decoplamiento / salto), FP=5 % emparejada, REPS repeticiones. Objetivo:
mostrar que el cross-asset domina de forma ROBUSTA (no solo en BRENT) donde 3σ es
ciego (stale/decoplamiento).
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UNIVERSE = ["BRENT", "WTI", "GOLD", "SILVER", "COPPER", "NATGAS", "SP500", "DAX", "EUROSTOXX50", "EURUSD"]
W = 20; FP = 0.05; REPS = 30; SEED = 42
rng = np.random.default_rng(SEED)


def windows(R, stride=W):
    return np.array([R[t:t+W] for t in range(0, len(R)-W, stride)])


def s_3sigma(win, col):
    return np.max(np.abs(win[:, :, col]), axis=1)


def s_cross(win, col, peers):
    out = []
    for w in win:
        y = w[:, col]; X = w[:, peers]
        Xo = np.column_stack([np.ones(len(y)), X])
        beta, *_ = np.linalg.lstsq(Xo, y, rcond=None)
        res = y - Xo @ beta; ss = np.sum((y - y.mean())**2)
        out.append(1 - (1 - np.sum(res**2)/ss if ss > 1e-12 else 0.0))
    return np.array(out)


def inject(win, col, kind):
    w = win.copy()
    if kind == "decoplamiento": w[:, col] = rng.normal(0, w[:, col].std()+1e-9, W)
    elif kind == "stale":       w[:, col] = 0.0
    elif kind == "salto":       j = rng.integers(2, W-2); w[j, col] += 8; w[j+1, col] -= 8
    return w


def recall(sc_clean, sc_def, fp=FP):
    thr = np.quantile(sc_clean, 1-fp); return float(np.mean(sc_def >= thr))


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    cols = [c for c in UNIVERSE if c in df.columns]
    df = df[["date"]+cols].dropna().reset_index(drop=True)
    R = np.diff(np.log(np.clip(df[cols].to_numpy(float), 1e-6, None)), axis=0)
    mu, sd = R.mean(0), R.std(0)+1e-9; Rz = (R-mu)/sd
    win_all = windows(Rz)
    out = {"universo": cols, "n_ventanas": len(win_all), "W": W, "fp": FP, "reps": REPS}
    fams = ["stale", "decoplamiento", "salto"]
    res = {}
    for ci, target in enumerate(cols):
        peers = [j for j in range(len(cols)) if j != ci]
        r = {f: {"3sigma": [], "cross_asset": []} for f in fams}
        for _ in range(REPS):
            m = len(win_all); perm = rng.permutation(m); h = m//2
            clean = win_all[perm[:h]]; inj = perm[h:]
            c3 = s_3sigma(clean, ci); cx = s_cross(clean, ci, peers)
            for f in fams:
                dw = np.array([inject(win_all[i], ci, f) for i in inj])
                r[f]["3sigma"].append(recall(c3, s_3sigma(dw, ci)))
                r[f]["cross_asset"].append(recall(cx, s_cross(dw, ci, peers)))
        res[target] = {f: {"3sigma": round(float(np.mean(r[f]["3sigma"])), 3),
                           "cross_asset": round(float(np.mean(r[f]["cross_asset"])), 3)} for f in fams}
    out["por_objetivo"] = res
    # resumen: mediana del recall cross-asset vs 3σ por familia
    out["resumen_mediana"] = {
        f: {"3sigma": round(float(np.median([res[t][f]["3sigma"] for t in cols])), 3),
            "cross_asset": round(float(np.median([res[t][f]["cross_asset"] for t in cols])), 3)}
        for f in fams}
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_cross_asset_multi.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps({"resumen_mediana": out["resumen_mediana"],
                      "por_objetivo": {t: {f: v[f]["cross_asset"] for f in fams} for t, v in res.items()}},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
