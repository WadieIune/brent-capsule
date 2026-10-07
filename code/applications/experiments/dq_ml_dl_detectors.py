#!/usr/bin/env python3
"""DQ control con ML/DL a nivel de VENTANA — enfoque en decoplamiento.

El gate barato mostró que 3σ y un cross-asset lineal por día son débiles ante el
DECOPLAMIENTO (correlación rota). Aquí se evalúan detectores a nivel de ventana,
entrenados SOLO con ventanas limpias de train, y se comparan a IGUAL tasa de
falsos positivos sobre ventanas limpias de test:

  - 3σ (benchmark)                      : máx |z| en la ventana.
  - cross-asset ventana (stat reforzado): 1 - R² de target~pares en la ventana.
  - IsolationForest (ML)                : sobre la ventana multivariante aplanada.
  - Autoencoder conv 1D (DL)            : error de reconstrucción de la ventana.

Ground truth por inyección (decoplamiento / stale / salto). Estricto: estandarizado
y modelos ajustados SOLO en train; FP emparejada; REPS repeticiones.
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ASSETS = ["BRENT", "WTI", "GOLD", "SILVER", "COPPER", "NATGAS"]
W = 20; STRIDE_TR = 5; FIT_END = pd.Timestamp("2018-12-31"); VAL_END = pd.Timestamp("2020-08-20")
FP = 0.05; REPS = 30; SEED = 42
rng = np.random.default_rng(SEED)
try:
    import torch, torch.nn as nn
    HAS_TORCH = True
except Exception:
    HAS_TORCH = False
from sklearn.ensemble import IsolationForest


def windows(R, idx_lo, idx_hi, stride):
    return np.array([R[t:t+W] for t in range(idx_lo, idx_hi - W, stride)])  # (m, W, A)


def score_3sigma(win):           # win: (m,W,A) estandarizado
    return np.max(np.abs(win), axis=(1, 2))


def score_crossasset(win):       # 1 - R² de BRENT ~ pares por ventana
    out = []
    for w in win:
        y = w[:, 0]; X = w[:, 1:]
        Xo = np.column_stack([np.ones(len(y)), X])
        beta, *_ = np.linalg.lstsq(Xo, y, rcond=None)
        res = y - Xo @ beta
        ss = np.sum((y - y.mean())**2)
        r2 = 1 - np.sum(res**2) / ss if ss > 1e-12 else 0.0
        out.append(1 - r2)
    return np.array(out)


def build_ae(tr_win):
    """Entrena el autoencoder conv 1D UNA vez con ventanas limpias de train y
    devuelve un scorer (error de reconstrucción por ventana)."""
    if not HAS_TORCH:
        return None
    torch.manual_seed(SEED)
    Xtr = torch.tensor(tr_win.transpose(0, 2, 1), dtype=torch.float32)   # (m, A, W)
    A = Xtr.shape[1]
    net = nn.Sequential(
        nn.Conv1d(A, 16, 3, padding=1), nn.ReLU(), nn.Conv1d(16, 8, 3, padding=1), nn.ReLU(),
        nn.Conv1d(8, 16, 3, padding=1), nn.ReLU(), nn.Conv1d(16, A, 3, padding=1))
    opt = torch.optim.Adam(net.parameters(), lr=1e-3); lossf = nn.MSELoss()
    net.train()
    for ep in range(120):
        opt.zero_grad(); out = net(Xtr); loss = lossf(out, Xtr); loss.backward(); opt.step()
    net.eval()
    def mse(win):
        X = torch.tensor(win.transpose(0, 2, 1), dtype=torch.float32)
        with torch.no_grad():
            rec = net(X)
        return ((rec - X)**2).mean(dim=(1, 2)).numpy()
    return mse


def inject(win, kind):
    w = win.copy()
    if kind == "decoplamiento":
        w[:, 0] = rng.normal(0, w[:, 0].std() + 1e-9, W)      # BRENT se desacopla
    elif kind == "stale":
        w[:, 0] = 0.0
    elif kind == "salto":
        j = rng.integers(2, W-2); w[j, 0] += 8.0; w[j+1, 0] -= 8.0
    return w


def recall_at_fp(scores_clean, scores_def, fp=FP):
    thr = np.quantile(scores_clean, 1 - fp)
    return float(np.mean(scores_def >= thr))


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    df = df[["date"] + ASSETS].dropna().reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"]); px = df[ASSETS].to_numpy(float)
    R = np.diff(np.log(np.clip(px, 1e-6, None)), axis=0); dr = dates[1:]
    # estandarización por activo SOLO con train
    tr = np.asarray(dr <= FIT_END)
    mu = R[tr].mean(0); sd = R[tr].std(0) + 1e-9; Rz = (R - mu) / sd
    lo_f, hi_f = 0, int(np.argmax(~tr)) if (~tr).any() else len(R)
    te = np.asarray(dr > VAL_END); lo_t = int(np.argmax(te)); hi_t = len(R)

    tr_win = windows(Rz, lo_f, hi_f, STRIDE_TR)           # limpias (train)
    te_win = windows(Rz, lo_t, hi_t, W)                   # no solapadas (test)
    out = {"assets": ASSETS, "W": W, "n_train_win": len(tr_win), "n_test_win": len(te_win),
           "fp": FP, "reps": REPS, "torch": HAS_TORCH}

    # precomputar scores base de test limpio
    base = {"3sigma": score_3sigma, "cross_asset_win": score_crossasset}
    iso = IsolationForest(random_state=SEED, n_estimators=200).fit(tr_win.reshape(len(tr_win), -1))
    def iso_score(win): return -iso.decision_function(win.reshape(len(win), -1))
    ae_mse = build_ae(tr_win)       # entrenado UNA vez

    fams = ["decoplamiento", "stale", "salto"]
    detectors = ["3sigma", "cross_asset_win", "isolation_forest_ML", "autoencoder_DL"]
    res = {d: {f: [] for f in fams} for d in detectors}
    for _ in range(REPS):
        # subset de ventanas limpias de test para calibrar FP (mitad), resto para inyectar
        m = len(te_win); perm = rng.permutation(m); half = m // 2
        clean_idx, inj_idx = perm[:half], perm[half:]
        clean = te_win[clean_idx]
        sc_clean = {"3sigma": score_3sigma(clean), "cross_asset_win": score_crossasset(clean),
                    "isolation_forest_ML": iso_score(clean)}
        ae_c = ae_mse(clean) if ae_mse else None
        if ae_c is not None: sc_clean["autoencoder_DL"] = ae_c
        for f in fams:
            dw = np.array([inject(te_win[i], f) for i in inj_idx])
            sc_def = {"3sigma": score_3sigma(dw), "cross_asset_win": score_crossasset(dw),
                      "isolation_forest_ML": iso_score(dw)}
            ae_d = ae_mse(dw) if ae_mse else None
            if ae_d is not None: sc_def["autoencoder_DL"] = ae_d
            for d in detectors:
                if d in sc_clean and d in sc_def:
                    res[d][f].append(recall_at_fp(sc_clean[d], sc_def[d]))
    out["recall_por_familia_a_FP"] = {d: {f: round(float(np.mean(v)), 3) if v else None for f, v in fam.items()}
                                      for d, fam in res.items()}
    # veredicto: ¿ML/DL baten a 3σ y al cross-asset en decoplamiento?
    r = out["recall_por_familia_a_FP"]
    best_stat = max(r["3sigma"]["decoplamiento"], r["cross_asset_win"]["decoplamiento"])
    ml = r["isolation_forest_ML"]["decoplamiento"]; dl = r.get("autoencoder_DL", {}).get("decoplamiento")
    out["veredicto_decoplamiento"] = {
        "mejor_estadistico": round(best_stat, 3), "isolation_forest": ml, "autoencoder": dl,
        "ML_DL_mejora": bool(max([x for x in (ml, dl) if x is not None], default=0) > best_stat + 0.1),
        "lectura": ("ML/DL mejora el decoplamiento sobre 3σ/cross-asset -> justifica la capa de IA en DQ"
                    if max([x for x in (ml, dl) if x is not None], default=0) > best_stat + 0.1
                    else "ML/DL no mejora de forma clara sobre el cross-asset de ventana"),
    }
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_ml_dl_detectors.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
