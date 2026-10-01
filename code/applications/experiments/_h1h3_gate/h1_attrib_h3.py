#!/usr/bin/env python3
"""Cierre honesto de H1 (atribución del capital) + H3 barato.

1. ¿La mejora de capital del overlay viene de la geometría o de la volatilidad?
   Se compara el overlay guiado por el modelo SOLO-VOL contra el guiado por
   geometría. Si igualan, el capital lo mueve la vol, no la forma.
2. H3: ¿condicionar el VaR/ES a la volatilidad (EWMA-FHS) reduce el capital
   frente al VaR estático, a cobertura aceptable? Es la palanca real.
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "code", "applications"))
import common  # noqa
from experiments.portfolio_var import (  # noqa
    _historical_var, _fhs_var, capital_analysis, basel_multiplier)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ALPHA, WIN, CUTOFF = 0.99, 250, pd.Timestamp("2020-08-20")
VOL_PROXIES = ["vol20", "atr_norm", "resid_norm", "band_width"]
PURE_GEOM = ["dir_asc", "slope_norm", "r2", "accel", "n_turn", "pos_in_channel"]

sys.argv = sys.argv[:1]
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "h1_cheap.py"))
     .read().split("def main()")[0])  # reutiliza load_brent, build_table, fit_eval


def kupiec_ok(exc, alpha=ALPHA):
    n = len(exc); x = int(exc.sum()); pe = 1 - alpha
    rate = x / n if n else float("nan")
    return rate, (0.5 * pe <= rate <= 2.0 * pe)  # cobertura "razonable"


def overlay_capital(te, p, scale=1.40, q=0.90):
    thr = np.quantile(p, q)
    mult = np.where(p >= thr, scale, 1.0)
    ret = te["ret"].to_numpy(); var = te["var"].to_numpy()
    exc = (ret < -(var * mult)).astype(int)
    cap = capital_analysis(exc, float(np.mean(var * mult)))
    rate, ok = kupiec_ok(exc)
    return {"worst_250d": cap["worst_250d_exceptions"],
            "mult_worst": cap["multiplier_worst"], "zone": cap["zone_worst"],
            "capital_worst": cap["capital_worst"],
            "exc_rate": round(rate, 4), "kupiec_ok": bool(ok)}


def main2():
    prices, dates, src = load_brent()
    df, rets = build_table(prices, dates)
    base_cols = ["vol", "var", "exc_prev"]
    _, pA, te = fit_eval(df, base_cols)                       # solo vol
    _, pB, _ = fit_eval(df, base_cols + VOL_PROXIES + PURE_GEOM)  # +geometría

    out = {"source": src}
    # ---- 1. atribución del overlay ----
    ret = te["ret"].to_numpy(); var = te["var"].to_numpy()
    exc_base = (ret < -var).astype(int)
    cap_base = capital_analysis(exc_base, float(np.mean(var)))
    out["H1_atribucion_capital"] = {
        "incumbente_estatico": {
            "worst_250d": cap_base["worst_250d_exceptions"],
            "mult_worst": cap_base["multiplier_worst"],
            "capital_worst": cap_base["capital_worst"]},
        "overlay_SOLO_VOL": overlay_capital(te, pA),
        "overlay_CON_GEOMETRIA": overlay_capital(te, pB),
        "lectura": "si solo-vol iguala a con-geometria, el capital lo mueve la vol",
    }

    # ---- 2. H3: VaR estatico vs condicional a vol (EWMA-FHS) ----
    var_fhs = _fhs_var(rets, ALPHA, WIN, 0.94)
    var_hist = _historical_var(rets, ALPHA, WIN)
    mask = pd.Series(dates[1:]) > CUTOFF
    mask = mask.to_numpy()
    r_te = rets[mask]
    def spec(name, v):
        v_te = v[mask]
        good = ~np.isnan(v_te)
        exc = (r_te[good] < -v_te[good]).astype(int)
        cap = capital_analysis(exc, float(np.nanmean(v_te[good])))
        rate, ok = kupiec_ok(exc)
        return {"spec": name, "avg_var": round(float(np.nanmean(v_te[good])), 5),
                "worst_250d": cap["worst_250d_exceptions"],
                "mult_worst": cap["multiplier_worst"], "zone": cap["zone_worst"],
                "capital_worst": cap["capital_worst"],
                "exc_rate": round(rate, 4), "kupiec_ok": bool(ok)}
    out["H3_estatico_vs_condicional_vol"] = {
        "estatico_historico": spec("historical_sim", var_hist),
        "condicional_vol_fhs_ewma": spec("fhs_ewma", var_fhs),
        "lectura": "capital_worst menor con cobertura ok = la palanca es la vol",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main2()
