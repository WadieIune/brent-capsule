"""Typed, causal core for the statistical + intelligent DQ framework.

This module emits review alerts only. It never edits, imputes, or rejects source
observations; model/context scores are supplied by versioned as-of adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import numpy as np
import pandas as pd

SeriesKind = Literal[
    "positive_price", "positive_metric", "signed_price", "rate", "spread", "generic"
]
POSITIVE_KINDS = {"positive_price", "positive_metric"}


@dataclass(frozen=True)
class SeriesContract:
    series_id: str
    kind: SeriesKind
    unit: str
    lookback: int = 60
    min_history: int = 20
    sigma_limit: float = 3.0
    hampel_limit: float = 3.5
    trim_zero_run: int = 20
    repeat_warning_run: int = 3
    zero_run_is_expected: bool = False

    def __post_init__(self):
        if not self.series_id or not self.unit:
            raise ValueError("series_id y unit son obligatorios")
        if self.kind not in {"positive_price", "positive_metric", "signed_price",
                             "rate", "spread", "generic"}:
            raise ValueError(f"kind desconocido: {self.kind}")
        if self.lookback < 2 or not 2 <= self.min_history <= self.lookback:
            raise ValueError("se requiere 2 <= min_history <= lookback")
        if self.trim_zero_run < 1 or self.repeat_warning_run < 2:
            raise ValueError("umbrales de racha inválidos")
        if self.sigma_limit <= 0 or self.hampel_limit <= 0:
            raise ValueError("umbrales estadísticos deben ser positivos")


@dataclass
class DQAlert:
    series_id: str
    timestamp: pd.Timestamp
    layer: Literal["contract", "statistical", "intelligent"]
    rule: str
    severity: float
    evidence: dict = field(default_factory=dict)
    disposition: str = "review"


@dataclass
class SeriesReport:
    contract: SeriesContract
    returns: np.ndarray
    z_score: np.ndarray
    robust_z_score: np.ndarray
    alerts: list[DQAlert]


def transform_returns(values: np.ndarray, kind: SeriesKind) -> np.ndarray:
    """Use proportional log changes only for strictly positive series."""
    x = np.asarray(values, dtype=float).reshape(-1)
    out = np.full(len(x), np.nan, dtype=float)
    if len(x) < 2:
        return out
    if kind in POSITIVE_KINDS:
        valid = (x[1:] > 0) & (x[:-1] > 0) & np.isfinite(x[1:]) & np.isfinite(x[:-1])
        idx = np.flatnonzero(valid) + 1
        out[idx] = np.log(x[idx] / x[idx - 1])
    else:
        valid = np.isfinite(x[1:]) & np.isfinite(x[:-1])
        idx = np.flatnonzero(valid) + 1
        out[idx] = x[idx] - x[idx - 1]
    return out


def causal_return_scores(returns: np.ndarray, lookback: int = 60,
                         min_history: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Return z and robust-z scores; each t uses returns strictly before t."""
    r = pd.Series(np.asarray(returns, dtype=float))
    prior = r.shift(1)
    mean = prior.rolling(lookback, min_periods=min_history).mean()
    sigma = prior.rolling(lookback, min_periods=min_history).std(ddof=1)
    z = (r - mean) / sigma.where(sigma > 1e-12)

    median = prior.rolling(lookback, min_periods=min_history).median()
    past_deviation = (prior - median).abs()
    mad = past_deviation.rolling(lookback, min_periods=min_history).median()
    robust_z = (r - median) / (1.4826 * mad).where(mad > 1e-12)
    return z.to_numpy(dtype=float), robust_z.to_numpy(dtype=float)


def _runs(mask: np.ndarray):
    start = None
    for i, value in enumerate(np.r_[mask, False]):
        if value and start is None:
            start = i
        elif not value and start is not None:
            yield start, i
            start = None


