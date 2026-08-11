"""Aplicación 1 — Data Quality en el control de precios.

Marca como candidatos a error de captura:
  - `out_of_band` : el nuevo precio se aleja del canal reciente más de k·σ
    (residuo proyectado hacia delante, sin fuga; ver common.forward_channel_residual).
  - `atr_jump_reverting` : salto > TOL_ATR·ATR que revierte al día siguiente
    (típico pico de feed / dato erróneo puntual).
  - `stale` : tres cierres idénticos consecutivos (posible precio congelado).

El umbral k·σ es estadístico y se deriva de la propia banda de residuos del
canal, no es un valor arbitrario. Se compara contra un baseline ingenuo de
outliers por cuantil de |retorno| para cuantificar el valor añadido.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402


def detect_anomalies(prices: np.ndarray, dates: pd.DatetimeIndex,
                     k_sigma: float, tol_atr: float,
                     lookback: int = common.LOOKBACK) -> pd.DataFrame:
    resid = common.forward_channel_residual(prices, lookback)
    atr = common.atr_like(prices)
    rows: List[Dict[str, object]] = []

    # 1) fuera de banda del canal (residuo proyectado)
    for _, r in resid.iterrows():
        if abs(r["z"]) > k_sigma:
            t = int(r["pos"])
            rows.append({
                "pos": t, "date": dates[t], "price": float(prices[t]),
                "reason": "out_of_band", "severity": round(abs(r["z"]), 2),
            })

    # 2) salto ATR que revierte al día siguiente (pico puntual)
    n = len(prices)
    for t in range(1, n - 1):
        jump = abs(prices[t] - prices[t - 1])
        thr = tol_atr * (atr[t] if not np.isnan(atr[t]) else 0.0)
        if thr > 0 and jump > thr:
            revert = abs(prices[t + 1] - prices[t - 1])
            if revert < 0.5 * jump:  # vuelve cerca del nivel previo
                rows.append({
                    "pos": t, "date": dates[t], "price": float(prices[t]),
                    "reason": "atr_jump_reverting",
                    "severity": round(jump / thr, 2),
                })

    # 3) precio congelado (tres cierres idénticos)
    for t in range(2, n):
        if prices[t] == prices[t - 1] == prices[t - 2]:
            rows.append({
                "pos": t, "date": dates[t], "price": float(prices[t]),
                "reason": "stale", "severity": 1.0,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["pos", "reason"]).sort_values("pos")
    return df.reset_index(drop=True)


def _naive_return_outliers(prices: np.ndarray, q: float = 0.999) -> np.ndarray:
    rets = np.abs(np.diff(prices, prepend=prices[0]) / np.clip(prices, 1e-9, None))
    thr = float(np.quantile(rets, q))
    return np.where(rets > thr)[0]


class DQPriceControlExperiment(Experiment):
    id = "dq_price_control"
    title = "Data Quality — control de precios (canal ±k·σ, saltos ATR, stale)"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        if float(ctx.config.get("k_sigma", 4.0)) <= 0:
            issues.append("k_sigma debe ser > 0")
        if float(ctx.config.get("tol_atr", common.TOL_ATR)) <= 0:
            issues.append("tol_atr debe ser > 0")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        s, source = common.load_prices(cfg.get("prices_path"),
                                       cfg.get("synthetic", False), ctx.seed)
        prices = s.to_numpy()
        dates = pd.DatetimeIndex(s.index)
        k_sigma = float(cfg.get("k_sigma", 4.0))
        tol_atr = float(cfg.get("tol_atr", common.TOL_ATR))

        flags = detect_anomalies(prices, dates, k_sigma, tol_atr)
        n_obs = int(len(prices))
        n_flags = int(len(flags))
        by_reason = (flags["reason"].value_counts().to_dict() if n_flags else {})

        out_band_pos = set(flags.loc[flags["reason"] == "out_of_band", "pos"]) if n_flags else set()
        naive_pos = set(_naive_return_outliers(prices).tolist())
        inter = len(out_band_pos & naive_pos)
        union = len(out_band_pos | naive_pos) or 1
        jaccard = inter / union

        metrics = {
            "source": source,
            "n_obs": n_obs,
            "n_flags": n_flags,
            "flag_rate": round(n_flags / n_obs, 5) if n_obs else 0.0,
            "by_reason": by_reason,
            "k_sigma": k_sigma,
            "tol_atr": tol_atr,
        }
        baseline = {
            "method": "outliers por cuantil |retorno| (q=0.999)",
            "n_naive_outliers": len(naive_pos),
            "jaccard_with_out_of_band": round(jaccard, 3),
            "note": "el detector de canal añade contexto geométrico (banda ±k·σ) "
                    "que el cuantil de retorno no captura",
        }

        artifacts: List[str] = []
        if n_flags:
            path = os.path.join(ctx.experiment_dir(), "dq_flags.csv")
            flags.to_csv(path, index=False)
            artifacts.append(path)

        flag_rate = metrics["flag_rate"]
        if 0 < flag_rate <= 0.05:
            decision = "accept"
        elif flag_rate == 0:
            decision = "review"  # nada marcado: revisar umbral o serie
        else:
            decision = "reject"  # >5% marcado: umbral demasiado laxo
        notes = (f"{n_flags} candidatos ({flag_rate:.2%}); "
                 f"solape con baseline Jaccard={jaccard:.2f}. "
                 "Salida pensada como regla adicional del Control de Cambios DQ.")
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                artifacts=artifacts, decision=decision, notes=notes)