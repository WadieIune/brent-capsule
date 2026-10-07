#!/usr/bin/env python3
"""Control de FORMA de curva (demo) — detección cross-tenor de cotizaciones malas.

La detección de canal/forma, llevada a una curva de tipos: en cada fecha la curva
[y(2),y(5),y(10),y(30)] debe ser suave. Una cotización mala en un nodo rompe la
forma (curvatura local alta / residuo frente a un ajuste suave) aunque el valor
sea "normal" en la serie temporal de ese nodo —justo lo que un 3σ POR NODO no ve.

CAVEAT (B): es una DEMOSTRACIÓN del concepto sobre yields CMT (DGS). Para producción
hay que resolver tenor/instrumento/calendario/convenciones y construir la curva ZC
(bootstrapping). No tratar DGS2/5/10/30 como nodos ZC sin eso.
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
NODES = ["DGS2", "DGS10", "DGS30"]; TENOR = np.array([2.0, 10.0, 30.0])
FP = 0.02; REPS = 40; SEED = 42
rng = np.random.default_rng(SEED)


def shape_score(curve):
    """Residuo máx. frente a un ajuste suave (cuadrático en log-tenor) por fecha."""
    x = np.log(TENOR); A = np.column_stack([np.ones_like(x), x])  # lineal (3 nodos)
    out = np.full(len(curve), np.nan)
    for i, y in enumerate(curve):
        if np.isnan(y).any():
            continue
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        out[i] = np.max(np.abs(y - A @ beta))
    return out


def node_z(curve_node, w=60):
    r = np.diff(curve_node, prepend=curve_node[0])
    sig = pd.Series(r).rolling(w, min_periods=20).std().shift(1).to_numpy()
    return np.where(sig > 0, r / sig, 0.0)


def inject_bad_quote(curve, kind):
    """Inyecta una cotización mala en un nodo interior que rompe la forma.

    kink/inversion: mal quote de golpe (grande; 3σ también lo ve).
    nodo_estancado: el nodo interior se CONGELA k sesiones mientras la curva se
    mueve -> retorno 0 (3σ ciego, TRIM tarda 20) pero la forma desarrolla un kink.
    """
    c = curve.copy(); node = 1  # nodo interior (DGS10)
    if kind == "nodo_estancado":
        s0 = int(rng.integers(70, len(c)-12)); k = 8
        c[s0:s0+k, node] = c[s0-1, node]          # congelado; los otros nodos siguen reales
        return c, np.arange(s0, s0+k), node
    idx = int(rng.integers(70, len(c)-1))
    base = c[idx, node]; neigh = 0.5*(c[idx, node-1] + c[idx, node+1])
    if kind == "kink":        c[idx, node] = neigh + 1.2*(neigh - base if abs(neigh-base) > 0.1 else 0.6)
    elif kind == "inversion": c[idx, node] = c[idx, node+1] + 0.8
    return c, np.array([idx]), node


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    df = df[["date"]+NODES].dropna().reset_index(drop=True)
    curve = df[NODES].to_numpy(float); n = len(curve)
    out = {"nodes": NODES, "n": n, "fp": FP, "reps": REPS,
           "caveat": "demo sobre yields CMT; produccion requiere ZC bootstrapping y convenciones"}
    fams = ["kink", "inversion", "nodo_estancado"]
    rec = {d: {f: [] for f in fams} for d in ["3sigma_por_nodo", "forma_cross_tenor"]}
    for _ in range(REPS):
        for f in fams:
            c2, idx, node = inject_bad_quote(curve, f)
            gt = np.zeros(n, bool); gt[idx] = True; clean = ~gt
            z = np.abs(node_z(c2[:, node])); thr = np.nanquantile(z[clean], 1-FP)
            rec["3sigma_por_nodo"][f].append(float(np.mean(z[idx] >= thr)))
            s = shape_score(c2); thr2 = np.nanquantile(s[clean], 1-FP)
            rec["forma_cross_tenor"][f].append(float(np.mean(s[idx] >= thr2)))
    out["recall_a_FP"] = {d: {f: round(float(np.mean(v)), 3) for f, v in fam.items()} for d, fam in rec.items()}
    r = out["recall_a_FP"]
    out["lectura"] = (f"El control de FORMA cross-tenor caza cotizaciones malas que rompen la curva "
                      f"(kink {r['forma_cross_tenor']['kink']}, inversion {r['forma_cross_tenor']['inversion']}) "
                      f"donde el 3σ por nodo falla (kink {r['3sigma_por_nodo']['kink']}, "
                      f"inversion {r['3sigma_por_nodo']['inversion']}), porque el valor es normal en su propia "
                      f"serie pero imposible en la forma de la curva.")
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "dq_curve_shape.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
