#!/usr/bin/env python3
"""Baseline cross-asset con el PROTOCOLO EXACTO de la CNN 1D supervisada de B.

Mismo universo (6 commodities = pares naturales), misma ventana, mismos cortes,
y —clave para que la comparación sea justa— el umbral de alerta se calibra en
VALIDACIÓN cronológica (no en test), igual que B. Da el recall por familia y por
objetivo que la CNN supervisada debe BATIR a FP emparejada.
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ASSETS = ["BRENT", "WTI", "GOLD", "SILVER", "COPPER", "NATGAS"]   # universo de B
W = 20; STRIDE_TR = 5; FIT_END = pd.Timestamp("2018-12-31"); VAL_END = pd.Timestamp("2020-08-20")
FP = 0.05; REPS = 30; SEED = 42
rng = np.random.default_rng(SEED)


def wins(R, lo, hi, stride):
    return np.array([R[t:t+W] for t in range(lo, hi-W, stride)])


def cross_1mr2(win, col, peers):
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
    if kind == "decoupling":        w[:, col] = rng.normal(0, w[:, col].std()+1e-9, W)
    elif kind == "stale":           w[:, col] = 0.0
    elif kind == "reversible_jump": j = rng.integers(2, W-2); w[j, col] += 8; w[j+1, col] -= 8
    return w


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    df = df[["date"]+ASSETS].dropna().reset_index(drop=True)
    dr = pd.DatetimeIndex(df["date"])[1:]
    R = np.diff(np.log(np.clip(df[ASSETS].to_numpy(float), 1e-6, None)), axis=0)
    tr = np.asarray(dr <= FIT_END); mu, sd = R[tr].mean(0), R[tr].std(0)+1e-9; Rz = (R-mu)/sd
    rb = lambda m: (int(np.where(m)[0][0]), int(np.where(m)[0][-1])+1)
    val = np.asarray((dr > FIT_END) & (dr <= VAL_END)); tes = np.asarray(dr > VAL_END)
    lo_v, hi_v = rb(val); lo_t, hi_t = rb(tes)
    val_win = wins(Rz, lo_v, hi_v, W); test_win = wins(Rz, lo_t, hi_t, W)
    fams = ["decoupling", "stale", "reversible_jump"]
    out = {"protocolo": "igual que dq_cnn1d_supervised (umbral en VAL, recall en test)",
           "universo": ASSETS, "W": W, "fp": FP, "n_val": len(val_win), "n_test": len(test_win)}
    res = {}
    for ci, tgt in enumerate(ASSETS):
        peers = [j for j in range(len(ASSETS)) if j != ci]
        # umbral calibrado en VALIDACIÓN limpia a FP
        thr = float(np.quantile(cross_1mr2(val_win, ci, peers), 1-FP))
        fam_rec = {}
        for f in fams:
            recs, fps = [], []
            for _ in range(REPS):
                m = len(test_win); perm = rng.permutation(m); h = m//2
                clean = test_win[perm[:h]]; inj = perm[h:]
                sc_clean = cross_1mr2(clean, ci, peers)
                dw = np.array([inject(test_win[i], ci, f) for i in inj])
                sc_def = cross_1mr2(dw, ci, peers)
                recs.append(float(np.mean(sc_def >= thr)))
                fps.append(float(np.mean(sc_clean >= thr)))
            fam_rec[f] = {"recall_test": round(float(np.mean(recs)), 3),
                          "fp_test_real": round(float(np.mean(fps)), 3)}
        res[tgt] = fam_rec
    out["baseline_a_batir_por_la_CNN"] = res
    out["mediana_recall"] = {f: round(float(np.median([res[t][f]["recall_test"] for t in ASSETS])), 3) for f in fams}
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_cross_asset_baseline.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps({"mediana_recall": out["mediana_recall"], "por_objetivo": res}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
