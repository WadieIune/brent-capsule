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


def lr_conditional_coverage(exceptions: np.ndarray, alpha: float) -> Dict[str, float]:
    """Cobertura condicional de Christoffersen: LR_cc = LR_uc + LR_ind ~ chi2(2).

    Un VaR puede acertar el nivel medio y aun así agrupar las excepciones; el
    test conjunto exige las dos cosas a la vez.
    """
    uc = kupiec_pof(exceptions, alpha)
    ind = christoffersen_independence(exceptions)
    lr_uc, lr_ind = uc.get("LR_pof"), ind.get("LR_ind")
    if lr_uc != lr_uc or lr_ind != lr_ind:  # NaN
        return {"LR_cc": float("nan"), "p_value": float("nan")}
    lr = float(lr_uc) + float(lr_ind)
    return {"LR_cc": round(lr, 4), "p_value": round(_chi2_sf(lr, 2), 4)}


def dq_engle_manganelli(exceptions: np.ndarray, var: np.ndarray, alpha: float,
                        lags: int = 4) -> Dict[str, object]:
    """Dynamic Quantile test (Engle & Manganelli, 2004).

    Regresa los *hits* desmediados sobre una constante, sus retardos y el propio
    VaR: bajo especificación correcta todos los coeficientes son nulos. Detecta a
    la vez sesgo de cobertura, dependencia temporal y dependencia del fallo
    respecto al nivel de VaR, que Kupiec y Christoffersen no capturan por separado.

    Nota terminológica: éste es el «DQ» de la literatura de VaR; no confundir con
    el control de calidad de dato del experimento `dq_price_control`.
    """
    p = 1.0 - alpha
    hit = np.asarray(exceptions, dtype=float) - p
    v = np.asarray(var, dtype=float)
    n = len(hit)
    if n <= lags + 3:
        return {"DQ_stat": float("nan"), "p_value": float("nan"), "lags": lags}
    X = np.column_stack(
        [np.ones(n - lags)]
        + [hit[lags - l: n - l] for l in range(1, lags + 1)]
        + [v[lags:]]
    )
    y = hit[lags:]
    xtx = X.T @ X
    try:
        beta = np.linalg.solve(xtx, X.T @ y)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
    stat = float(beta @ xtx @ beta / (p * (1.0 - p)))
    df = int(X.shape[1])
    return {"DQ_stat": round(stat, 4), "p_value": round(_chi2_sf(stat, df), 4),
            "lags": lags, "df": df}


