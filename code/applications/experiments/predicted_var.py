"""Aplicación 3 — Predicted VaR como overlay sobre el VaR histórico.

Compara dos estimadores de VaR 1-día a nivel `alpha` sobre la serie del Brent:

  - `historical`  (baseline): simulación histórica pura — cuantil empírico de
    los retornos en una ventana móvil.
  - `predicted`  : simulación histórica FILTRADA por volatilidad EWMA
    (Hull–White / FHS) + un *add-on* de cola cuando el mercado está en
    compresión de canal (banda estrecha), régimen en el que el histórico
    reciente tiende a subestimar el riesgo.

Backtesting regulatorio sobre el tramo de test: nº de excepciones, test de
cobertura incondicional de **Kupiec (POF)** y test de independencia de
**Christoffersen**. Se reporta qué estimador queda más cerca del `alpha`
objetivo sin ser rechazado — sin ocultar si el overlay no mejora.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402


def _chi2_sf(x: float, df: int) -> float:
    """Cola superior de una chi-cuadrado (usa scipy si está, si no gammainc)."""
    if x <= 0:
        return 1.0
    try:
        from scipy.stats import chi2

        return float(chi2.sf(x, df))
    except Exception:  # pragma: no cover
        # Serie incompleta de la gamma regularizada para df/2 entero o semientero.
        from math import erfc, exp, sqrt

        if df == 1:
            return erfc(sqrt(x / 2.0))
        if df == 2:
            return exp(-x / 2.0)
        # aproximación de Wilson–Hilferty para df general
        t = ((x / df) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / sqrt(2.0 / (9.0 * df))
        return 0.5 * erfc(t / sqrt(2.0))


def kupiec_pof(exceptions: np.ndarray, alpha: float) -> Dict[str, float]:
    """Test de cobertura incondicional (proporción de fallos)."""
    n = int(len(exceptions))
    x = int(np.sum(exceptions))
    p = 1.0 - alpha  # prob. teórica de excepción
    if n == 0:
        return {"n": 0, "exceptions": 0, "exception_rate": float("nan"),
                "LR_pof": float("nan"), "p_value": float("nan")}
    pi = x / n
    if x == 0:
        lr = -2.0 * (n * math.log(1 - p))
    elif x == n:
        lr = -2.0 * (n * math.log(p))
    else:
        ll_null = x * math.log(p) + (n - x) * math.log(1 - p)
        ll_alt = x * math.log(pi) + (n - x) * math.log(1 - pi)
        lr = -2.0 * (ll_null - ll_alt)
    return {"n": n, "exceptions": x, "exception_rate": round(pi, 5),
            "expected_rate": round(p, 5), "LR_pof": round(lr, 4),
            "p_value": round(_chi2_sf(lr, 1), 4)}


def christoffersen_independence(exceptions: np.ndarray) -> Dict[str, float]:
    """Test de independencia (clustering) de las excepciones."""
    e = np.asarray(exceptions, dtype=int)
    if len(e) < 2:
        return {"LR_ind": float("nan"), "p_value": float("nan")}
    n00 = n01 = n10 = n11 = 0
    for prev, cur in zip(e[:-1], e[1:]):
        if prev == 0 and cur == 0:
            n00 += 1
        elif prev == 0 and cur == 1:
            n01 += 1
        elif prev == 1 and cur == 0:
            n10 += 1
        else:
            n11 += 1
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    if pi in (0.0, 1.0) or pi01 in (0.0, 1.0) or pi11 in (0.0, 1.0):
        return {"LR_ind": 0.0, "p_value": 1.0,
                "transitions": {"n00": n00, "n01": n01, "n10": n10, "n11": n11}}

    def _ll(p, a, b):
        return a * math.log(1 - p) + b * math.log(p)

    ll_null = _ll(pi, n00 + n10, n01 + n11)
    ll_alt = _ll(pi01, n00, n01) + _ll(pi11, n10, n11)
    lr = -2.0 * (ll_null - ll_alt)
    return {"LR_ind": round(lr, 4), "p_value": round(_chi2_sf(lr, 1), 4),
            "transitions": {"n00": n00, "n01": n01, "n10": n10, "n11": n11}}


def historical_var(returns: np.ndarray, alpha: float, window: int) -> np.ndarray:
    var = np.full(len(returns), np.nan)
    for t in range(window, len(returns)):
        var[t] = -float(np.quantile(returns[t - window:t], 1.0 - alpha))
    return var


def predicted_var(returns: np.ndarray, alpha: float, window: int,
                  regime_addon: np.ndarray, lam: float = 0.94,
                  addon: float = 0.25) -> np.ndarray:
    """FHS con vol EWMA + add-on de cola por régimen de compresión."""
    vol = common.ewma_vol(returns, lam)
    var = np.full(len(returns), np.nan)
    for t in range(window, len(returns)):
        v = vol[t]
        if v <= 1e-12:
            var[t] = -float(np.quantile(returns[t - window:t], 1.0 - alpha))
            continue
        z = returns[t - window:t] / np.where(vol[t - window:t] > 1e-12, vol[t - window:t], v)
        q_z = float(np.quantile(z, 1.0 - alpha))
        base = -q_z * v
        var[t] = base * (1.0 + addon * float(regime_addon[t]))
    return var


class PredictedVaRExperiment(Experiment):
    id = "predicted_var"
    title = "Predicted VaR (FHS + régimen de canal) vs VaR histórico + backtest"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        a = float(ctx.config.get("alpha", 0.99))
        if not 0.90 <= a < 1.0:
            issues.append("alpha fuera de [0.90, 1.0)")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        s, source = common.load_prices(cfg.get("prices_path"),
                                       cfg.get("synthetic", False), ctx.seed)
        prices = s.to_numpy()
        dates = pd.DatetimeIndex(s.index)
        alpha = float(cfg.get("alpha", 0.99))
        window = int(cfg.get("var_window", 250))
        cutoff = cfg.get("cutoff")

        rets = common.log_returns(prices)              # len n-1
        rdates = dates[1:]
        if len(rets) < window + 100:
            return ExperimentResult(metrics={"source": source, "n_returns": len(rets)},
                                    decision="review", notes="serie corta para VaR")

        # Régimen = propensión de ruptura a corto plazo: 1 - P(T>k) de la
        # supervivencia del canal (ajustada solo con train). Fallback: compresión
        # de banda por tercil si la supervivencia no está disponible.
        surv_h = int(cfg.get("var_surv_horizon", 5))
        episodes = common.cs.extract_episodes(prices, dates)
        featurizer = common.SurvivalFeaturizer().fit(episodes, cutoff)
        idxs, _flags, featdf = common.window_features(prices)
        regime = np.zeros(len(rets))
        survival_method = featurizer.method
        if featurizer.method != "none" and not featdf.empty:
            surv_pk = featurizer.predict_pk(featdf, surv_h)
            prop = {int(e0): (1.0 - float(surv_pk[k]))
                    for k, e0 in enumerate(idxs) if surv_pk[k] == surv_pk[k]}
            for t in range(len(rets)):
                regime[t] = prop.get(t + 1, 0.0)  # posición de precio = t+1
        else:  # fallback compresión de banda
            resid = common.forward_channel_residual(prices, common.LOOKBACK)
            bw = pd.Series(resid["band_width_rel"].to_numpy(),
                           index=resid["pos"].astype(int).to_numpy())
            if not bw.empty:
                thr = float(np.quantile(bw.to_numpy(), 0.33))
                for t in range(len(rets)):
                    pos = t + 1
                    if pos in bw.index:
                        regime[t] = 1.0 if bw.loc[pos] <= thr else 0.0
            survival_method = "fallback_band_compression"

        var_hs = historical_var(rets, alpha, window)
        var_pred = predicted_var(rets, alpha, window, regime,
                                 lam=float(cfg.get("ewma_lambda", 0.94)),
                                 addon=float(cfg.get("tail_addon", 0.25)))

        tr = common.temporal_mask(rdates, cutoff)
        te = (~tr) & (np.arange(len(rets)) >= window)
        valid = te & ~np.isnan(var_hs) & ~np.isnan(var_pred)
        if valid.sum() < 100:
            return ExperimentResult(metrics={"source": source, "n_test": int(valid.sum())},
                                    decision="review", notes="test insuficiente para backtest")

        r_te = rets[valid]
        exc_hs = (r_te < -var_hs[valid]).astype(int)
        exc_pred = (r_te < -var_pred[valid]).astype(int)

        res_hs = {"kupiec": kupiec_pof(exc_hs, alpha),
                  "christoffersen": christoffersen_independence(exc_hs),
                  "avg_var": round(float(np.mean(var_hs[valid])), 5)}
        res_pred = {"kupiec": kupiec_pof(exc_pred, alpha),
                    "christoffersen": christoffersen_independence(exc_pred),
                    "avg_var": round(float(np.mean(var_pred[valid])), 5)}

        target = 1.0 - alpha
        dist_hs = abs(res_hs["kupiec"]["exception_rate"] - target)
        dist_pred = abs(res_pred["kupiec"]["exception_rate"] - target)

        metrics = {
            "source": source, "alpha": alpha, "var_window": window,
            "n_test": int(valid.sum()), "target_exception_rate": round(target, 5),
            "survival_method": survival_method, "survival_horizon": surv_h,
            "historical": res_hs, "predicted": res_pred,
        }
        baseline = {"method": "VaR histórico (simulación histórica pura)",
                    "exception_rate": res_hs["kupiec"]["exception_rate"],
                    "kupiec_p": res_hs["kupiec"]["p_value"]}

        pred_ok = (res_pred["kupiec"]["p_value"] >= 0.05)
        improves = dist_pred <= dist_hs
        if pred_ok and improves:
            decision = "accept"
        elif pred_ok:
            decision = "review"
        else:
            decision = "reject"
        notes = (f"tasa excep. hist={res_hs['kupiec']['exception_rate']:.3%} vs "
                 f"pred={res_pred['kupiec']['exception_rate']:.3%} (objetivo {target:.2%}); "
                 f"Kupiec p pred={res_pred['kupiec']['p_value']}; surv={survival_method}. "
                 "Overlay FHS-EWMA con add-on de cola escalado por 1-P(T>k) del canal.")
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)