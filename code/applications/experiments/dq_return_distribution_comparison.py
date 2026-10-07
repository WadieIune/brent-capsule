#!/usr/bin/env python3
"""Compare empirical standardized returns with a fitted Gaussian reference.

This is a distributional diagnostic, not a capital estimate or a DQ detector
benchmark. Synthetic-label detector metrics remain a separate evaluation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import kurtosis, norm, skew

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ("BRENT", "WTI", "GOLD", "SILVER", "COPPER", "SP500",
          "DAX", "EUROSTOXX50", "EURUSD")
THEORETICAL_GAUSSIAN_3SIGMA = float(2 * norm.sf(3))


def load_standardized_returns(panel_path: Path):
    frame = pd.read_csv(panel_path, parse_dates=["date"])
    results, stats = {}, {}
    for asset in ASSETS:
        prices = pd.to_numeric(frame[asset], errors="coerce")
        log_prices = np.log(prices.where(prices > 0))
        returns = log_prices.diff().dropna()
        returns.index = pd.DatetimeIndex(frame.loc[returns.index, "date"])
        values = returns.to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if len(values) < 100:
            continue
        mu, sigma = float(np.mean(values)), float(np.std(values, ddof=1))
        z = (values - mu) / sigma
        empirical_tail = float(np.mean(np.abs(z) > 3))
        results[asset] = z
        stats[asset] = {
            "n": int(len(values)),
            "start_date": str(returns.index.min().date()),
            "end_date": str(returns.index.max().date()),
            "mean_log_return": mu,
            "std_log_return": sigma,
            "skewness": float(skew(values, bias=False)),
            "excess_kurtosis": float(kurtosis(values, fisher=True, bias=False)),
            "empirical_abs_z_gt_3": empirical_tail,
            "gaussian_abs_z_gt_3": THEORETICAL_GAUSSIAN_3SIGMA,
            "empirical_to_gaussian_3sigma_tail_ratio": (
                empirical_tail / THEORETICAL_GAUSSIAN_3SIGMA
                if THEORETICAL_GAUSSIAN_3SIGMA else None
            ),
        }
    return results, stats


def plot_distributions(standardized: dict[str, np.ndarray], output: Path):
    sns.set_theme(style="whitegrid", context="notebook")
    names = list(standardized)
    rows = int(np.ceil(len(names) / 3))
    fig, axes = plt.subplots(rows, 3, figsize=(15, 4.2 * rows), squeeze=False)
    grid = np.linspace(-6, 6, 700)
    palette = sns.color_palette("colorblind", n_colors=len(names))
    for i, (asset, z) in enumerate(standardized.items()):
        ax = axes.flat[i]
        sns.histplot(z, bins=100, stat="density", kde=True, color=palette[i],
                     alpha=0.32, edgecolor=None, ax=ax)
        ax.plot(grid, norm.pdf(grid), color="#222222", linewidth=1.8,
                label="Normal ajustada (N(0,1))")
        ax.axvline(-3, color="#c23b22", linestyle="--", linewidth=1.1)
        ax.axvline(3, color="#c23b22", linestyle="--", linewidth=1.1,
                   label="Umbral ±3σ")
        ax.set_xlim(-6, 6)
        ax.set_title(asset)
        ax.set_xlabel("Rendimiento logarítmico estandarizado (z)")
        ax.set_ylabel("Densidad")
        ax.legend(frameon=False, fontsize=8)
    for ax in axes.flat[len(names):]:
        ax.remove()
    fig.suptitle("Rendimientos empíricos frente a referencia normal y umbrales ±3σ",
                 fontsize=15, y=1.01)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def run(panel_path: Path, out: Path):
    standardized, stats = load_standardized_returns(panel_path)
    plot_distributions(standardized, out / "empirical_vs_gaussian_returns.png")
    payload = {
        "panel": str(panel_path),
        "series": list(stats),
        "method": "daily log returns; per-series sample mean/std standardization; full-history descriptive fit",
        "reference": "standard normal with theoretical two-sided P(|Z|>3)=0.0026998",
        "interpretation": "descriptive only; historical fit is not a causal alert threshold or capital estimate",
        "metrics": stats,
    }
    (out / "distribution_metrics.json").write_text(json.dumps(payload, indent=2),
                                                    encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data/panel_extendido_2026-09-09.csv")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "results/reports/dq_return_distributions")
    args = parser.parse_args()
    print(json.dumps(run(args.panel, args.out), indent=2))


if __name__ == "__main__":
    main()
