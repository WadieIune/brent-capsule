#!/usr/bin/env python3
"""DQ-IA · gate barato — ¿un control cross-asset bate a 3σ donde 3σ es ciego?

Inyecta defectos con GROUND TRUTH sobre BRENT (usando sus pares correlacionados),
y compara detectores a IGUAL tasa de falsos positivos (1 % sobre días limpios):
  - 3σ sobre log-rendimientos (BENCHMARK estándar);
  - TRIM repetidos consecutivos (rendimiento 0), alerta si racha ≥ 20;
  - cross-asset: residuo de regresión causal de la serie sobre sus pares.

Familias de defecto: racha estancada (stale), repetidos ≥20 (P&L mensual),
salto imposible (print que revierte), decoplamiento cross-asset.
Si el cross-asset recupera recall donde 3σ da ~0 (stale/repetidos/decoplamiento),
queda justificada una CNN 1D cross-asset. Estricto: umbrales causales, FP emparejada.
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TARGET = "BRENT"; PEERS = ["WTI", "GOLD", "SILVER", "COPPER", "NATGAS", "DTWEXBGS"]
WIN = 120; FP_TARGET = 0.01; SEED = 42
rng = np.random.default_rng(SEED)


def rolling_sigma(r, w=60):
    return pd.Series(r).rolling(w, min_periods=20).std().shift(1).to_numpy()


def cross_asset_resid(rt, RP, w=WIN):
    """Residuo z causal: regresión de rt sobre pares en ventana [t-w, t-1]."""
    n = len(rt); z = np.full(n, np.nan)
    for t in range(w, n):
        X = RP[t-w:t]; y = rt[t-w:t]
        m = ~(np.isnan(X).any(1) | np.isnan(y))
        if m.sum() < 40: continue
        Xo = np.column_stack([np.ones(m.sum()), X[m]])
        try:
            beta, *_ = np.linalg.lstsq(Xo, y[m], rcond=None)
            res = y[m] - Xo @ beta; s = res.std()
            xt = RP[t]
            if np.isnan(xt).any() or s < 1e-9: continue
            pred = beta[0] + beta[1:] @ xt
            z[t] = (rt[t] - pred) / s
        except Exception:
            continue
    return z


def zero_run_len(r):
    """Longitud de la racha de ceros que termina en t (incluye t)."""
    n = len(r); run = np.zeros(n, int); c = 0
    for t in range(n):
        c = c + 1 if (r[t] == 0) else 0
        run[t] = c
    return run


def inject(rt, RP, kind, L):
    """Devuelve (serie defectuosa, índices ground-truth)."""
    r = rt.copy(); n = len(r); s0 = int(rng.integers(WIN+50, n-L-50))
    idx = np.arange(s0, s0+L)
    if kind == "stale":                      # precio congelado -> rendimiento 0
        r[idx] = 0.0
    elif kind == "repetidos20":              # racha de 0 de >=20 (P&L mensual)
        r[idx] = 0.0
    elif kind == "salto":                    # print imposible que revierte
        sg = rng.choice([-1, 1]); r[s0] += sg*8*np.nanstd(rt); r[s0+1] -= sg*8*np.nanstd(rt); idx = np.array([s0, s0+1])
    elif kind == "decoplamiento":            # serie se mueve sin relación con pares
        r[idx] = rng.normal(0, np.nanstd(rt), L)
    return r, idx


def flags_at_fp(score, clean_mask, fp=FP_TARGET, absval=True):
    s = np.abs(score) if absval else score
    thr = np.nanquantile(s[clean_mask], 1-fp)
    return (s >= thr), thr


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    cols = [TARGET]+PEERS; df = df[["date"]+cols].dropna().reset_index(drop=True)
    px = df[cols].to_numpy(float)
    R = np.diff(np.log(np.clip(px, 1e-6, None)), axis=0)
    rt0 = R[:, 0]; RP = R[:, 1:]
    n = len(rt0)
    fams = {"stale": 10, "repetidos20": 22, "salto": 2, "decoplamiento": 15}
    REPS = 60
    out = {"target": TARGET, "peers": PEERS, "fp_target": FP_TARGET, "reps": REPS, "n": n}
    rec = {d: {f: [] for f in fams} for d in ["3sigma", "trim_czeros", "cross_asset"]}
    for f, L in fams.items():
        for _ in range(REPS):
            r, idx = inject(rt0, RP, f, L)
            gt = np.zeros(n, bool); gt[idx] = True
            clean = ~gt
            # 3 sigma (causal)
            sig = rolling_sigma(r); z3 = np.where(sig > 0, r/sig, 0.0)
            fl3, _ = flags_at_fp(np.nan_to_num(z3), clean)
            # TRIM consecutivos a 0 (umbral emparejado a FP sobre racha)
            run = zero_run_len(r).astype(float)
            flT, _ = flags_at_fp(run, clean)
            # cross-asset
            za = cross_asset_resid(r, RP); flX, _ = flags_at_fp(np.nan_to_num(za), clean)
            rec["3sigma"][f].append(fl3[gt].mean())
            rec["trim_czeros"][f].append(flT[gt].mean())
            rec["cross_asset"][f].append(flX[gt].mean())
    out["recall_por_familia_a_FP_1pct"] = {
        d: {f: round(float(np.mean(v)), 3) for f, v in fam.items()} for d, fam in rec.items()}
    # lectura
    s3 = out["recall_por_familia_a_FP_1pct"]["3sigma"]
    sx = out["recall_por_familia_a_FP_1pct"]["cross_asset"]
    sT = out["recall_por_familia_a_FP_1pct"]["trim_czeros"]
    out["lectura"] = {
        "3sigma_ciego_en": [f for f in fams if s3[f] < 0.2],
        "cross_asset_recupera": {f: round(sx[f]-s3[f], 3) for f in fams},
        "trim_capta_repetidos": sT["repetidos20"],
        "veredicto": ("El cross-asset recupera recall donde 3σ es ciego → justifica la CNN 1D cross-asset"
                      if any(sx[f]-s3[f] > 0.2 for f in ("stale","decoplamiento","repetidos20")) else
                      "El cross-asset no aporta sobre 3σ"),
    }
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_ia_gate.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
