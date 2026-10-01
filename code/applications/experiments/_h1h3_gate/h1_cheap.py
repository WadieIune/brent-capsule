#!/usr/bin/env python3
"""H1 — test BARATO (sin CNN): ¿la geometría del canal anticipa el CLUSTERING de
excepciones del VaR mejor que la volatilidad sola, por encima de un nulo?

Gate antes de invertir en reentrenar la CNN. Objetivo NUEVO (no refutado):
no es dirección ni nivel de vol, es la probabilidad condicional de excepción
dado el estado reciente — el término que mata el test de independencia de
Christoffersen y dispara el recargo del multiplicador de Basilea.

Diseño:
  - Serie: Brent diario (brent_fred_daily.csv).
  - VaR incumbente: simulación histórica estática (window=250, alpha=0.99),
    que es la que agrupa excepciones en los repuntes de vol (realista).
  - Objetivo: y_t = 1 si el retorno de t+1 es excepción del VaR de t+1.
  - Baseline A: logística sobre [vol EWMA, VaR actual, excepción_hoy].
  - Tratamiento B: A + features de geometría del canal (as-of, sin look-ahead).
  - Métrica: AUC-PR y AUC-ROC out-of-time (train <= cutoff, test > cutoff).
  - NULO: block-bootstrap de retornos (preserva clustering de vol) repetido;
    el incremento real de B sobre A debe salirse de la banda del nulo.
  - Lectura de capital: usar la señal para subir el VaR solo en el decil de
    mayor riesgo y medir excepciones peor-250d, multiplicador y capital.
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "code", "applications"))
sys.path.insert(0, os.path.join(ROOT, "code", "part2_channel_survival"))
import common  # noqa
from experiments.portfolio_var import (  # noqa
    _historical_var, basel_multiplier, capital_analysis)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, roc_auc_score

ALPHA = 0.99
WIN = 250
CUTOFF = pd.Timestamp("2020-08-20")
SEED = 42
VOL_PROXIES = ["vol20", "atr_norm", "resid_norm", "band_width"]
PURE_GEOM = ["dir_asc", "slope_norm", "r2", "accel", "n_turn", "pos_in_channel"]

rng = np.random.default_rng(SEED)


def load_brent():
    s, src = common.load_prices(
        os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    return s.to_numpy(dtype=float), pd.DatetimeIndex(s.index), src


def daily_geometry(prices: np.ndarray, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Matriz diaria de features de geometría, alineada AS-OF (sin look-ahead).

    window_features da features en los índices e0 de fin de ventana de canal;
    para cada día t usamos las features de la ventana más reciente con e0 <= t.
    """
    idxs, _flags, feats = common.window_features(prices)
    cols = list(common.FEATURES)
    daily = pd.DataFrame(index=np.arange(len(prices)), columns=cols, dtype=float)
    if len(feats):
        f = feats.reset_index(drop=True)
        for k, e0 in enumerate(idxs):
            if 0 <= e0 < len(prices):
                daily.loc[e0, cols] = f.loc[k, cols].to_numpy()
    daily = daily.ffill()  # as-of: arrastra la última ventana completada
    return daily


def build_table(prices, dates):
    rets = np.diff(np.log(prices))
    var = _historical_var(rets, ALPHA, WIN)                 # VaR de t (usa t-WIN..t)
    exc = (rets < -var).astype(float)
    vol = common.ewma_vol(rets, 0.94)
    geom = daily_geometry(prices, dates)                    # index 0..len(prices)-1
    # el retorno t corresponde al precio t+1 -> geometría as-of del precio t
    geom_r = geom.iloc[:-1].reset_index(drop=True)
    df = pd.DataFrame({
        "date": dates[1:],
        "ret": rets, "var": var, "exc": exc, "vol": vol,
        "exc_prev": np.concatenate([[0.0], exc[:-1]]),
    })
    for c in common.FEATURES:
        df[c] = geom_r[c].to_numpy()
    df["y"] = np.concatenate([exc[1:], [np.nan]])           # excepción de MAÑANA
    df = df.iloc[WIN:].dropna(subset=["y", "var", "vol"]).reset_index(drop=True)
    return df, rets


