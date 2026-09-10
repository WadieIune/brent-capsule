"""FRTB risk-factor data and modellability gate (non-regulatory proxy).

This module deliberately does *not* calculate ES, capital or an official RFET.
It produces an auditable pre-calibration decision per factor so a risk platform
can block contaminated observations and route weak factors to NMRF/model-risk
review before they enter an IMA data set.
"""
from __future__ import annotations

from typing import Dict

import pandas as pd


def assess_factor(
    prices: pd.Series,
    *,
    min_moves_per_year: int = 24,
    max_gap_sessions: int = 21,
    max_zero_return_fraction: float = 0.05,
    cnn_outlier_score: float | None = None,
    cnn_outlier_threshold: float = 0.68,
) -> Dict[str, object]:
    """Return a conservative operational gate for one risk-factor series.

    ``pass`` means only that observable proxies are clean enough to continue to
    human/RFET verification. It is never an assertion that the factor is
    officially modellable: real-price provenance and representativeness are
    outside this data-only gate.
    """
    s = pd.Series(prices, copy=False).astype(float).dropna()
    if len(s) < 2:
        return {"status": "block", "reason": "insufficient_observations", "n": int(len(s))}
    diff = s.diff().iloc[1:]
    nonpositive = int((s <= 0).sum())
    zero_fraction = float((diff.abs() <= 1e-12).mean())
    moved = diff.abs() > 1e-12
    per_year = moved.groupby(s.index[1:].year).sum()
    min_moves = int(per_year.min()) if len(per_year) else 0
    gap = 0
    max_gap = 0
    for flag in moved.to_numpy(dtype=bool):
        gap = 0 if flag else gap + 1
        max_gap = max(max_gap, gap)
    reasons = []
    if nonpositive:
        reasons.append("nonpositive_price")
    if zero_fraction > max_zero_return_fraction:
        reasons.append("stale_or_calendar_padding")
    if min_moves < min_moves_per_year:
        reasons.append("rfet_activity_proxy_below_threshold")
    if max_gap > max_gap_sessions:
        reasons.append("gap_proxy_above_threshold")
    cnn_review = cnn_outlier_score is not None and float(cnn_outlier_score) >= cnn_outlier_threshold
    if cnn_review:
        reasons.append("cnn_channel_review")
    status = "block" if any(r in reasons for r in ("nonpositive_price", "stale_or_calendar_padding")) else ("review" if reasons else "pass")
    return {
        "status": status,
        "reasons": reasons,
        "n": int(len(s)),
        "nonpositive_count": nonpositive,
        "zero_return_fraction": round(zero_fraction, 6),
        "min_moves_per_year": min_moves,
        "max_gap_sessions": int(max_gap),
        "rfet_proxy_pass": bool(min_moves >= min_moves_per_year and max_gap <= max_gap_sessions and not nonpositive),
        "cnn_signal": {"score": cnn_outlier_score, "threshold": cnn_outlier_threshold, "review": cnn_review},
        "official_rfet_claim": False,
    }


def assess_panel(prices: pd.DataFrame, **kwargs: object) -> Dict[str, Dict[str, object]]:
    """Apply :func:`assess_factor` column-wise, preserving factor names."""
    return {str(c): assess_factor(prices[c], **kwargs) for c in prices.columns}

