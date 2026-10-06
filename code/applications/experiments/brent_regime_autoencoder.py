#!/usr/bin/env python3
"""Exploratory, walk-forward Brent return autoencoder with scheduled refits.

The autoencoder sees only trailing daily log-return windows. It is unsupervised:
future downside labels are reserved for evaluation and never enter fitting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd
import torch
from sklearn.cluster import KMeans
from sklearn.metrics import average_precision_score, roc_auc_score
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = ROOT / "data" / "brent_fred_daily.csv"
DEFAULT_OUT = ROOT / "results" / "reports" / "brent_regime_autoencoder"
LOOKBACK = 32
HORIZON = 10
REFIT_SESSIONS = 252
TRAIN_SESSIONS = 5 * REFIT_SESSIONS
MIN_INITIAL_SESSIONS = 10 * REFIT_SESSIONS
SEED = 42


class ReturnAutoencoder(nn.Module):
    """Variational autoencoder with an explicit Gaussian latent prior."""

    def __init__(self, width: int = LOOKBACK, latent_dim: int = 4):
        super().__init__()
        self.encoder_body = nn.Sequential(nn.Linear(width, 16), nn.GELU())
        self.mu = nn.Linear(16, latent_dim)
        self.logvar = nn.Linear(16, latent_dim)
        self.decoder = nn.Sequential(nn.Linear(latent_dim, 16), nn.GELU(), nn.Linear(16, width))

    def encode(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        hidden = self.encoder_body(x)
        return self.mu(hidden), self.logvar(hidden).clamp(-10.0, 10.0)

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        return self.decoder(z)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        mu, logvar = self.encode(x)
        z = mu + torch.randn_like(mu) * torch.exp(0.5 * logvar) if self.training else mu
        return self.decode(z)


def build_windows(returns: np.ndarray, lookback: int = LOOKBACK) -> Tuple[np.ndarray, np.ndarray]:
    """Return causal trailing windows and their ending return indices."""
    values = np.asarray(returns, dtype=np.float32)
    if values.ndim != 1 or len(values) < lookback:
        raise ValueError("returns must be a 1D array at least as long as lookback")
    ends = np.arange(lookback - 1, len(values))
    windows = np.stack([values[i - lookback + 1:i + 1] for i in ends])
    return windows, ends


def _scale(train: np.ndarray, *others: np.ndarray) -> Tuple[np.ndarray, ...]:
    center = float(train.mean())
    scale = max(float(train.std()), 1e-8)
    return tuple(((x - center) / scale).astype(np.float32) for x in (train,) + others)


def _fit_model(train: np.ndarray, valid: np.ndarray, seed: int) -> Tuple[ReturnAutoencoder, Dict[str, float]]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(2)
    model = ReturnAutoencoder()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loader = DataLoader(
        TensorDataset(torch.from_numpy(train)), batch_size=64, shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )
    x_valid = torch.from_numpy(valid)
    best_loss, best_state, patience = float("inf"), None, 0
    epochs = 0
    for epoch in range(80):
        model.train()
        for (batch,) in loader:
            optimizer.zero_grad()
            reconstruction = nn.functional.mse_loss(model(batch), batch)
            mu, logvar = model.encode(batch)
            kl = -0.5 * torch.mean(1.0 + logvar - mu.square() - logvar.exp())
            loss = reconstruction + 0.01 * kl
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            valid_loss = float(nn.functional.mse_loss(model(x_valid), x_valid))
        epochs = epoch + 1
        if valid_loss < best_loss - 1e-6:
            best_loss = valid_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
        if patience >= 8:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, {"best_valid_mse": best_loss, "epochs": epochs}


def reconstruction_error(model: ReturnAutoencoder, windows: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        x = torch.from_numpy(np.asarray(windows, dtype=np.float32))
        return nn.functional.mse_loss(model(x), x, reduction="none").mean(dim=1).numpy()


def latent_means(model: ReturnAutoencoder, windows: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        mean, _ = model.encode(torch.from_numpy(np.asarray(windows, dtype=np.float32)))
        return mean.numpy()


def sample_returns(model: ReturnAutoencoder, center: float, scale: float,
                   observation_noise_sd: float, n: int = 512,
                   seed: int = SEED) -> np.ndarray:
    model.eval()
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        z = torch.randn((n, model.mu.out_features), generator=generator)
        mean = model.decode(z)
        noise = torch.randn(mean.shape, generator=generator) * observation_noise_sd
        return ((mean + noise).numpy() * scale + center).astype(np.float64)


def _alerts(score: np.ndarray, threshold: float, cooldown: int = HORIZON) -> np.ndarray:
    alert = np.zeros(len(score), dtype=bool)
    last = -10**9
    for i, value in enumerate(score):
        if np.isfinite(value) and value >= threshold and i - last >= cooldown:
            alert[i] = True
            last = i
    return alert


def _episodes(event: np.ndarray, merge: int = HORIZON) -> np.ndarray:
    starts = np.flatnonzero(event)
    if not len(starts):
        return starts
    return starts[np.r_[True, np.diff(starts) >= merge]]


def _calibrate_threshold(score: np.ndarray, target_reviews_per_year: float = 20.0) -> float:
    best_threshold, best_gap = float("inf"), float("inf")
    for quantile in np.linspace(0.50, 0.999, 100):
        threshold = float(np.quantile(score, quantile))
        reviews = _alerts(score, threshold).sum() * 252.0 / len(score)
        gap = abs(reviews - target_reviews_per_year)
        if gap < best_gap:
            best_threshold, best_gap = threshold, gap
    return best_threshold


def _episode_metrics(alert: np.ndarray, starts: np.ndarray, n: int) -> Dict[str, object]:
    covered = np.zeros(n, dtype=bool)
    hits = []
    for start in starts:
        lo = max(0, int(start) - HORIZON)
        covered[lo:start] = True
        hits.append(bool(alert[lo:start].any()))
    false_alerts = int((alert & ~covered).sum())
    years = max(n / 252.0, 1e-9)
    return {
        "episodes": int(len(starts)),
        "recall": float(np.mean(hits)) if hits else None,
        "false_alerts_per_year": false_alerts / years,
        "reviews_per_year": float(alert.sum()) / years,
    }


def _block_bootstrap_delta(records: pd.DataFrame, candidate: str, baseline: str,
                          block_years: int = 3, draws: int = 5000,
                          seed: int = SEED) -> Dict[str, object]:
    paired = records.pivot(index="year", columns="model", values="recall")[[candidate, baseline]].dropna()
    differences = (paired[candidate] - paired[baseline]).to_numpy(dtype=float)
    if len(differences) < block_years:
        return {"n_years": int(len(differences)), "delta_mean": None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    samples = []
    n_blocks = int(np.ceil(len(differences) / block_years))
    for _ in range(draws):
        starts = rng.integers(0, len(differences), size=n_blocks)
        idx = np.concatenate([
            (start + np.arange(block_years)) % len(differences) for start in starts
        ])[:len(differences)]
        samples.append(float(np.mean(differences[idx])))
    return {
        "n_years": int(len(differences)),
        "block_years": block_years,
        "delta_mean": float(np.mean(differences)),
        "ci95": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
        "bootstrap_probability_delta_positive": float(np.mean(np.asarray(samples) > 0.0)),
    }


def _year_folds(dates: pd.DatetimeIndex) -> Iterable[Tuple[int, np.ndarray, np.ndarray]]:
    for year in range(2000, int(dates.max().year)):
        test = np.flatnonzero(dates.year == year)
        prior = np.flatnonzero(dates.year < year)
        if len(test) < 100 or len(prior) < MIN_INITIAL_SESSIONS:
            continue
        yield year, prior, test


def _evaluate_fold(
    year: int, windows: np.ndarray, ends: np.ndarray, dates: pd.DatetimeIndex,
    returns: np.ndarray, static_model: ReturnAutoencoder, static_center: float,
    static_scale: float,
) -> Tuple[list, list, list]:
    records, fit_records, latent_records = [], [], []
    test_pos = np.flatnonzero((dates[ends] >= pd.Timestamp(year=year, month=1, day=1)) &
                              (dates[ends].year == year))
    if len(test_pos) == 0:
        return records, fit_records, latent_records
    first_test = int(test_pos[0])
    refit_start = dates[ends[first_test]] - pd.DateOffset(years=5)
    train_pos = np.flatnonzero((dates[ends] < dates[ends[first_test]]) &
                               (dates[ends] >= refit_start))
    if len(train_pos) < 3 * REFIT_SESSIONS:
        return records, fit_records, latent_records
    valid_pos = train_pos[-REFIT_SESSIONS:]
    valid_start_idx = int(ends[valid_pos[0]])
    fit_pos = train_pos[(ends[train_pos] < valid_start_idx - LOOKBACK)]
    if len(fit_pos) < 2 * REFIT_SESSIONS:
        return records, fit_records, latent_records

    # Fit and refit use only windows ending strictly before their validation/test periods.
    x_fit, x_valid, x_test = windows[fit_pos], windows[valid_pos], windows[test_pos]
    sx_fit, sx_valid, sx_test = _scale(x_fit, x_valid, x_test)
    adaptive, training = _fit_model(sx_fit, sx_valid, SEED + year)
    adaptive_score = reconstruction_error(adaptive, sx_test)

    static_score = reconstruction_error(
        static_model, (x_test - static_center) / static_scale,
    )
    ewma = pd.Series(np.square(returns)).ewm(alpha=1.0 - 0.94, adjust=False).mean().to_numpy()
    ewma_score = np.sqrt(ewma[ends[test_pos]])
    score_sets = {
        "ae_adaptativo_anual": (adaptive_score, reconstruction_error(adaptive, sx_valid)),
        "ae_congelado": (
            static_score,
            reconstruction_error(static_model, (x_valid - static_center) / static_scale),
        ),
        "ewma_094": (ewma_score, np.sqrt(ewma[ends[valid_pos]])),
    }

    cutoff = pd.Timestamp(year=year, month=1, day=1)
    hist_start = cutoff - pd.DateOffset(years=5)
    fwd = np.full(len(returns), np.nan)
    for i in range(len(returns) - HORIZON):
        fwd[i] = returns[i + 1:i + HORIZON + 1].sum()
    return_dates = dates[1:]
    label_end = np.minimum(np.arange(len(returns)) + HORIZON, len(returns) - 1)
    train_returns = np.flatnonzero(
        (return_dates < cutoff) & (return_dates >= hist_start) &
        (return_dates[label_end] < cutoff) & np.isfinite(fwd)
    )
    label_train = fwd[train_returns]
    label_train = label_train[np.isfinite(label_train)]
    if len(label_train) < 2 * REFIT_SESSIONS:
        return records, fit_records, latent_records
    tail_cut = float(np.quantile(label_train, 0.10))
    event = np.isfinite(fwd) & (fwd < tail_cut)
    label_dates = dates[1:]
    event_starts_all = _episodes(event)
    test_dates = dates[ends[test_pos]]
    test_lo, test_hi = test_dates[0], test_dates[-1]
    starts = np.asarray([
        s for s in event_starts_all
        if label_dates[s] >= test_lo and label_dates[s] <= test_hi
    ], dtype=int)
    test_event = event[ends[test_pos]]

    for name, (score, valid_score) in score_sets.items():
        threshold = _calibrate_threshold(valid_score)
        validation_reviews = _alerts(valid_score, threshold).sum() * 252.0 / len(valid_score)
        alert = _alerts(score, threshold)
        metrics = _episode_metrics(alert, starts - int(ends[test_pos][0]), len(test_pos))
        metrics.update({
            "year": year,
            "model": name,
            "threshold_validation": threshold,
            "target_validation_reviews_per_year": 20.0,
            "validation_reviews_per_year": float(validation_reviews),
            "reconstruction_mse_test": float(np.mean(score)) if name.startswith("ae_") else None,
            "tail_threshold_train": tail_cut,
            "auc_pr_daily_secondary": (
                float(average_precision_score(test_event, score)) if len(np.unique(test_event)) > 1 else None
            ),
            "auc_roc_daily_secondary": (
                float(roc_auc_score(test_event, score)) if len(np.unique(test_event)) > 1 else None
            ),
        })
        records.append(metrics)
        if name == "ae_adaptativo_anual":
            train_latent = latent_means(adaptive, sx_fit)
            test_latent = latent_means(adaptive, sx_test)
            kmeans = KMeans(n_clusters=4, n_init=10, random_state=SEED + year).fit(train_latent)
            states = kmeans.predict(test_latent)
            for j, pos in enumerate(test_pos):
                end = int(ends[pos])
                trajectory = returns[end - LOOKBACK + 1:end + 1]
                cumulative = np.r_[0.0, np.cumsum(trajectory)]
                row = {"date": str(dates[ends[pos]].date()), "year": year,
                       "state": int(states[j]), "reconstruction_mse": float(adaptive_score[j]),
                       "trailing_32d_return": float(np.expm1(trajectory.sum())),
                       "trailing_32d_annualized_vol": float(np.std(trajectory, ddof=1) * np.sqrt(252)),
                       "trailing_32d_drawdown": float(np.min(cumulative - np.maximum.accumulate(cumulative)))}
                row.update({f"latent_{k}": float(test_latent[j, k])
                            for k in range(test_latent.shape[1])})
                latent_records.append(row)
            fit_records.append({"year": year, **training, "n_fit_windows": int(len(fit_pos)),
                                "n_validation_windows": int(len(valid_pos)),
                                "refit_start": str(dates[ends[train_pos[0]]].date()),
                                "refit_end": str(dates[ends[train_pos[-1]]].date())})
    return records, fit_records, latent_records


def run_experiment(data_path: Path = DEFAULT_DATA, out_dir: Path = DEFAULT_OUT) -> Dict[str, object]:
    frame = pd.read_csv(data_path, parse_dates=["date"]).dropna(subset=["BRENT"])
    frame = frame.sort_values("date").drop_duplicates("date")
    prices = frame["BRENT"].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or np.any(prices <= 0):
        raise ValueError("Brent prices must be finite and positive for log returns")
    dates = pd.DatetimeIndex(frame["date"])
    returns = np.diff(np.log(prices))
    return_dates = dates[1:]
    windows, ends = build_windows(returns)
    window_dates = dates[1:][ends]

    # A single frozen model is trained before OOS begins; its scaler stays frozen too.
    static_cutoff = pd.Timestamp("2000-01-01")
    prior = np.flatnonzero(window_dates < static_cutoff)
    valid_pos = prior[-REFIT_SESSIONS:]
    valid_first = int(ends[valid_pos[0]])
    fit_pos = prior[(ends[prior] < valid_first - LOOKBACK)]
    x_fit, x_valid = windows[fit_pos], windows[valid_pos]
    sx_fit, sx_valid = _scale(x_fit, x_valid)
    static_model, static_training = _fit_model(sx_fit, sx_valid, SEED)
    center, scale = float(x_fit.mean()), max(float(x_fit.std()), 1e-8)

    records, fit_records, latent_records = [], [], []
    for year, _, _ in _year_folds(window_dates):
        result, fits, latent = _evaluate_fold(
            year, windows, ends, dates, returns, static_model, center, scale,
        )
        records.extend(result)
        fit_records.extend(fits)
        latent_records.extend(latent)
    if not records:
        raise RuntimeError("No out-of-sample annual folds had enough train/validation data")

    out_dir.mkdir(parents=True, exist_ok=True)
    predictions = pd.DataFrame(records)
    predictions.to_csv(out_dir / "annual_metrics.csv", index=False)
    pd.DataFrame(fit_records).to_csv(out_dir / "refit_log.csv", index=False)
    pd.DataFrame(latent_records).to_csv(out_dir / "latent_states.csv", index=False)
    grouped = predictions.groupby("model", as_index=False).agg(
        mean_episode_recall=("recall", "mean"),
        mean_false_alerts_per_year=("false_alerts_per_year", "mean"),
        mean_reviews_per_year=("reviews_per_year", "mean"),
        mean_test_reconstruction_mse=("reconstruction_mse_test", "mean"),
    )
    summary = {
        "experiment": "brent_regime_autoencoder",
        "decision": "exploratory",
        "source": str(data_path.name),
        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "date_start": str(dates.min().date()),
        "date_end": str(dates.max().date()),
        "n_prices": int(len(prices)),
        "architecture": {"input": LOOKBACK, "latent_dim": 4, "hidden": 16,
                          "prior": "N(0,I)", "optimizer": "AdamW",
                          "loss": "MSE + 0.01*KL", "seed": SEED},
        "adaptation": {"cadence_sessions": REFIT_SESSIONS, "rolling_train_sessions": TRAIN_SESSIONS,
                       "static_fit_cutoff": str(static_cutoff.date()),
                       "calibration": "20 validation reviews/year after 10-session cooldown"},
        "event": {"horizon_sessions": HORIZON, "train_quantile": 0.10,
                  "episode_merge_sessions": HORIZON, "purge_sessions": LOOKBACK + HORIZON},
        "static_initial_fit": static_training,
        "primary_comparison": "episode recall at the closest validation-achievable load to 20 reviews/year after cooldown; report realized validation/test loads",
        "aggregates": grouped.replace({np.nan: None}).to_dict(orient="records"),
        "paired_block_bootstrap_recall_deltas": {
            "adaptativo_menos_congelado": _block_bootstrap_delta(
                predictions, "ae_adaptativo_anual", "ae_congelado"),
            "adaptativo_menos_ewma": _block_bootstrap_delta(
                predictions, "ae_adaptativo_anual", "ewma_094"),
        },
        "latent_state_profiles": pd.DataFrame(latent_records).groupby(
            ["year", "state"], as_index=False
        ).agg(
            n=("state", "size"), mean_trailing_return=("trailing_32d_return", "mean"),
            mean_annualized_vol=("trailing_32d_annualized_vol", "mean"),
            mean_drawdown=("trailing_32d_drawdown", "mean"),
            mean_reconstruction_error=("reconstruction_mse", "mean"),
        ).to_dict(orient="records"),
        "limitations": [
            "The latent representation is descriptive and does not identify causal market drivers.",
            "The annual bootstrap uses a three-year circular block and does not remove uncertainty from research choices.",
            "Latent axes and cluster IDs are refit-specific and must not be compared literally across years.",
            "The autoencoder is an unsupervised anomaly detector, not a calibrated loss distribution or trading policy.",
        ],
    }
    observation_noise_sd = float(np.sqrt(static_training["best_valid_mse"]))
    generated = sample_returns(static_model, center, scale, observation_noise_sd)
    static_train_returns = returns[return_dates < static_cutoff]
    real_lag1 = np.corrcoef(static_train_returns[1:], static_train_returns[:-1])[0, 1]
    synthetic_lag1 = np.mean([np.corrcoef(row[1:], row[:-1])[0, 1] for row in generated])
    summary["frozen_vae_generation_diagnostic"] = {
        "n_generated_windows": int(len(generated)),
        "decoder_observation_noise_sd_standardized": observation_noise_sd,
        "real_daily_std_train": float(np.std(static_train_returns)),
        "generated_daily_std": float(np.std(generated)),
        "real_daily_q01_train": float(np.quantile(static_train_returns, 0.01)),
        "generated_daily_q01": float(np.quantile(generated, 0.01)),
        "real_daily_q99_train": float(np.quantile(static_train_returns, 0.99)),
        "generated_daily_q99": float(np.quantile(generated, 0.99)),
        "real_within_window_lag1_corr": float(real_lag1),
        "generated_within_window_lag1_corr": float(synthetic_lag1),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.data, args.out), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
