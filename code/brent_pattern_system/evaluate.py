"""Evaluación out-of-sample: clasificación balanceada + regresión de retornos."""

from __future__ import annotations

from typing import Dict, Sequence

import numpy as np
import pandas as pd

from .config import PATTERN_CLASSES
from .metrics import classification_metrics


def predict_indices(
    model_path: str,
    frame: pd.DataFrame,
    window_table: pd.DataFrame,
    indices: np.ndarray,
    feature_cols: Sequence[str],
    config: Dict[str, object],
) -> pd.DataFrame:
    """Predice (torch) las ventanas en `indices` y las cruza con el ground-truth."""
    from .torch_model import predict_torch_model

    sub = window_table.iloc[np.asarray(indices, dtype=int)].copy()
    infer_table = sub[["start", "end", "end_date"]].reset_index(drop=True)
    pred_df = predict_torch_model(model_path, frame, infer_table, feature_cols, config)

    truth_cols = ["start", "end", "pattern_label", "future_return", "future_low", "future_high"]
    truth_cols = [c for c in truth_cols if c in window_table.columns]
    merged = pred_df.merge(window_table[truth_cols], on=["start", "end"], how="left")
    return merged


def regression_metrics(df: pd.DataFrame) -> Dict[str, float]:
    out: Dict[str, float] = {}
    pairs = [
        ("future_return", "pred_return"),
        ("future_low", "pred_low"),
        ("future_high", "pred_high"),
    ]
    for truth, pred in pairs:
        if truth in df.columns and pred in df.columns:
            t = df[truth].to_numpy(dtype=float)
            p = df[pred].to_numpy(dtype=float)
            mask = ~(np.isnan(t) | np.isnan(p))
            if mask.sum() == 0:
                continue
            err = p[mask] - t[mask]
            out[f"mae_{truth}"] = float(np.mean(np.abs(err)))
            out[f"rmse_{truth}"] = float(np.sqrt(np.mean(err ** 2)))
    # Acierto direccional del retorno (relevante para la señal de trading).
    if "future_return" in df.columns and "pred_return" in df.columns:
        t = df["future_return"].to_numpy(dtype=float)
        p = df["pred_return"].to_numpy(dtype=float)
        mask = ~(np.isnan(t) | np.isnan(p))
        if mask.any():
            out["directional_accuracy"] = float(np.mean(np.sign(p[mask]) == np.sign(t[mask])))
    return out


def evaluate_predictions(df: pd.DataFrame) -> Dict[str, object]:
    """Métricas de clasificación (balanceadas) y de regresión sobre `df` (OOS)."""
    summary: Dict[str, object] = {"n": int(len(df))}
    if "pattern_label" in df.columns and "predicted_pattern" in df.columns:
        valid = df.dropna(subset=["pattern_label", "predicted_pattern"])
        summary["classification"] = classification_metrics(
            valid["pattern_label"].tolist(),
            valid["predicted_pattern"].tolist(),
            PATTERN_CLASSES,
        )
    summary["regression"] = regression_metrics(df)
    return summary
