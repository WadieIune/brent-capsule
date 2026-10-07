#!/usr/bin/env python3
"""CNN 1D SUPERVISADA de forma de curva vs residuo Nelson-Siegel (baseline) y 3σ.

Mi autoencoder no supervisado fallaba; aquí la red se entrena SUPERVISADA sobre
los picos pequeños (como la CNN de B). Pregunta: ¿puede una CNN 1D aprender el
smoothness de la curva (sin conocer el modelo paramétrico) e igualar al residuo
Nelson-Siegel en detectar picos sub-3σ? Su valor sería ser agnóstica al modelo
(curvas donde NS está mal especificado: smile, segmentadas).

Protocolo limpio: train (inyección con etiquetas) -> umbral/FP en validación ->
recall en test. FP emparejada. Baselines: residuo NS y 3σ por nodo.
"""
from __future__ import annotations
import os, json
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TAU = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30.0]); LAM = 2.0
N = 4000; SPIKE_BPS = 4.0; FP = 0.02; SEED = 42
rng = np.random.default_rng(SEED)
import torch, torch.nn as nn


def ns_load():
    f1 = (1-np.exp(-TAU/LAM))/(TAU/LAM); f2 = f1 - np.exp(-TAU/LAM)
    return np.column_stack([np.ones_like(TAU), f1, f2])


def gen():
    A = ns_load(); b = np.array([3.0, -1.5, -1.0]); step = np.array([0.02, 0.03, 0.05])
    C = np.zeros((N, len(TAU)))
    for t in range(N):
        b = b + rng.normal(0, step); C[t] = A @ b + rng.normal(0, 0.003, len(TAU))
    return C


def ns_resid(curve):
    A = ns_load(); return np.array([np.max(np.abs(y - A @ np.linalg.lstsq(A, y, rcond=None)[0])) for y in curve])


def node_z(curve, w=60):
    import pandas as pd
    z = np.zeros(len(curve))
    for j in range(curve.shape[1]):
        r = np.diff(curve[:, j], prepend=curve[0, j])
        s = pd.Series(r).rolling(w, min_periods=20).std().shift(1).to_numpy()
        z = np.maximum(z, np.nan_to_num(np.where(s > 0, np.abs(r)/s, 0.0)))
    return z


def spike(curve):
    c = curve.copy(); lab = np.zeros(len(c))
    sel = rng.random(len(c)) < 0.5; nodes = rng.integers(2, len(TAU)-2, len(c))
    for i in np.where(sel)[0]:
        c[i, nodes[i]] += (SPIKE_BPS/100.0) * rng.choice([-1, 1]); lab[i] = 1
    return c, lab


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.b = nn.Sequential(nn.Conv1d(1, 16, 3, padding=1), nn.GELU(),
                               nn.Conv1d(16, 32, 3, padding=1), nn.GELU(), nn.AdaptiveMaxPool1d(1))
        self.h = nn.Linear(32, 1)
    def forward(self, x): return self.h(self.b(x).squeeze(-1)).squeeze(-1)


def main():
    C = gen(); a, b = N//2, 3*N//4
    tr, va, te = C[:a], C[a:b], C[b:]
    def shape(c): return c - c.mean(axis=1, keepdims=True)  # quita nivel, conserva forma
    torch.manual_seed(SEED)
    Xtr, ytr = spike(tr)
    net = Net(); opt = torch.optim.Adam(net.parameters(), 2e-3); lf = nn.BCEWithLogitsLoss()
    Xt = torch.tensor(shape(Xtr)[:, None, :], dtype=torch.float32); yt = torch.tensor(ytr, dtype=torch.float32)
    for _ in range(150):
        opt.zero_grad(); loss = lf(net(Xt), yt); loss.backward(); opt.step()
    net.eval()
    def cnn_score(curve):
        with torch.no_grad():
            return torch.sigmoid(net(torch.tensor(shape(curve)[:, None, :], dtype=torch.float32))).numpy()

    # umbral de cada detector calibrado en VALIDACIÓN (limpia) a FP
    Xva, yva = spike(va)
    def recall_fp(score_fn, Xtest, ytest, Xval):
        thr = np.quantile(score_fn(Xval), 1-FP)             # FP sobre val limpia
        s = score_fn(Xtest); return float(np.mean(s[ytest == 1] >= thr)), float(np.mean(s[ytest == 0] >= thr))
    Xte, yte = spike(te)
    out = {"spike_bps": SPIKE_BPS, "fp": FP, "n_test": len(te),
           "pico_sigma_retorno": round(SPIKE_BPS/ (np.median([np.std(np.diff(C[:, j])) for j in range(len(TAU))])*100), 2)}
    res = {}
    for name, fn in (("cnn1d_supervisada", cnn_score),
                     ("residuo_NS", lambda c: ns_resid(c)),
                     ("3sigma_por_nodo", lambda c: node_z(np.vstack([C[b-60:b], c]))[60:])):
        rec, fpr = recall_fp(fn, Xte, yte, va)
        res[name] = {"recall_test": round(rec, 3), "fp_test": round(fpr, 3)}
    out["resultados"] = res
    out["lectura"] = (f"CNN 1D supervisada recall {res['cnn1d_supervisada']['recall_test']} vs "
                      f"residuo NS {res['residuo_NS']['recall_test']} y 3σ {res['3sigma_por_nodo']['recall_test']}. "
                      + ("La CNN iguala al control paramétrico aprendiendo el smoothness de los datos."
                         if res['cnn1d_supervisada']['recall_test'] >= 0.9*res['residuo_NS']['recall_test']
                         else "La CNN no iguala al residuo NS; el control paramétrico sigue siendo superior."))
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_curve_cnn_supervised.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
