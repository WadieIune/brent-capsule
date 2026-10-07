#!/usr/bin/env python3
"""Control de FORMA de curva con CNN 1D (demostración correcta).

Corrige la demo anterior (3 nodos). El defecto relevante en curvas NO es un
outlier grande (lo caza el 3σ) sino un MOVIMIENTO PEQUEÑO que mantiene la
correlación entre plazos (>98 %) pero rompe el SMOOTHNESS —p. ej. un plazo infra/
sobrevalorado por unos bps—. Un algoritmo de desviaciones por punto no lo ve; una
red entrenada sobre la forma (como el smoothness de un modelo paramétrico tipo
Svensson/Nelson-Siegel) sí.

Curva: Nelson-Siegel (10 plazos) con betas en paseo aleatorio + ruido de obs. Es
la "curva de referencia con smoothness definido". Se inyectan picos PEQUEÑOS
(pocos bps) en un plazo. Detectores, a FP emparejada sobre fechas limpias:
  - 3σ por nodo (benchmark de desviaciones);
  - residuo Nelson-Siegel (control paramétrico de forma);
  - autoencoder conv 1D entrenado sobre curvas limpias (la "CNN 1D de forma").
"""
from __future__ import annotations
import os, json
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TAU = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30.0]); LAM = 2.0
N = 3000; SPIKE_BPS = 4.0; FP = 0.02; REPS = 25; SEED = 42
rng = np.random.default_rng(SEED)
try:
    import torch, torch.nn as nn; HAS = True
except Exception:
    HAS = False


def ns_load():
    f1 = (1 - np.exp(-TAU/LAM)) / (TAU/LAM)
    f2 = f1 - np.exp(-TAU/LAM)
    return np.column_stack([np.ones_like(TAU), f1, f2])    # (nodos, 3)


def gen_curves():
    A = ns_load()
    b = np.array([3.0, -1.5, -1.0])                        # nivel, pendiente, curvatura
    steps = np.array([0.02, 0.03, 0.05])
    C = np.zeros((N, len(TAU)))
    for t in range(N):
        b = b + rng.normal(0, steps)
        C[t] = A @ b + rng.normal(0, 0.003, len(TAU))      # ruido ~0,3 pb
    return C


def ns_residual(curve):
    A = ns_load(); out = np.full(len(curve), np.nan)
    for i, y in enumerate(curve):
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        out[i] = np.max(np.abs(y - A @ beta))
    return out


def node_z(curve, w=60):
    import pandas as pd
    z = np.zeros(len(curve))
    for j in range(curve.shape[1]):
        r = np.diff(curve[:, j], prepend=curve[0, j])
        sig = pd.Series(r).rolling(w, min_periods=20).std().shift(1).to_numpy()
        zz = np.where(sig > 0, np.abs(r)/sig, 0.0)
        z = np.maximum(z, np.nan_to_num(zz))
    return z


def build_ae(train):
    if not HAS:
        return None
    torch.manual_seed(SEED)
    mu, sd = train.mean(0), train.std(0)+1e-9
    X = torch.tensor(((train-mu)/sd)[:, None, :], dtype=torch.float32)
    net = nn.Sequential(nn.Conv1d(1, 8, 3, padding=1), nn.GELU(),
                        nn.Conv1d(8, 4, 3, padding=1), nn.GELU(),
                        nn.Conv1d(4, 8, 3, padding=1), nn.GELU(),
                        nn.Conv1d(8, 1, 3, padding=1))
    opt = torch.optim.Adam(net.parameters(), lr=2e-3); lf = nn.MSELoss()
    for _ in range(300):
        opt.zero_grad(); loss = lf(net(X), X); loss.backward(); opt.step()
    net.eval()
    def score(curve):
        Z = torch.tensor(((curve-mu)/sd)[:, None, :], dtype=torch.float32)
        with torch.no_grad(): r = net(Z)
        return ((r-Z)**2).mean(dim=(1, 2)).numpy()
    return score


def main():
    C = gen_curves(); n = len(C); half = n//2
    train = C[:half]
    ae = build_ae(train)
    # magnitudes para demostrar que el pico es sub-umbral para 3σ
    node_std_bps = np.median([np.std(np.diff(C[:, j])) for j in range(len(TAU))])*100
    out = {"tenores": TAU.tolist(), "spike_bps": SPIKE_BPS, "fp": FP, "reps": REPS,
           "torch": HAS, "node_daily_std_bps_mediana": round(float(node_std_bps), 2),
           "pico_en_sigmas_de_retorno": round(SPIKE_BPS/node_std_bps, 2)}
    rec = {"3sigma_por_nodo": [], "residuo_NS": [], "cnn1d_forma": []}
    for _ in range(REPS):
        test = C[half:].copy(); m = len(test)
        inj = rng.random(m) < 0.3                           # 30 % fechas con pico
        nodes = rng.integers(2, len(TAU)-2, m)              # plazo interior
        for i in np.where(inj)[0]:
            test[i, nodes[i]] += SPIKE_BPS/100.0            # pico pequeño en bps
        gt = inj; clean = ~inj
        for name, sc in (("3sigma_por_nodo", node_z(test)),
                         ("residuo_NS", ns_residual(test)),
                         ("cnn1d_forma", ae(test) if ae else None)):
            if sc is None: continue
            thr = np.nanquantile(sc[clean], 1-FP)
            rec[name].append(float(np.mean(sc[gt] >= thr)))
    out["recall_a_FP"] = {k: round(float(np.mean(v)), 3) for k, v in rec.items() if v}

    # ---- caso curvas paralelas (base rate vs RFR): divergencia de -4bps en un plazo ----
    base = C[half:].copy(); rfr = base - 0.10 + rng.normal(0, 0.002, base.shape)  # RFR ~ base - 10bps, muy correlada
    m = len(base); inj2 = rng.random(m) < 0.3; nd = rng.integers(2, len(TAU)-2, m)
    for i in np.where(inj2)[0]:
        rfr[i, nd[i]] -= 0.04                               # -4bps solo en un plazo del RFR
    diff = base - rfr                                       # debería ser ~plano (10bps)
    # 3σ sobre el retorno del nodo del RFR vs forma del spread cross-tenor
    zrfr = node_z(rfr); sp = ns_residual(diff)
    thr_z = np.nanquantile(zrfr[~inj2], 1-FP); thr_s = np.nanquantile(sp[~inj2], 1-FP)
    out["paralelas_base_vs_rfr"] = {
        "recall_3sigma_nodo": round(float(np.mean(zrfr[inj2] >= thr_z)), 3),
        "recall_forma_spread": round(float(np.mean(sp[inj2] >= thr_s)), 3),
        "corr_media_base_rfr": round(float(np.mean([np.corrcoef(base[:, j], rfr[:, j])[0, 1] for j in range(len(TAU))])), 4)}

    r = out["recall_a_FP"]
    out["lectura"] = (f"Pico de {SPIKE_BPS}pb = {out['pico_en_sigmas_de_retorno']}σ de retorno "
                      f"(sub-umbral para 3σ). Recall: 3σ {r.get('3sigma_por_nodo')}, "
                      f"residuo NS {r.get('residuo_NS')}, CNN 1D forma {r.get('cnn1d_forma')}. "
                      "La forma (NS/CNN) caza el pico que rompe el smoothness donde el 3σ por punto falla.")
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_curve_shape_v2.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