def drop_ffill_holidays(s: pd.Series) -> tuple:
    """Elimina sesiones rellenadas por forward-fill (precio idéntico al previo).

    Los festivos con relleno introducen retornos exactamente cero que no son
    negociación: inflan la muestra, desplazan el cuantil empírico y crean rachas
    artificiales de no-excepción que sesgan el test de independencia.
    """
    moved = s.diff().abs() > 1e-12
    if len(moved):
        moved.iloc[0] = True
    out = s.loc[moved]
    diag = {"rows_in": int(len(s)), "rows_out": int(len(out)),
            "dropped_ffill": int(len(s) - len(out))}
    return out, diag


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
        cal_diag: Dict[str, object] = {"ffill_filter": False}
        if bool(cfg.get("drop_ffill", True)):
            s, cal_diag = drop_ffill_holidays(s)
            cal_diag["ffill_filter"] = True
            ctx.log(f"  sesiones: {cal_diag['rows_in']} -> {cal_diag['rows_out']} "
                    f"({cal_diag['dropped_ffill']} rellenos por ffill excluidos)")
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

        lam = float(cfg.get("ewma_lambda", 0.94))
        addon = float(cfg.get("tail_addon", 0.25))
        var_hs = historical_var(rets, alpha, window)
        # Baseline FUERTE: mismo filtrado EWMA pero SIN información de canal.
        # Sin él, la mejora del overlay no es atribuible: podría venir entera
        # del filtrado de volatilidad.
        var_fhs = predicted_var(rets, alpha, window, np.zeros(len(rets)), lam=lam, addon=0.0)
        var_pred = predicted_var(rets, alpha, window, regime, lam=lam, addon=addon)

        tr = common.temporal_mask(rdates, cutoff)
        te = (~tr) & (np.arange(len(rets)) >= window)
        valid = te & ~np.isnan(var_hs) & ~np.isnan(var_pred) & ~np.isnan(var_fhs)
        if valid.sum() < 100:
            return ExperimentResult(metrics={"source": source, "n_test": int(valid.sum())},
                                    decision="review", notes="test insuficiente para backtest")

        # Control de NIVEL: constante con el mismo VaR medio que el overlay.
        # Si lo iguala, el canal no aporta timing, solo un desplazamiento.
        k_const = float(np.mean(var_pred[valid]) / np.mean(var_fhs[valid]))
        var_const = var_fhs * k_const

        r_te = rets[valid]

        def _bt(name: str, var: np.ndarray) -> Dict[str, object]:
            exc = (r_te < -var[valid]).astype(int)
            return {"estimator": name,
                    "kupiec": kupiec_pof(exc, alpha),
                    "christoffersen": christoffersen_independence(exc),
                    "lr_cc": lr_conditional_coverage(exc, alpha),
                    "dq_engle_manganelli": dq_engle_manganelli(exc, var[valid], alpha),
                    "avg_var": round(float(np.mean(var[valid])), 5),
                    "exceptions": int(exc.sum())}

        res = {"historical": _bt("historical", var_hs),
               "fhs_ewma": _bt("fhs_ewma", var_fhs),
               "predicted": _bt("predicted", var_pred),
               "constant_equivalent": _bt("constant_equivalent", var_const)}

        # ¿La señal de régimen concentra las excepciones? Si el lift no supera 1,
        # no hay timing de cola y la mejora es de nivel.
        exc_hs_full = (rets < -var_hs).astype(int)
        lift = []
        for q in (0.70, 0.80, 0.90, 0.95):
            sig = regime[valid]
            thr = float(np.quantile(sig, q))
            a = sig >= thr
            e = exc_hs_full[valid]
            r1 = float(e[a].mean()) if a.sum() else float("nan")
            r0 = float(e[~a].mean()) if (~a).sum() else float("nan")
            lift.append({"quantile": q, "alert_days_pct": round(100.0 * float(a.mean()), 2),
                         "exc_rate_alert": round(r1, 5), "exc_rate_rest": round(r0, 5),
                         "lift": round(r1 / r0, 3) if r0 else None})

        target = 1.0 - alpha
        gaps = {k: abs(v["kupiec"]["exception_rate"] - target) for k, v in res.items()}
        attribution = {
            "target_exception_rate": round(target, 5),
            "coverage_gap": {k: round(v, 5) for k, v in gaps.items()},
            "gain_from_ewma_filtering": round(gaps["historical"] - gaps["fhs_ewma"], 5),
            "gain_from_channel_addon": round(gaps["fhs_ewma"] - gaps["predicted"], 5),
            "constant_equivalent_multiplier": round(k_const, 4),
            "channel_beats_constant": bool(gaps["predicted"] < gaps["constant_equivalent"]),
            "regime_lift_test": lift,
        }
        metrics = {
            "source": source, "calendar": cal_diag, "alpha": alpha, "var_window": window,
            "n_test": int(valid.sum()), "target_exception_rate": round(target, 5),
            "survival_method": survival_method, "survival_horizon": surv_h,
            "backtests": res, "attribution": attribution,
        }
        baseline = {"weak": "VaR histórico (simulación histórica pura)",
                    "strong": "FHS-EWMA sin información de canal",
                    "exception_rate_historical": res["historical"]["kupiec"]["exception_rate"],
                    "exception_rate_fhs_ewma": res["fhs_ewma"]["kupiec"]["exception_rate"],
                    "kupiec_p_fhs_ewma": res["fhs_ewma"]["kupiec"]["p_value"]}

        p = res["predicted"]
        pred_ok = (p["kupiec"]["p_value"] >= 0.05 and p["christoffersen"]["p_value"] >= 0.05)
        beats_strong = attribution["gain_from_channel_addon"] > 0
        beats_const = attribution["channel_beats_constant"]
        if pred_ok and beats_strong and beats_const:
            decision = "accept"
        elif pred_ok and (beats_strong or beats_const):
            decision = "review"
        else:
            decision = "reject"
        lift80 = next((x["lift"] for x in lift if x["quantile"] == 0.80), None)
        notes = (
            f"Cobertura (objetivo {target:.2%}): histórico "
            f"{res['historical']['kupiec']['exception_rate']:.3%} · FHS-EWMA "
            f"{res['fhs_ewma']['kupiec']['exception_rate']:.3%} · predicted "
            f"{p['kupiec']['exception_rate']:.3%} · constante equivalente "
            f"(x{k_const:.3f}) {res['constant_equivalent']['kupiec']['exception_rate']:.3%}. "
            f"La ganancia del filtrado EWMA es {attribution['gain_from_ewma_filtering']:+.5f} "
            f"y la del add-on de canal {attribution['gain_from_channel_addon']:+.5f}. "
            f"¿Bate el canal a una constante del mismo nivel medio? {beats_const}. "
            f"Timing: lift de la señal de régimen @q80 = {lift80} "
            f"(>1 indicaría que concentra excepciones). "
            f"DQ (Engle-Manganelli) p: histórico {res['historical']['dq_engle_manganelli']['p_value']} · "
            f"FHS {res['fhs_ewma']['dq_engle_manganelli']['p_value']} · "
            f"predicted {p['dq_engle_manganelli']['p_value']}. surv={survival_method}."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)