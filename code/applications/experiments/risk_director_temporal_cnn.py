"""Temporal CNN for the CNN-info-Risk Director chain.

The model consumes rolling windows of risk and external variables and predicts the
mean squared Brent log-return over the next ten observations. It is compared with
a tabular EWMA/HAR + external-information model on the same temporal folds.

The uncertainty layer uses Monte Carlo dropout as a lightweight Bayesian
approximation. It is not a full Bayesian network and not reinforcement learning.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from harness import Experiment, ExperimentResult, RunContext  # noqa: E402
from experiments.risk_director_scientific_eval import (  # noqa: E402
    _default_panel_path,
    _sha256,
    block_interval,
    build_frame,
    predict,
    qlike,
)

WINDOW = 64
EPOCHS = 80
PATIENCE = 10
BATCH = 128
SEED = 42

RISK_COLS = ["rv1", "rv5", "rv22", "ret5", "ret20", "vol20"]


class TemporalCNN(nn.Module):
    def __init__(self, channels: int, dropout: float = 0.15):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(channels, 24, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Conv1d(24, 24, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Linear(24, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.net(x).squeeze(-1)
        return self.head(z).squeeze(-1)


def _qlike_loss(log_forecast: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    return torch.mean(log_forecast + y * torch.exp(-log_forecast))


def _feature_cols(frame: pd.DataFrame) -> List[str]:
    extra = [c for c in frame.columns if c.startswith("x_")]
    return RISK_COLS + extra


def _make_sequences(frame: pd.DataFrame, cols: List[str]) -> Tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    clean = frame.dropna(subset=cols + ["target", "label_end"]).copy()
    x_raw = clean[cols].to_numpy(dtype=np.float32)
    y_raw = clean["target"].to_numpy(dtype=np.float32)
    dates = clean.index
    xs: List[np.ndarray] = []
    ys: List[float] = []
    ds: List[pd.Timestamp] = []
    for i in range(WINDOW - 1, len(clean)):
        xs.append(x_raw[i - WINDOW + 1:i + 1].T)
        ys.append(float(y_raw[i]))
        ds.append(dates[i])
    return pd.DatetimeIndex(ds), np.stack(xs), np.asarray(ys, dtype=np.float32)


def _standardize(x_train: np.ndarray, *others: np.ndarray) -> Tuple[np.ndarray, ...]:
    # x shape: n, channels, window. Standardize channel-wise using train only.
    mu = x_train.transpose(1, 0, 2).reshape(x_train.shape[1], -1).mean(axis=1)
    sd = x_train.transpose(1, 0, 2).reshape(x_train.shape[1], -1).std(axis=1)
    sd = np.maximum(sd, 1e-6)
    out = []
    for x in (x_train,) + others:
        z = (x - mu[None, :, None]) / sd[None, :, None]
        out.append(np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32))
    return tuple(out)


def _fit_cnn(x_train: np.ndarray, y_train: np.ndarray, off_train: np.ndarray, x_valid: np.ndarray, y_valid: np.ndarray, off_valid: np.ndarray) -> Tuple[TemporalCNN, Dict[str, float]]:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    torch.set_num_threads(2)
    model = TemporalCNN(x_train.shape[1])
    with torch.no_grad():
        model.head.bias.zero_()
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    ds = TensorDataset(torch.tensor(x_train), torch.tensor(y_train), torch.tensor(off_train.astype(np.float32)))
    loader = DataLoader(ds, batch_size=BATCH, shuffle=True, generator=torch.Generator().manual_seed(SEED))
    xv = torch.tensor(x_valid)
    yv = torch.tensor(y_valid)
    ov = torch.tensor(off_valid.astype(np.float32))
    best_state = None
    best = float("inf")
    bad = 0
    hist: List[float] = []
    for _epoch in range(EPOCHS):
        model.train()
        for xb, yb, ob in loader:
            opt.zero_grad()
            loss = _qlike_loss(ob + model(xb), yb)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val = float(_qlike_loss(ov + model(xv), yv).item())
        hist.append(val)
        if val < best - 1e-5:
            best = val
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            bad = 0
        else:
            bad += 1
        if bad >= PATIENCE:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, {"best_valid_qlike": best, "epochs": len(hist)}


def _predict_mc(model: TemporalCNN, x: np.ndarray, offset: np.ndarray, draws: int = 30) -> Dict[str, np.ndarray]:
    xt = torch.tensor(x)
    off = torch.tensor(offset.astype(np.float32))
    preds = []
    model.train()  # keep dropout active for MC uncertainty.
    with torch.no_grad():
        for _ in range(draws):
            preds.append(torch.exp(off + model(xt)).cpu().numpy())
    arr = np.stack(preds)
    return {
        "mean": arr.mean(axis=0),
        "p10": np.quantile(arr, 0.10, axis=0),
        "p90": np.quantile(arr, 0.90, axis=0),
        "sd": arr.std(axis=0),
    }


def run_temporal_cnn(panel_path: Path, out_dir: Path) -> Dict[str, object]:
    frame = build_frame(panel_path)
    cols = _feature_cols(frame)
    dates, x_all, y_all = _make_sequences(frame, cols)
    f_seq = pd.DataFrame({"target": y_all}, index=dates)
    f_seq["label_end"] = frame.loc[dates, "label_end"].to_numpy()

    records: List[pd.DataFrame] = []
    folds: List[Dict[str, object]] = []
    for year in range(2024, int(dates.max().year) + 1):
        test_mask = dates.year == year
        if int(test_mask.sum()) < 30:
            continue
        start = dates[test_mask].min()
        available_mask = (dates < start) & (pd.to_datetime(f_seq["label_end"]).to_numpy() < np.datetime64(start))
        available_idx = np.flatnonzero(available_mask)
        if len(available_idx) < 1250:
            continue
        valid_idx = available_idx[-252:]
        train_idx = available_idx[:-252]
        test_idx = np.flatnonzero(test_mask)
        if len(train_idx) < 900:
            continue

        # Tabular same-period comparator from current scientific evaluation.
        frame_test = frame.loc[dates[test_idx]].dropna(subset=cols)
        frame_available = frame[(frame.index < start) & (frame["label_end"] < start)].dropna(subset=cols)
        frame_valid = frame_available.iloc[-252:]
        frame_train = frame_available.iloc[:-252]
        scores = {fam: float(np.mean(qlike(frame_valid["target"].to_numpy(), predict(frame_train, frame_valid, fam, [])))) for fam in ["EWMA", "HAR"]}
        selected = min(scores, key=scores.get)
        offset_col = "ewma" if selected == "EWMA" else "rv22"
        offsets = np.log(frame.loc[dates, offset_col].clip(lower=1e-12).to_numpy(dtype=float))

        x_train, x_valid, x_test = _standardize(x_all[train_idx], x_all[valid_idx], x_all[test_idx])
        y_train, y_valid, y_test = y_all[train_idx], y_all[valid_idx], y_all[test_idx]
        model, fit = _fit_cnn(x_train, y_train, offsets[train_idx], x_valid, y_valid, offsets[valid_idx])
        mc = _predict_mc(model, x_test, offsets[test_idx])

        tabular = predict(frame_available, frame_test, selected, cols[6:])  # external cols only; risk cols are in EWMA/HAR.
        base = predict(frame_available, frame_test, selected, [])

        row = pd.DataFrame({
            "date": dates[test_idx],
            "year": year,
            "target": y_test,
            "selected": selected,
            "base": base[:len(y_test)],
            "tabular_external": tabular[:len(y_test)],
            "cnn_mean": mc["mean"],
            "cnn_p10": mc["p10"],
            "cnn_p90": mc["p90"],
            "cnn_sd": mc["sd"],
        })
        row["delta_qlike_cnn_minus_tabular"] = qlike(row.target.to_numpy(), row.cnn_mean.to_numpy()) - qlike(row.target.to_numpy(), row.tabular_external.to_numpy())
        row["delta_qlike_cnn_minus_base"] = qlike(row.target.to_numpy(), row.cnn_mean.to_numpy()) - qlike(row.target.to_numpy(), row.base.to_numpy())
        records.append(row)
        folds.append({
            "year": year,
            "selected_tabular_base": selected,
            "validation_qlike_base": scores,
            "train_n": int(len(train_idx)),
            "validation_n": int(len(valid_idx)),
            "test_n": int(len(test_idx)),
            **fit,
        })
    if not records:
        raise RuntimeError("no CNN folds produced")
    forecasts = pd.concat(records, ignore_index=True)
    d_tab = forecasts["delta_qlike_cnn_minus_tabular"].to_numpy(dtype=float)
    d_base = forecasts["delta_qlike_cnn_minus_base"].to_numpy(dtype=float)
    annual = forecasts.groupby("year").agg(
        n=("target", "size"),
        delta_qlike_cnn_minus_tabular=("delta_qlike_cnn_minus_tabular", "mean"),
        delta_qlike_cnn_minus_base=("delta_qlike_cnn_minus_base", "mean"),
        mean_cnn_uncertainty=("cnn_sd", "mean"),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    forecasts.to_csv(out_dir / "forecasts.csv", index=False)
    annual.to_csv(out_dir / "per_year.csv")
    summary = {
        "status": "provisional_temporal_cnn_mc_dropout",
        "panel_path": str(panel_path),
        "panel_sha256": _sha256(panel_path),
        "window": WINDOW,
        "features": cols,
        "n_forecasts": int(len(forecasts)),
        "date_min": str(pd.to_datetime(forecasts["date"]).min().date()),
        "date_max": str(pd.to_datetime(forecasts["date"]).max().date()),
        "delta_qlike_cnn_minus_tabular": float(np.mean(d_tab)),
        "delta_qlike_cnn_minus_base": float(np.mean(d_base)),
        "block_ci_95_cnn_minus_tabular": {str(b): block_interval(d_tab, b) for b in [10, 20, 60]},
        "block_ci_95_cnn_minus_base": {str(b): block_interval(d_base, b) for b in [10, 20, 60]},
        "folds": folds,
        "limitations": [
            "First CPU temporal CNN; implemented as multiplicative adjustment over EWMA/HAR to avoid free-scale variance drift.",
            "MC dropout is approximate Bayesian uncertainty, not a full Bayesian network.",
            "External variables are dated by observation; operational lags still require deployment policy.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


class RiskDirectorTemporalCNNExperiment(Experiment):
    id = "risk_director_temporal_cnn"
    title = "CNN temporal con incertidumbre para Risk Director"

    def preflight(self, ctx: RunContext) -> List[str]:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        return [] if panel_path.exists() else [f"no existe panel_path={panel_path}"]

    def run(self, ctx: RunContext) -> ExperimentResult:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        out = Path(ctx.experiment_dir())
        summary = run_temporal_cnn(panel_path, out)
        decision = "review"
        return ExperimentResult(
            metrics={k: v for k, v in summary.items() if k not in {"folds", "limitations", "features"}},
            artifacts=[str(out / "summary.json"), str(out / "forecasts.csv"), str(out / "per_year.csv")],
            decision=decision,
            notes=f"delta CNN-tabular={summary['delta_qlike_cnn_minus_tabular']:.6f}; pendiente challenge",
        )
