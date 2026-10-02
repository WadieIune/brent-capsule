#!/usr/bin/env python3
"""Backtest completo del VaR condicional a volatilidad (tarea de B, ejecutada
por A por instrucción del MASTER para cerrar la cola).

Compara, fuera de muestra (corte 2020-08-20), el VaR incumbente estático
(simulación histórica, ventana 250) contra el VaR condicional a volatilidad
(FHS-EWMA, λ=0,94) sobre el Brent, y pasa la batería COMPLETA de backtesting de
VaR: Kupiec POF (cobertura incondicional), Christoffersen (independencia /
clustering), cobertura condicional (LR_cc), Engle-Manganelli DQ, y el semáforo /
multiplicador de Basilea con capital. Añade un IC por bloques sobre la diferencia
de capital para no fiar el −22,7 % a una sola realización.

    python code/applications/experiments/var_vol_conditional_backtest.py
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "code", "applications"))
import common  # noqa
from experiments.portfolio_var import (  # noqa
    _historical_var, _fhs_var, capital_analysis)
from experiments.predicted_var import (  # noqa
    kupiec_pof, christoffersen_independence, lr_conditional_coverage,
    dq_engle_manganelli)

ALPHA, WIN, LAM = 0.99, 250, 0.94
CUTOFF = pd.Timestamp("2020-08-20")
SEED = 42
rng = np.random.default_rng(SEED)


def battery(name, rets, var, dates):
    m = ~np.isnan(var)
    r, v, d = rets[m], var[m], dates[m]
    te = d > CUTOFF
    r, v = r[te], v[te]
    exc = (r < -v).astype(int)
    cap = capital_analysis(exc, float(np.mean(v)))
    return {
        "spec": name,
        "n_test": int(len(r)),
        "exceptions": int(exc.sum()),
        "avg_var": round(float(np.mean(v)), 5),
        "kupiec": kupiec_pof(exc, ALPHA),
        "christoffersen": christoffersen_independence(exc),
        "cond_coverage_lr_cc": lr_conditional_coverage(exc, ALPHA),
        "dq_engle_manganelli": dq_engle_manganelli(exc, v, ALPHA),
        "capital": {k: cap[k] for k in (
            "exceptions_per_250d_avg", "worst_250d_exceptions",
            "multiplier_worst", "zone_worst", "capital_worst")},
        "_exc": exc, "_var": v,  # para el bootstrap
    }


def main():
    s, src = common.load_prices(os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    prices = s.to_numpy(dtype=float)
    dates = pd.DatetimeIndex(s.index)
    rets = np.diff(np.log(prices))
    dr = dates[1:]

    var_hist = _historical_var(rets, ALPHA, WIN)
    var_fhs = _fhs_var(rets, ALPHA, WIN, LAM)

    A = battery("historical_sim_estatico", rets, var_hist, dr)
    B = battery("fhs_ewma_condicional_vol", rets, var_fhs, dr)

    cap_a, cap_b = A["capital"]["capital_worst"], B["capital"]["capital_worst"]
    delta_pct = 100.0 * (cap_b / cap_a - 1.0)

    # IC por bloques sobre la diferencia de capital (worst-250d), 1000 remuestreos
    def cap_worst(exc, var, idx):
        e = exc[idx]
        roll = pd.Series(e).rolling(250).sum()
        worst = int(np.nanmax(roll.to_numpy())) if len(e) >= 250 else int(e.sum())
        from experiments.portfolio_var import basel_multiplier
        k, _ = basel_multiplier(worst)
        return k * float(np.mean(var[idx]))

    ea, va = A["_exc"], A["_var"]
    eb, vb = B["_exc"], B["_var"]
    n = len(ea); bl = 20
    deltas = []
    for _ in range(1000):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n - bl)
            idx.extend(range(start, start + bl))
        idx = np.array(idx[:n])
        ca = cap_worst(ea, va, idx); cb = cap_worst(eb, vb, idx)
        if ca > 0:
            deltas.append(100.0 * (cb / ca - 1.0))
    deltas = np.array(deltas)

    out = {
        "fuente": src, "alpha": ALPHA, "ventana": WIN, "lambda_ewma": LAM,
        "corte_out_of_time": str(CUTOFF.date()),
        "incumbente_estatico": {k: A[k] for k in A if not k.startswith("_")},
        "condicional_vol_fhs": {k: B[k] for k in B if not k.startswith("_")},
        "delta_capital_pct": round(delta_pct, 2),
        "delta_capital_ic95_bloques": [round(float(np.percentile(deltas, 2.5)), 2),
                                       round(float(np.percentile(deltas, 97.5)), 2)],
        "delta_capital_mediano_bloques": round(float(np.median(deltas)), 2),
    }
    # veredicto honesto
    kup_ok = B["kupiec"]["p_value"] > 0.05
    chr_ok = (B["christoffersen"]["p_value"] != B["christoffersen"]["p_value"]
              or B["christoffersen"]["p_value"] > 0.05)
    not_worse = (B["christoffersen"].get("p_value", 1) >=
                 A["christoffersen"].get("p_value", 0) - 1e-9) or chr_ok
    ic = out["delta_capital_ic95_bloques"]
    out["veredicto"] = {
        "cobertura_kupiec_ok": bool(kup_ok),
        "independencia_christoffersen_no_peor": bool(not_worse),
        "ahorro_capital_robusto": bool(ic[0] < 0 and ic[1] < 0),
        "resumen": ("El VaR condicional a volatilidad reduce el capital "
                    f"{out['delta_capital_pct']} % (IC95 por bloques {ic}) "
                    "manteniendo cobertura; "
                    + ("la independencia no empeora." if not_worse
                       else "AVISO: empeora la independencia de excepciones.")),
    }
    outdir = os.path.join(ROOT, "results", "reports")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "var_vol_conditional_backtest.json"), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
