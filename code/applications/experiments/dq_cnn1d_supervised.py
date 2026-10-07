#!/usr/bin/env python3
"""Supervised 1D CNN for multivariate price-series data-quality alerts.

Synthetic defects are injected into real, non-overlapping return windows. Model
selection and alert thresholds use a chronological validation period; the later
test period is not used for fitting or calibration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ("BRENT", "WTI", "DTWEXBGS", "COPPER", "EUROSTOXX50")
WINDOW = 20
WINDOW_STRIDE = 5
FIT_END = pd.Timestamp("2018-12-31")
VAL_END = pd.Timestamp("2023-12-31")
FP_TARGET = 0.05
FAMILIES = ("decoupling", "stale", "reversible_jump")


class DQConv1D(nn.Module):
    def __init__(self, n_assets: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(n_assets, 24, kernel_size=3, padding=1), nn.GELU(),
            nn.Conv1d(24, 32, kernel_size=3, padding=1), nn.GELU(),
            nn.Conv1d(32, 32, kernel_size=3, padding=1), nn.GELU(),
        )
        self.head = nn.Sequential(nn.Linear(64, 24), nn.GELU(), nn.Linear(24, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.features(x.transpose(1, 2))
        pooled = torch.cat([h.mean(dim=2), h.amax(dim=2)], dim=1)
        return self.head(pooled).squeeze(-1)


def load_windows(panel_path: Path, window: int = WINDOW, stride: int = WINDOW_STRIDE):
    raw = panel_path.read_bytes()
    frame = pd.read_csv(panel_path, parse_dates=["date"])
    frame = frame[["date", *ASSETS]].dropna().reset_index(drop=True)
    prices = frame[list(ASSETS)].to_numpy(dtype=float)
    log_cols = [i for i, asset in enumerate(ASSETS) if asset != "WTI"]
    if np.any(prices[:, log_cols] <= 0):
        raise ValueError("Las series logarítmicas seleccionadas requieren valores positivos")
    # WTI is represented as dollar price changes to preserve its genuine 2020
    # negative settlement; all other channels use log returns.
    returns = np.empty((len(prices) - 1, len(ASSETS)), dtype=float)
    returns[:, log_cols] = np.diff(np.log(prices[:, log_cols]), axis=0)
    wti_idx = ASSETS.index("WTI")
    returns[:, wti_idx] = np.diff(prices[:, wti_idx])
    dates = pd.DatetimeIndex(frame["date"].iloc[1:])
    # Causal volatility normalization; each row uses only returns before its date.
    scaled = np.full_like(returns, np.nan)
    for j in range(returns.shape[1]):
        history = pd.Series(returns[:, j])
        mean = history.rolling(60, min_periods=20).mean().shift(1).to_numpy()
        sigma = history.rolling(60, min_periods=20).std().shift(1).to_numpy()
        valid = np.isfinite(mean) & np.isfinite(sigma) & (sigma > 1e-10)
        scaled[valid, j] = (returns[valid, j] - mean[valid]) / sigma[valid]
    windows, starts, ends = [], [], []
    for stop in range(window, len(scaled) + 1, stride):
        block = scaled[stop - window:stop]
        if np.isfinite(block).all():
            windows.append(block.astype(np.float32))
            starts.append(dates[stop - window])
            ends.append(dates[stop - 1])
    return (np.asarray(windows), pd.DatetimeIndex(starts), pd.DatetimeIndex(ends),
            hashlib.sha256(raw).hexdigest())


def inject(window: np.ndarray, family: str, rng: np.random.Generator) -> np.ndarray:
    out = window.copy()
    target = 0  # Brent; peers remain as observed.
    if family == "decoupling":
        # Circular shift preserves Brent's marginal values and most serial shape,
        # while breaking its date alignment with the peer channels.
        shift = int(rng.integers(2, len(out) - 1))
        out[:, target] = np.roll(out[:, target], shift)
    elif family == "stale":
        out[:, target] = 0.0
    elif family == "reversible_jump":
        t = int(rng.integers(2, len(out) - 2))
        jump = float(rng.choice([-1.0, 1.0]) * 8.0)
        out[t, target] += jump
        out[t + 1, target] -= jump
    else:
        raise ValueError(f"Familia desconocida: {family}")
    return out


def make_labeled(windows: np.ndarray, seed: int):
    rng = np.random.default_rng(seed)
    samples = [np.clip(x, -15.0, 15.0) for x in windows]
    labels = [0] * len(windows)
    for x in windows:
        for family in FAMILIES:
            samples.append(np.clip(inject(x, family, rng), -15.0, 15.0))
            labels.append(1)
    return np.asarray(samples, dtype=np.float32), np.asarray(labels, dtype=np.float32)


def score_cross_asset(windows: np.ndarray) -> np.ndarray:
    scores = np.zeros(len(windows), dtype=float)
    for i, block in enumerate(windows):
        y, x = block[:, 0], block[:, 1:]
        design = np.column_stack([np.ones(len(y)), x])
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual = y - design @ beta
        total = np.sum((y - y.mean()) ** 2)
        r2 = 0.0 if total <= 1e-12 else 1.0 - np.sum(residual ** 2) / total
        scores[i] = 1.0 - r2
    return scores


def score_3sigma(windows: np.ndarray) -> np.ndarray:
    return np.max(np.abs(windows), axis=(1, 2))


def fit_cnn(train_windows: np.ndarray, validation_windows: np.ndarray,
            seed: int = 42, epochs: int = 50) -> DQConv1D:
    torch.manual_seed(seed)
    np.random.seed(seed)
    x_train, y_train = make_labeled(train_windows, seed)
    x_val, y_val = make_labeled(validation_windows, seed + 1)
    train_loader = DataLoader(TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
                              batch_size=128, shuffle=True)
    val_x, val_y = torch.from_numpy(x_val), torch.from_numpy(y_val)
    model = DQConv1D(train_windows.shape[2])
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss()
    best_loss, best_state, stale_epochs = float("inf"), None, 0
    for _ in range(epochs):
        model.train()
        for xb, yb in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(val_x), val_y))
        if val_loss < best_loss - 1e-5:
            best_loss = val_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= 8:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model


def score_cnn(model: DQConv1D, windows: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        x = np.clip(windows, -15.0, 15.0).astype(np.float32)
        return torch.sigmoid(model(torch.from_numpy(x))).numpy()


def threshold_at_fp(scores: np.ndarray, fp: float = FP_TARGET) -> float:
    if not len(scores):
        raise ValueError("Se necesitan scores limpios para calibrar el umbral")
    allowed = int(np.floor(fp * len(scores)))
    rank = max(0, len(scores) - allowed - 1)
    return float(np.sort(scores)[rank])


def evaluate_detector(clean_val: np.ndarray, clean_test: np.ndarray,
                      injected_test: dict[str, np.ndarray], scorer):
    val_score = scorer(clean_val)
    threshold = threshold_at_fp(val_score)
    clean_score = scorer(clean_test)
    return {
        "threshold": threshold,
        "validation_false_positive_rate": float(np.mean(val_score > threshold)),
        "test_false_positive_rate": float(np.mean(clean_score > threshold)),
        "recall_by_family": {
            name: float(np.mean(scorer(samples) > threshold))
            for name, samples in injected_test.items()
        },
    }


def run(panel_path: Path, output_dir: Path, seed: int = 42):
    windows, starts, ends, data_hash = load_windows(panel_path)
    train = windows[ends <= FIT_END]
    validation = windows[(starts > FIT_END) & (ends <= VAL_END)]
    test = windows[starts > VAL_END]
    if min(len(train), len(validation), len(test)) < 20:
        raise ValueError("Insuficientes ventanas en uno de los bloques temporales")

    cnn = fit_cnn(train, validation, seed=seed)
    rng = np.random.default_rng(seed + 2)
    injected = {
        family: np.asarray([inject(x, family, rng) for x in test], dtype=np.float32)
        for family in FAMILIES
    }
    detectors = {
        "cnn_1d_supervisada": lambda x: score_cnn(cnn, x),
        "cross_asset_1_minus_r2": score_cross_asset,
        "3sigma_vol_normalizada": score_3sigma,
    }
    results = {
        name: evaluate_detector(validation, test, injected, scorer)
        for name, scorer in detectors.items()
    }
    output = {
        "protocol": {
            "assets": list(ASSETS),
            "peer_selection": "top absolute training-period return correlations with BRENT, excluding derived ratios: WTI, DTWEXBGS, COPPER, EUROSTOXX50",
            "window_sessions": WINDOW,
            "window_stride_sessions": WINDOW_STRIDE,
            "fit_end": str(FIT_END.date()), "validation_end": str(VAL_END.date()),
            "test_start": str(starts[starts > VAL_END][0].date()),
            "target_false_positive_rate": FP_TARGET,
            "normalization": "rolling 60-session mean/sd shifted one session; WTI uses dollar changes to preserve negative settlement; CNN input clipped to +/-15",
            "injected_families": list(FAMILIES), "seed": seed,
            "source": str(panel_path), "sha256": data_hash,
            "n_train_windows": len(train), "n_validation_windows": len(validation),
            "n_test_windows": len(test),
        },
        "results": results,
        "interpretation": "Synthetic injected-defect benchmark only; no claim about real defect prevalence or operational benefit.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    rows = []
    for detector, detail in results.items():
        for family, recall in detail["recall_by_family"].items():
            rows.append({"detector": detector, "family": family, "recall": recall,
                         "threshold": detail["threshold"],
                         "validation_fpr": detail["validation_false_positive_rate"],
                         "test_clean_fpr": detail["test_false_positive_rate"]})
    pd.DataFrame(rows).to_csv(output_dir / "scores.csv", index=False)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "reports" / "dq_cnn1d_supervised")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(run(args.panel, args.output, args.seed), indent=2))


if __name__ == "__main__":
    main()
