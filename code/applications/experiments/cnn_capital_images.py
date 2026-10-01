"""Causal GASF/GADF representation; NumPy only, no fitted model or performance claim.

Input rows must already be aligned by availability time, not observation time.
Call fit_scaler on each training fold, never on validation/test observations.
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class ImageScaler:
    center: np.ndarray
    scale: np.ndarray
    observed_train: np.ndarray
    train_end_exclusive: int


def fit_scaler(data, train_end_exclusive):
    """Fit robust location/scale on rows [0, train_end_exclusive)."""
    x = np.asarray(data, dtype=float)
    if x.ndim != 2 or not 0 < train_end_exclusive <= len(x):
        raise ValueError("Expected 2D data and a nonempty, bounded training prefix")
    train = x[:train_end_exclusive]
    center = np.zeros(x.shape[1])
    scale = np.ones(x.shape[1])
    observed = np.zeros(x.shape[1], dtype=bool)
    for j in range(x.shape[1]):
        v = train[np.isfinite(train[:, j]), j]
        if not len(v):
            continue
        observed[j] = True
        center[j] = np.median(v)
        q25, q75 = np.quantile(v, [0.25, 0.75])
        robust = (q75 - q25) / 1.349
        fallback = np.std(v)
        scale[j] = robust if robust > 1e-12 else (fallback if fallback > 1e-12 else 1.0)
    for value in (center, scale, observed):
        value.setflags(write=False)
    return ImageScaler(center, scale, observed, int(train_end_exclusive))


def transform_window(data, scaler, decision_index, window=64):
    """Return (3F,L,L) images plus exactly the inputs needed by fair baselines.

    At decision_index t only rows t-L+1:t+1 are accessed. Each feature yields
    [GASF, GADF, pair-validity]. Missing values are masked, not forward filled.
    Features wholly absent during training stay unavailable until next refit.
    """
    x = np.asarray(data, dtype=float)
    if x.ndim != 2 or x.shape[1] != len(scaler.center):
        raise ValueError("Data feature count differs from fitted scaler")
    if window < 1 or decision_index < window - 1 or decision_index >= len(x):
        raise ValueError("Decision index must have a complete past window")
    past = x[decision_index - window + 1:decision_index + 1]
    valid = np.isfinite(past) & scaler.observed_train[None, :]
    z = np.zeros_like(past)
    np.subtract(past, scaler.center, out=z, where=valid)
    z /= scaler.scale
    z[~valid] = 0.0
    # Fixed monotone map to [0,1], retaining sign relative to the train median.
    # Unlike per-window min/max, it preserves absolute amplitude between windows.
    bounded = 0.5 * (1.0 + np.tanh(z / 3.0))
    images = []
    for j in range(x.shape[1]):
        u = bounded[:, j]
        sin = np.sqrt(np.maximum(0.0, 1.0 - u * u))
        mask = valid[:, j, None] & valid[None, :, j]
        gasf = np.outer(u, u) - np.outer(sin, sin)
        gadf = np.outer(sin, u) - np.outer(u, sin)
        images.extend([np.where(mask, gasf, 0), np.where(mask, gadf, 0), mask.astype(float)])
    return {
        "images": np.asarray(images, dtype=np.float32),
        "normalized_window": z.astype(np.float32),
        "bounded_window": bounded.astype(np.float32),
        "valid_window": valid,
        "missing_fraction": 1.0 - valid.mean(axis=0),
        "saturation_fraction": ((np.abs(z) > 9.0) & valid).sum(axis=0) / np.maximum(1, valid.sum(axis=0)),
        "train_end_exclusive": scaler.train_end_exclusive,
        "decision_index": int(decision_index),
    }


def joint_target(brent_usd, eurusd, decision_index, horizon=10):
    """Future joint target and exact unhedged EUR import cost change.

    EURUSD is USD per EUR. Horizon counts rows in the supplied common session
    calendar. No filling is performed; invalid endpoint quotes are rejected.
    Future values are labels only, never representation inputs.
    """
    b, fx = np.asarray(brent_usd, dtype=float), np.asarray(eurusd, dtype=float)
    if b.ndim != 1 or fx.shape != b.shape or horizon < 1:
        raise ValueError("Expected equal 1D price series and positive horizon")
    end = decision_index + horizon
    if decision_index < 0 or end >= len(b):
        raise ValueError("Future label is not yet mature")
    points = np.array([b[decision_index], b[end], fx[decision_index], fx[end]])
    if not np.all(np.isfinite(points) & (points > 0)):
        raise ValueError("Target requires positive observed endpoint quotes")
    r_b, r_fx = np.log(b[end] / b[decision_index]), np.log(fx[end] / fx[decision_index])
    return np.array([r_b, r_fx]), float(np.expm1(r_b - r_fx))
