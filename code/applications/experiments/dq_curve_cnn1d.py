#!/usr/bin/env python3
"""Experimental 1D CNN for cross-tenor yield-curve shape anomalies.

Uses observed Treasury CMT yields as a curve-shape proxy, not as a bootstrapped
zero curve. Synthetic local tenor bumps provide known labels; thresholds are
calibrated chronologically and evaluated on later dates.
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
NODES = ("DGS2", "DGS10", "DGS30")
TENOR_YEARS = np.array([2.0, 10.0, 30.0])
FIT_END = pd.Timestamp("2018-12-31")
VAL_END = pd.Timestamp("2023-12-31")
FP_TARGET = 0.02
TRAIN_BUMP_BPS = (2.0, 4.0)
TEST_BUMP_BPS = (1.0, 2.0, 3.0, 4.0, 5.0, 8.0)


class CurveCNN1D(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(1, 16, kernel_size=3, padding=1), nn.GELU(),
            nn.Conv1d(16, 24, kernel_size=3, padding=1), nn.GELU(),
        )
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(24 * len(NODES), 24),
                                  nn.GELU(), nn.Linear(24, 1))

    def forward(self, x):
        return self.head(self.conv(x.unsqueeze(1))).squeeze(-1)


def load_curves(path: Path):
    raw = path.read_bytes()
    frame = pd.read_csv(path, parse_dates=["date"])
    frame = frame[["date", *NODES]].copy()
    for col in NODES:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna().sort_values("date").reset_index(drop=True)
    # CMT inputs are quoted in percentage points; model inputs are centered bp.
    values = frame[list(NODES)].to_numpy(dtype=float) * 100.0
    centered = values - values.mean(axis=1, keepdims=True)
    return (pd.DatetimeIndex(frame["date"]), values, centered.astype(np.float32),
            hashlib.sha256(raw).hexdigest())


def inject_bump(curves_bp: np.ndarray, amplitude_bp: float,
                rng: np.random.Generator, node: int | None = None) -> np.ndarray:
    out = curves_bp.copy()
    if node is None:
        node = int(rng.integers(1, len(NODES)))
    sign = float(rng.choice([-1.0, 1.0]))
    out[:, node] += sign * amplitude_bp
    return out


def make_labeled(curves_bp: np.ndarray, rng: np.random.Generator):
    x = [row.copy() for row in curves_bp]
    y = [0] * len(curves_bp)
    for row in curves_bp:
        amplitude = float(rng.uniform(*TRAIN_BUMP_BPS))
        x.append(inject_bump(row[None, :], amplitude, rng, node=1)[0])
        y.append(1)
    return np.asarray(x, np.float32), np.asarray(y, np.float32)


def fit_model(train: np.ndarray, validation: np.ndarray, seed: int,
              epochs: int = 60) -> CurveCNN1D:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    x_train, y_train = make_labeled(train, rng)
    x_val, y_val = make_labeled(validation, np.random.default_rng(seed + 1))
    loader = DataLoader(TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
                        batch_size=128, shuffle=True)
    xv, yv = torch.from_numpy(x_val), torch.from_numpy(y_val)
    model = CurveCNN1D()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss()
    best, state, patience = float("inf"), None, 0
    for _ in range(epochs):
        model.train()
        for xb, yb in loader:
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(xv), yv))
        if val_loss < best - 1e-5:
            best, state, patience = val_loss, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            patience += 1
            if patience >= 8:
                break
    if state is not None:
        model.load_state_dict(state)
    model.eval()
    return model


def cnn_score(model: CurveCNN1D, curves_bp: np.ndarray) -> np.ndarray:
    x = curves_bp - curves_bp.mean(axis=1, keepdims=True)
    with torch.no_grad():
        return torch.sigmoid(model(torch.from_numpy(x.astype(np.float32)))).numpy()


def linear_shape_score(curves_bp: np.ndarray) -> np.ndarray:
    """10Y deviation from log-tenor interpolation between 2Y and 30Y."""
    x = np.log(TENOR_YEARS)
    j = 1
    w = (x[j] - x[0]) / (x[2] - x[0])
    fitted = curves_bp[:, 0] * (1.0 - w) + curves_bp[:, 2] * w
    return np.abs(curves_bp[:, j] - fitted)


def three_sigma_node_stats(values_pct: np.ndarray):
    changes_bp = np.diff(values_pct, axis=0, prepend=values_pct[[0]]) * 100.0
    means, stds = np.full_like(changes_bp, np.nan), np.full_like(changes_bp, np.nan)
    for j in range(changes_bp.shape[1]):
        s = pd.Series(changes_bp[:, j])
        means[:, j] = s.rolling(60, min_periods=20).mean().shift(1).to_numpy()
        stds[:, j] = s.rolling(60, min_periods=20).std().shift(1).to_numpy()
    return changes_bp, means, stds


def three_sigma_node_score(values_pct: np.ndarray) -> np.ndarray:
    changes, means, stds = three_sigma_node_stats(values_pct)
    z = np.full_like(changes, np.nan)
    valid = np.isfinite(means) & np.isfinite(stds) & (stds > 1e-9)
    z[valid] = ((changes - means)[valid] / stds[valid])
    score = np.full(len(z), np.nan)
    for i, row in enumerate(z):
        if np.isfinite(row).any():
            score[i] = np.nanmax(np.abs(row))
    return score


def threshold_at_fp(scores: np.ndarray, fp: float = FP_TARGET) -> float:
    scores = scores[np.isfinite(scores)]
    allowed = int(np.floor(fp * len(scores)))
    return float(np.sort(scores)[max(0, len(scores) - allowed - 1)])


def run(panel_path: Path, output_dir: Path, seed: int = 42):
    dates, values_pct, curves_bp, data_hash = load_curves(panel_path)
    # Discard warm-up needed by the causal 60-session 3σ baseline.
    valid = np.isfinite(three_sigma_node_score(values_pct))
    dates, values_pct, curves_bp = dates[valid], values_pct[valid], curves_bp[valid]
    train = curves_bp[dates <= FIT_END]
    val_mask = (dates > FIT_END) & (dates <= VAL_END)
    test_mask = dates > VAL_END
    validation, test = curves_bp[val_mask], curves_bp[test_mask]
    if min(len(train), len(validation), len(test)) < 100:
        raise ValueError("Insuficientes curvas para train/validación/test")

    model = fit_model(train, validation, seed)
    scores = {
        "cnn_1d": cnn_score(model, curves_bp),
        "linear_log_tenor_residual": linear_shape_score(curves_bp),
        "3sigma_per_node": three_sigma_node_score(values_pct),
    }
    thresholds = {name: threshold_at_fp(score[val_mask]) for name, score in scores.items()}
    validation_fpr = {name: float(np.mean(score[val_mask] > thresholds[name]))
                       for name, score in scores.items()}
    clean_test_fpr = {name: float(np.mean(score[test_mask] > thresholds[name]))
                      for name, score in scores.items()}

    rng = np.random.default_rng(seed + 2)
    recall = {}
    for amplitude in TEST_BUMP_BPS:
        test_raw_bp = values_pct[test_mask] * 100.0
        injected_raw = inject_bump(test_raw_bp, amplitude, rng, node=1)
        injected = injected_raw - injected_raw.mean(axis=1, keepdims=True)
        # Apply exactly the same feature transforms used for clean scores.
        injected_scores = {
            "cnn_1d": cnn_score(model, injected),
            "linear_log_tenor_residual": linear_shape_score(injected),
        }
        # Pointwise 3σ needs the time series, so inject into the raw test curve
        # and score its node changes against the historical causal baseline.
        indices = np.flatnonzero(test_mask)
        _, means, stds = three_sigma_node_stats(values_pct)
        point_scores = []
        for i, t in enumerate(indices):
            if t == 0:
                point_scores.append(np.nan)
                continue
            injected_change = injected_raw[i] - values_pct[t - 1] * 100.0
            valid_nodes = np.isfinite(means[t]) & np.isfinite(stds[t]) & (stds[t] > 1e-9)
            z = np.abs((injected_change[valid_nodes] - means[t, valid_nodes]) /
                       stds[t, valid_nodes])
            point_scores.append(float(np.max(z)) if len(z) else np.nan)
        injected_scores["3sigma_per_node"] = np.asarray(point_scores)
        recall[str(int(amplitude))] = {
            name: float(np.mean(sc > thresholds[name]))
            for name, sc in injected_scores.items()
        }

    report = {
        "protocol": {
            "series": list(NODES), "tenors_years": TENOR_YEARS.tolist(),
            "instrument_status": "US Treasury constant-maturity yields (CMT), not bootstrapped zero-coupon rates",
            "fit_end": str(FIT_END.date()), "validation_end": str(VAL_END.date()),
            "test_start": str(dates[test_mask][0].date()), "test_end": str(dates[test_mask][-1].date()),
            "n_train": len(train), "n_validation": len(validation), "n_test": len(test),
            "false_positive_target": FP_TARGET, "training_bumps_bp": list(TRAIN_BUMP_BPS),
            "test_bumps_bp": list(TEST_BUMP_BPS), "seed": seed,
            "source": str(panel_path), "sha256": data_hash,
            "limitations": ["only DGS2/DGS10/DGS30 are available; DGS5 is absent",
                            "GBP base/SONIA pair is not in the panel",
                            "three CMT nodes cannot validate a production Svensson ZC curve",
                            "synthetic perturbations are not real defect labels"],
        },
        "thresholds": thresholds,
        "validation_false_positive_rate": validation_fpr,
        "clean_test_false_positive_rate": clean_test_fpr,
        "recall_by_bump_size_bp": recall,
        "interpretation": "Exploratory synthetic defect test; no production claim.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame([{"size_bp": size, "detector": detector, "recall": value}
                  for size, row in recall.items() for detector, value in row.items()]
                 ).to_csv(output_dir / "recall_by_size.csv", index=False)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "reports" / "dq_curve_cnn1d")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(run(args.panel, args.output, args.seed), indent=2))


if __name__ == "__main__":
    main()