def analyze_series(
    values: np.ndarray,
    dates,
    contract: SeriesContract,
    *,
    context_scores: Mapping[str, tuple[np.ndarray, float]] | None = None,
    model_scores: Mapping[str, tuple[np.ndarray, float]] | None = None,
) -> SeriesReport:
    """Run Layer 1 and attach calibrated Layer 2 scores as auditable alerts.

    Each mapping value is ``(score_by_observation, frozen_threshold)``. Scores
    must already be computed as-of each timestamp by the corresponding adapter.
    Context is for channel/survival features; model scores are for CNN/XGBoost.
    """
    x = np.asarray(values, dtype=float).reshape(-1)
    ts = pd.DatetimeIndex(dates)
    if len(ts) != len(x):
        raise ValueError("dates y values deben tener la misma longitud")
    if not len(x):
        raise ValueError("serie vacía")

    returns = transform_returns(x, contract.kind)
    z, robust_z = causal_return_scores(returns, contract.lookback, contract.min_history)
    alerts: list[DQAlert] = []

    def emit(index: int, layer: str, rule: str, severity: float, **evidence):
        alerts.append(DQAlert(contract.series_id, ts[index], layer, rule,
                              float(severity), evidence))

    for i in np.flatnonzero(~np.isfinite(x)):
        emit(int(i), "contract", "missing_or_nonfinite", 1.0)
    for i in np.flatnonzero(ts.isna()):
        emit(int(i), "contract", "missing_timestamp", 1.0)
    for i in range(1, len(ts)):
        if ts[i] <= ts[i - 1]:
            rule = ("duplicate_timestamp" if ts[i] == ts[i - 1]
                    else "timestamp_out_of_order")
            emit(i, "contract", rule, 1.0, previous=str(ts[i - 1]))
    if contract.kind in POSITIVE_KINDS:
        for i in np.flatnonzero(np.isfinite(x) & (x <= 0)):
            emit(int(i), "contract", "nonpositive_value", 1.0,
                 value=float(x[i]), unit=contract.unit)

    for i in np.flatnonzero(np.isfinite(z) & (np.abs(z) > contract.sigma_limit)):
        emit(int(i), "statistical", "causal_return_sigma", abs(z[i]),
             score=float(z[i]), threshold=contract.sigma_limit, unit=contract.unit)
    for i in np.flatnonzero(np.isfinite(robust_z) &
                            (np.abs(robust_z) > contract.hampel_limit)):
        emit(int(i), "statistical", "causal_hampel_return", abs(robust_z[i]),
             score=float(robust_z[i]), threshold=contract.hampel_limit)

    if not contract.zero_run_is_expected:
        zero_returns = np.isfinite(returns) & (returns == 0.0)
        for start, stop in _runs(zero_returns):
            run_length = stop - start
            if run_length >= contract.trim_zero_run:
                emit(stop - 1, "statistical", "trim_zero_return_run", run_length,
                     run_length=run_length, threshold=contract.trim_zero_run,
                     unit=contract.unit)
        for start, stop in _runs(np.isfinite(x[1:]) & np.isfinite(x[:-1]) &
                                 (x[1:] == x[:-1])):
            run_length = stop - start
            if run_length >= contract.repeat_warning_run:
                emit(stop, "statistical", "repeated_price_run", run_length,
                     run_length=run_length, threshold=contract.repeat_warning_run)

    for layer, signals in (("context", context_scores or {}),
                           ("model", model_scores or {})):
        for name, (scores, threshold) in signals.items():
            score_values = np.asarray(scores, dtype=float).reshape(-1)
            if len(score_values) != len(x):
                raise ValueError(f"score {name} no está alineado con la serie")
            if not np.isfinite(threshold):
                raise ValueError(f"umbral no finito para {name}")
            for i in np.flatnonzero(np.isfinite(score_values) &
                                    (score_values > threshold)):
                emit(int(i), "intelligent", f"{layer}:{name}", score_values[i],
                     score=float(score_values[i]), threshold=float(threshold))

    alerts.sort(key=lambda a: (a.timestamp, a.layer, a.rule))
    return SeriesReport(contract, returns, z, robust_z, alerts)