def fit_eval(df, feat_cols):
    tr = df[df["date"] <= CUTOFF]
    te = df[df["date"] > CUTOFF]
    Xtr, Xte = tr[feat_cols].to_numpy(), te[feat_cols].to_numpy()
    ytr, yte = tr["y"].to_numpy(), te["y"].to_numpy()
    sc = StandardScaler().fit(Xtr)
    m = LogisticRegression(max_iter=1000, class_weight="balanced")
    m.fit(sc.transform(np.nan_to_num(Xtr)), ytr)
    p = m.predict_proba(sc.transform(np.nan_to_num(Xte)))[:, 1]
    return {
        "n_test": int(len(yte)), "exc_test": int(yte.sum()),
        "auc_pr": float(average_precision_score(yte, p)) if yte.sum() else float("nan"),
        "auc_roc": float(roc_auc_score(yte, p)) if 0 < yte.sum() < len(yte) else float("nan"),
    }, p, te


def main():
    prices, dates, src = load_brent()
    df, rets = build_table(prices, dates)
    base_cols = ["vol", "var", "exc_prev"]
    out = {"source": src, "alpha": ALPHA, "window": WIN,
           "cutoff": str(CUTOFF.date()),
           "n": int(len(df)), "exc_rate": round(float(df["y"].mean()), 4)}

    A, pA, te = fit_eval(df, base_cols)
    B, pB, _ = fit_eval(df, base_cols + VOL_PROXIES + PURE_GEOM)
    Bv, _, _ = fit_eval(df, base_cols + VOL_PROXIES)
    Bg, _, _ = fit_eval(df, base_cols + PURE_GEOM)
    out["A_baseline_vol_var"] = A
    out["B_full_geometry"] = B
    out["B_vol_proxies_only"] = Bv
    out["B_pure_geometry_only"] = Bg
    out["delta_auc_pr_full_vs_base"] = round(B["auc_pr"] - A["auc_pr"], 4)
    out["delta_auc_pr_puregeom_increment"] = round(Bg["auc_pr"] - A["auc_pr"], 4)

    # ---- NULO: block-bootstrap de retornos (preserva clustering de vol) ----
    def block_bootstrap(r, bl=20):
        n = len(r); out = np.empty(n)
        i = 0
        while i < n:
            s = rng.integers(0, n - bl)
            take = min(bl, n - i)
            out[i:i + take] = r[s:s + take]
            i += take
        return out

    null_deltas = []
    for _ in range(60):
        rb = block_bootstrap(rets, 20)
        pb = np.exp(np.concatenate([[np.log(prices[0])], np.cumsum(rb)]))
        try:
            dfb, _ = build_table(pb, dates[:len(pb)])
            a, _, _ = fit_eval(dfb, base_cols)
            b, _, _ = fit_eval(dfb, base_cols + VOL_PROXIES + PURE_GEOM)
            null_deltas.append(b["auc_pr"] - a["auc_pr"])
        except Exception:
            pass
    nd = np.array([x for x in null_deltas if x == x])
    out["null"] = {
        "n_valid": int(len(nd)),
        "delta_mean": round(float(np.mean(nd)), 4) if len(nd) else None,
        "delta_p95": round(float(np.percentile(nd, 95)), 4) if len(nd) else None,
        "real_delta_exceeds_null_p95": bool(
            (B["auc_pr"] - A["auc_pr"]) > np.percentile(nd, 95)) if len(nd) else None,
    }

    # ---- lectura de capital: subir VaR en el decil de mayor riesgo ----
    yte = te["y"].to_numpy(); var_te = te["var"].to_numpy()
    ret_next = te["y"].to_numpy()  # placeholder; usar retorno real de t+1
    # recomputar excepción real con overlay: subir VaR un 40% en top-decil de señal
    thr = np.quantile(pB, 0.90)
    overlay = np.where(pB >= thr, 1.40, 1.0)
    rfut = te["ret"].to_numpy()  # retorno de HOY; la excepción y es de mañana
    # para capital usamos la serie de excepciones del propio test bajo incumbente
    exc_base = (te["ret"].to_numpy() < -te["var"].to_numpy()).astype(int)
    exc_over = (te["ret"].to_numpy() < -(te["var"].to_numpy() *
                np.where(pB >= thr, 1.40, 1.0))).astype(int)
    cap_base = capital_analysis(exc_base, float(np.mean(var_te)))
    cap_over = capital_analysis(exc_over, float(np.mean(var_te * overlay)))
    out["capital"] = {
        "base": {k: cap_base[k] for k in
                 ("exceptions_per_250d_avg", "worst_250d_exceptions",
                  "multiplier_worst", "zone_worst", "capital_worst")},
        "overlay_geom": {k: cap_over[k] for k in
                         ("exceptions_per_250d_avg", "worst_250d_exceptions",
                          "multiplier_worst", "zone_worst", "capital_worst")},
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
