"""Backtest walk-forward y validación estadística del rendimiento.

Construye una estrategia simple a partir de la predicción de retorno del modelo
(`pred_return`) y la evalúa contra el retorno realizado (`future_return`),
reportando métricas corregidas por overfitting de López de Prado: Sharpe, PSR,
Deflated Sharpe Ratio (DSR) y Probability of Backtest Overfitting (PBO/CSCV).

La señal por defecto es direccional (`sign`): posición = signo del retorno
predicho; el PnL por periodo es `posición * retorno_realizado` menos costes de
transacción cuando la posición cambia.

Referencias: ver `metrics.py`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .metrics import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)


def position_from_prediction(pred_return: np.ndarray, signal: str = "sign", threshold: float = 0.0) -> np.ndarray:
    """Convierte el retorno predicho en una posición [-1, 1]."""
    pred = np.asarray(pred_return, dtype=float)
    if signal == "sign":
        pos = np.sign(pred)
    elif signal == "long_only":
        pos = (pred > threshold).astype(float)
    elif signal == "threshold":
        pos = np.where(pred > threshold, 1.0, np.where(pred < -threshold, -1.0, 0.0))
    elif signal == "proportional":
        scale = np.std(pred) + 1e-8
        pos = np.clip(pred / scale, -1.0, 1.0)
    else:
        raise ValueError(f"signal no soportado: {signal}")
    return pos


def strategy_returns(positions: np.ndarray, realized: np.ndarray, fee_bps: float = 0.0) -> np.ndarray:
    """PnL por periodo neto de costes (los costes se cobran al cambiar posición)."""
    positions = np.asarray(positions, dtype=float)
    realized = np.asarray(realized, dtype=float)
    gross = positions * realized
    turnover = np.abs(np.diff(np.r_[0.0, positions]))
    fees = turnover * (fee_bps / 1e4)
    return gross - fees


def performance_stats(returns: np.ndarray, periods_per_year: int = 252) -> Dict[str, float]:
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]
    if returns.size == 0:
        return {"n": 0}
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0
    wins = returns[returns != 0]
    return {
        "n": int(returns.size),
        "cumulative_return": float(equity[-1] - 1.0),
        "annualized_return": float(returns.mean() * periods_per_year),
        "annualized_vol": float(returns.std(ddof=1) * np.sqrt(periods_per_year)) if returns.size > 1 else 0.0,
        "sharpe_annual": sharpe_ratio(returns, periods_per_year=periods_per_year),
        "psr_vs_zero": probabilistic_sharpe_ratio(returns, sr_benchmark=0.0, periods_per_year=periods_per_year),
        "max_drawdown": float(drawdown.min()),
        "hit_rate": float(np.mean(wins > 0)) if wins.size else 0.0,
    }


def _signal_variants() -> List[Dict[str, object]]:
    """Pequeña rejilla de señales para estimar el PBO sobre el hiperparámetro de señal."""
    return [
        {"name": "sign", "signal": "sign", "threshold": 0.0},
        {"name": "long_only", "signal": "long_only", "threshold": 0.0},
        {"name": "thr_lo", "signal": "threshold", "threshold": 0.001},
        {"name": "thr_hi", "signal": "threshold", "threshold": 0.003},
        {"name": "proportional", "signal": "proportional", "threshold": 0.0},
    ]


def walk_forward_backtest(
    test_df: pd.DataFrame,
    config: Dict[str, object],
    pred_col: str = "pred_return",
    realized_col: str = "future_return",
    fold_col: Optional[str] = "fold_id",
    sr_trials_extra: Optional[Sequence[float]] = None,
) -> Dict[str, object]:
    """Evalúa la estrategia sobre el camino out-of-sample agregado del walk-forward.

    `test_df` debe contener las predicciones OOS concatenadas de todos los folds,
    ordenadas temporalmente, con columnas `pred_col` y `realized_col`.
    """
    bt_cfg = config.get("backtest", {})
    periods_per_year = int(bt_cfg.get("periods_per_year", 252))
    fee_bps = float(bt_cfg.get("fee_bps", 0.0))
    signal = str(bt_cfg.get("signal", "sign"))
    pbo_partitions = int(bt_cfg.get("pbo_partitions", 16))

    if pred_col not in test_df.columns or realized_col not in test_df.columns:
        raise ValueError(f"test_df debe contener '{pred_col}' y '{realized_col}'.")

    df = test_df.dropna(subset=[pred_col, realized_col]).reset_index(drop=True)
    realized = df[realized_col].to_numpy(dtype=float)
    pred = df[pred_col].to_numpy(dtype=float)

    # Estrategia principal (señal configurada).
    main_pos = position_from_prediction(pred, signal=signal)
    main_ret = strategy_returns(main_pos, realized, fee_bps=fee_bps)
    main_stats = performance_stats(main_ret, periods_per_year=periods_per_year)

    # Benchmark buy & hold del activo (posición larga constante).
    bh_stats = performance_stats(realized, periods_per_year=periods_per_year)

    # Sharpe por fold (caminos del walk-forward) -> trials para el DSR.
    sr_trials: List[float] = []
    if fold_col and fold_col in df.columns:
        for _, g in df.groupby(fold_col):
            pos_g = position_from_prediction(g[pred_col].to_numpy(dtype=float), signal=signal)
            r_g = strategy_returns(pos_g, g[realized_col].to_numpy(dtype=float), fee_bps=fee_bps)
            sr_trials.append(sharpe_ratio(r_g, periods_per_year=periods_per_year))
    if sr_trials_extra:
        sr_trials.extend(list(sr_trials_extra))
    if not sr_trials:
        sr_trials = [main_stats.get("sharpe_annual", 0.0)]

    dsr = deflated_sharpe_ratio(main_ret, sr_trials=sr_trials, periods_per_year=periods_per_year)

    # PBO mediante CSCV sobre la rejilla de señales (matriz T x N de retornos).
    variants = _signal_variants()
    perf_cols = []
    for v in variants:
        pos_v = position_from_prediction(pred, signal=str(v["signal"]), threshold=float(v["threshold"]))
        perf_cols.append(strategy_returns(pos_v, realized, fee_bps=fee_bps))
    perf_matrix = np.column_stack(perf_cols) if perf_cols else np.empty((0, 0))
    pbo = probability_of_backtest_overfitting(perf_matrix, n_partitions=pbo_partitions)

    return {
        "n_oos": int(len(df)),
        "signal": signal,
        "fee_bps": fee_bps,
        "strategy": main_stats,
        "buy_and_hold": bh_stats,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "sharpe_per_fold": sr_trials,
    }
