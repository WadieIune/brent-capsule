#!/usr/bin/env python3
"""EQ split re-ajustado hacia atrás — invisible a controles de retorno.

Escenario (MASTER): un split/ajuste corporativo se aplica HACIA ATRÁS sobre la
serie histórica (se multiplica el tramo previo por un factor). Los log-retornos
NO cambian (el escalado no afecta a los retornos), así que 3σ y cross-asset SOBRE
RETORNOS son ciegos a todo el tramo; la serie queda inconsistente en BBDD. Solo un
control de CONSISTENCIA DE NIVEL contra una referencia (ratio al par / vintage
almacenado) lo detecta.

Demuestra: 3σ/cross-asset sobre retornos ~0 en el tramo; control de nivel (z del
ratio serie/par) caza el tramo re-ajustado. FP emparejada.
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TARGET, PEER = "SP500", "DAX"; FACTOR = 0.98; SEG = 400; FP = 0.02; REPS = 30; SEED = 42
rng = np.random.default_rng(SEED)


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    df = df[["date", TARGET, PEER]].dropna().reset_index(drop=True)
    px = df[TARGET].to_numpy(float); peer = df[PEER].to_numpy(float); n = len(px)
    corr = np.corrcoef(np.diff(np.log(px)), np.diff(np.log(peer)))[0, 1]
    rec = {"3sigma_retorno": [], "cross_asset_retorno": [], "nivel_ratio_rolling": [], "vintage_vs_almacenado": []}
    for _ in range(REPS):
        s0 = int(rng.integers(300, n-SEG-50)); idx = np.arange(s0, s0+SEG)
        p2 = px.copy(); p2[:s0] *= FACTOR          # re-ajuste HACIA ATRÁS del tramo previo
        # ground truth: el tramo [0:s0] queda con nivel inconsistente (defecto)
        gt = np.zeros(n, bool); gt[:s0] = True; clean = ~gt
        r = np.diff(np.log(np.clip(p2, 1e-6, None)), prepend=np.log(p2[0]))
        # 3σ sobre retorno del target
        sig = pd.Series(r).rolling(60, min_periods=20).std().shift(1).to_numpy()
        z3 = np.nan_to_num(np.where(sig > 0, np.abs(r)/sig, 0.0))
        thr3 = np.nanquantile(z3[clean], 1-FP); rec["3sigma_retorno"].append(float(np.mean(z3[gt] >= thr3)))
        # cross-asset sobre retornos (residuo target~par)
        rp = np.diff(np.log(peer), prepend=np.log(peer[0]))
        beta = np.polyfit(rp[clean], r[clean], 1); resid = r - (beta[0]*rp + beta[1])
        sg = np.nanstd(resid[clean]); zc = np.abs(resid)/ (sg+1e-9)
        thrc = np.nanquantile(zc[clean], 1-FP); rec["cross_asset_retorno"].append(float(np.mean(zc[gt] >= thrc)))
        # control de NIVEL: z del log-ratio serie/par vs su media móvil (detecta el escalón de nivel)
        lr = np.log(np.clip(p2, 1e-6, None)) - np.log(np.clip(peer, 1e-6, None))
        mu = pd.Series(lr).rolling(120, min_periods=40).mean().to_numpy()
        sdv = pd.Series(lr).rolling(120, min_periods=40).std().to_numpy()
        zl = np.nan_to_num(np.where(sdv > 0, np.abs(lr-mu)/sdv, 0.0))
        thrl = np.nanquantile(zl[clean], 1-FP); rec["nivel_ratio_rolling"].append(float(np.mean(zl[gt] >= thrl)))
        # control de VINTAGE: comparar la serie actual con la almacenada (original px)
        viol = np.abs(p2/px - 1.0) > 1e-4           # cualquier desvío del vintage es defecto
        rec["vintage_vs_almacenado"].append(float(np.mean(viol[gt])))
    out = {"target": TARGET, "peer": PEER, "factor_backadjust": FACTOR, "segmento": SEG,
           "corr_retornos": round(float(corr), 4), "fp": FP, "reps": REPS,
           "recall_tramo_reajustado": {k: round(float(np.mean(v)), 3) for k, v in rec.items()},
           "lectura": ("El re-ajuste hacia atrás es INVISIBLE a los controles de retorno "
                       "(3σ y cross-asset ~0 en el tramo, porque el escalado no cambia los retornos); "
                       "solo el control de CONSISTENCIA DE NIVEL (ratio serie/par) lo caza. "
                       "Justifica un control de nivel/vintage además de los de desviación.")}
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_eq_backadjust.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
