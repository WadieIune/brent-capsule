#!/usr/bin/env python3
"""Exploratory multiactive long-portfolio alert/exposure gate.

The basket is an equal-weight risk-unit proxy, not the user's booked portfolio.
Price differences retain negative WTI settlements without manufacturing log
returns. All scales, risk contributions, survival models and classifiers are
refit from data available before each validation/test fold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "code" / "applications"
sys.path.insert(0, str(APP))
import common  # noqa: E402

ASSETS = ("BRENT", "WTI", "GOLD", "SILVER", "COPPER", "NATGAS")
HORIZON = 10
MIN_TRAIN_SESSIONS = 5 * 252
MIN_VALID_SESSIONS = 200
MIN_TEST_SESSIONS = 100
REVIEW_BUDGET_YEAR = 20
COOLDOWN = 10
EXPOSURE_REDUCED = 0.50
COST_BPS = (2, 5, 10)
SEED = 42
NONPOSITIVE_FEATURE_OFFSET = 100.0


def load_panel(path: Path) -> Tuple[pd.DataFrame, Dict[str, object]]:
    frame = pd.read_csv(path, parse_dates=["date"])
    missing = sorted(set(ASSETS) - set(frame.columns))
    if missing:
        raise ValueError(f"panel lacks required assets: {missing}")
    frame = frame[["date", *ASSETS]].dropna().sort_values("date").drop_duplicates("date")
    prices = frame.set_index("date")
    prices = prices.loc[prices.index.dayofweek < 5]
    changed = prices.diff().abs().sum(axis=1) > 1e-12
    if len(changed):
        changed.iloc[0] = True
    prices = prices.loc[changed]
    diag = {
        "source": path.name,
        "date_start": str(prices.index.min().date()),
        "date_end": str(prices.index.max().date()),
        "joint_weekday_sessions": int(len(prices)),
        "nonpositive_prices": {
            asset: [{"date": str(date.date()), "price": float(value)}
                    for date, value in prices[asset].items() if value <= 0]
            for asset in ASSETS
        },
    }
    return prices, diag


def risk_contributions(returns: np.ndarray, weights: np.ndarray) -> np.ndarray:
    cov = np.cov(returns, rowvar=False)
    variance = float(weights @ cov @ weights)
    if not np.isfinite(variance) or variance <= 0:
        return weights / weights.sum()
    contribution = weights * (cov @ weights) / variance
    contribution = np.maximum(contribution, 1e-10)
    return contribution / contribution.sum()


def survival_feature_eligible(asset: str) -> bool:
    # Keep the feature universe fixed across folds when a source series crosses zero.
    return asset != "WTI"


def channel_features(prices: pd.DataFrame) -> Tuple[Dict[str, np.ndarray], Dict[str, Dict[str, object]]]:
    regime: Dict[str, np.ndarray] = {}
    cached: Dict[str, Dict[str, object]] = {}
    for asset in ASSETS:
        values = prices[asset].to_numpy(dtype=float)
        feature_prices = values.copy()
        offset = NONPOSITIVE_FEATURE_OFFSET if np.any(values <= 0) else 0.0
        feature_prices += offset
        if np.any(feature_prices <= 0):
            raise ValueError(f"fixed geometry-only price offset is insufficient for {asset}")
        idxs, _flags, feature_frame = common.window_features(feature_prices)
        band = np.full(len(prices) - 1, np.nan)
        for row, end in enumerate(idxs):
            if 0 <= end - 1 < len(band):
                width = float(feature_frame.iloc[row].get("band_width", np.nan))
                lo = max(0, int(end) - common.LOOKBACK + 1)
                level = float(np.mean(feature_prices[lo:end + 1]))
                band[end - 1] = width * level / (2.0 * common.BAND_MULT)
        regime[asset] = pd.Series(band).ffill().to_numpy()
        cached[asset] = {"features": feature_frame, "price_indices": idxs,
                         "feature_prices": feature_prices, "feature_offset": offset}
    return regime, cached


def _fit_survival_scores(prices: pd.DataFrame, cached: Dict[str, object],
                         fit_cutoff: pd.Timestamp) -> Tuple[Dict[str, np.ndarray], Dict[str, str]]:
    scores, methods = {}, {}
    for asset in ASSETS:
        if not survival_feature_eligible(asset):
            scores[asset] = np.full(len(prices) - 1, 0.5)
            methods[asset] = "excluded: nonpositive settlement makes ratio-survival features undefined"
            continue
        feature_prices = cached[asset]["feature_prices"]
        dates = pd.DatetimeIndex(prices.index)
        cutoff_idx = int(dates.searchsorted(fit_cutoff, side="right"))
        train_episodes = common.cs.extract_episodes(
            feature_prices[:cutoff_idx], dates[:cutoff_idx],
        )
        model = common.SurvivalFeaturizer().fit(train_episodes, str(fit_cutoff.date()))
        score = np.full(len(prices) - 1, np.nan)
        feats = cached[asset]["features"]
        if model.method != "none" and not feats.empty:
            survival = model.predict_pk(feats, HORIZON)
            price_indices = cached[asset]["price_indices"]
            values = np.full(len(prices), np.nan)
            valid = np.isfinite(survival)
            values[price_indices[valid]] = 1.0 - survival[valid]
            values = pd.Series(values).ffill().to_numpy()
            score[:] = values[1:]
        scores[asset] = score
        methods[asset] = model.method
    return scores, methods


def _forward_sum(values: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for t in range(len(values) - horizon):
        out[t] = float(np.sum(values[t + 1:t + horizon + 1]))
    return out


def fhs_ewma_downside_score(pnl: np.ndarray, window: int = 252,
                            lam: float = 0.94, horizon: int = HORIZON) -> np.ndarray:
    """Causal FHS forecast from trailing overlapping blocks of filtered residuals."""
    values = np.asarray(pnl, dtype=float)
    variance = pd.Series(np.square(values)).ewm(alpha=1.0 - lam, adjust=False,
                                                min_periods=20).mean().to_numpy()
    sigma = np.sqrt(variance)
    residual = values / np.maximum(sigma, 1e-10)
    score = np.full(len(values), np.nan)
    warmup = int(np.flatnonzero(np.isfinite(sigma))[0]) if np.isfinite(sigma).any() else len(values)
    for t in range(warmup + window - 1, len(values)):
        sample = residual[t - window + 1:t + 1]
        blocks = np.lib.stride_tricks.sliding_window_view(sample, horizon)
        lower_tail = float(np.quantile(blocks.sum(axis=1), 0.10))
        score[t] = max(0.0, -lower_tail * sigma[t])
    return score


def _alerts(score: np.ndarray, threshold: float) -> np.ndarray:
    out = np.zeros(len(score), dtype=bool)
    last = -10**9
    for t, value in enumerate(score):
        if np.isfinite(value) and value >= threshold and t - last >= COOLDOWN:
            out[t] = True
            last = t
    return out


def _calibrate(score: np.ndarray, target_per_year: float = REVIEW_BUDGET_YEAR) -> Tuple[float, float]:
    valid = score[np.isfinite(score)]
    if not len(valid):
        return float("inf"), 0.0
    best_threshold, best_gap, best_rate = float("inf"), float("inf"), 0.0
    for q in np.linspace(0.50, 0.999, 120):
        threshold = float(np.quantile(valid, q))
        rate = float(_alerts(score, threshold).sum() * 252.0 / len(score))
        gap = abs(rate - target_per_year)
        if gap < best_gap:
            best_threshold, best_gap, best_rate = threshold, gap, rate
    return best_threshold, best_rate


def _event_metrics(alerts: np.ndarray, event_starts: np.ndarray, start: int,
                   n: int) -> Dict[str, object]:
    local = alerts[start:start + n]
    covered = np.zeros(n, dtype=bool)
    hits = []
    effective_starts = []
    for event in event_starts:
        s = int(event) - start
        if not 0 <= s < n:
            continue
        lo = max(0, s - HORIZON)
        covered[lo:s] = True
        hits.append(bool(local[lo:s].any()))
        effective_starts.append(int(event))
    years = max(n / 252.0, 1e-9)
    return {
        "episodes": len(hits),
        "episode_recall": float(np.mean(hits)) if hits else None,
        "false_alerts_per_year": float((local & ~covered).sum()) / years,
        "reviews_per_year": float(local.sum()) / years,
    }


def _portfolio_policy(pnl: np.ndarray, alerts: np.ndarray, cost_bps: int) -> Dict[str, object]:
    exposure = np.ones(len(pnl), dtype=float)
    for t in np.flatnonzero(alerts):
        lo = t + 1
        hi = min(len(exposure), t + HORIZON + 1)
        exposure[lo:hi] = EXPOSURE_REDUCED
    turnover = np.abs(np.diff(np.r_[1.0, exposure]))
    turnover[-1] += abs(exposure[-1] - 1.0)
    net = pnl * exposure - turnover * (cost_bps / 10000.0)
    forward = _forward_sum(net)
    valid = np.isfinite(forward)
    if not valid.any():
        return {"error": "insufficient forward observations"}
    q10 = float(np.quantile(forward[valid], 0.10))
    tail = forward[valid][forward[valid] <= q10]
    downside = np.minimum(net, 0.0)
    return {
        "cost_bps_per_turnover": cost_bps,
        "mean_exposure": float(exposure.mean()),
        "turnover_units": float(turnover.sum()),
        "net_proxy_sharpe": float(np.mean(net) / max(np.std(net, ddof=1), 1e-12) * np.sqrt(252)),
        "net_cumulative_pnl_risk_units": float(net.sum()),
        "net_max_drawdown_risk_units": float(np.max(np.maximum.accumulate(np.r_[0.0, np.cumsum(net)]) -
                                                       np.r_[0.0, np.cumsum(net)])),
        "oos_fwd10_q10_risk_units": q10,
        "oos_fwd10_es10_risk_units": float(tail.mean()),
        "daily_downside_deviation_risk_units": float(np.sqrt(np.mean(downside ** 2))),
    }


def _bootstrap_recall_delta(frame: pd.DataFrame, candidate: str, baseline: str,
                           block_years: int = 2, draws: int = 5000) -> Dict[str, object]:
    paired = frame.pivot(index="year", columns="model", values="episode_recall")
    paired = paired[[candidate, baseline]].dropna()
    delta = (paired[candidate] - paired[baseline]).to_numpy(dtype=float)
    if len(delta) < block_years:
        return {"n_years": int(len(delta)), "delta": None, "ci95": [None, None]}
    rng = np.random.default_rng(SEED)
    nblocks = int(np.ceil(len(delta) / block_years))
    samples = []
    for _ in range(draws):
        starts = rng.integers(0, len(delta), size=nblocks)
        indices = np.concatenate([
            (start + np.arange(block_years)) % len(delta) for start in starts
        ])[:len(delta)]
        samples.append(float(np.mean(delta[indices])))
    return {"n_years": int(len(delta)), "block_years": block_years,
            "delta_mean": float(np.mean(delta)),
            "ci95": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))]}


def run_experiment(panel_path: Path, out_dir: Path) -> Dict[str, object]:
    prices, data_diag = load_panel(panel_path)
    dates = pd.DatetimeIndex(prices.index)
    changes = prices.diff().iloc[1:].to_numpy(dtype=float)
    return_dates = dates[1:]
    regime_raw, cached = channel_features(prices)
    n = len(changes)
    forward_cache: Dict[int, np.ndarray] = {}
    results: List[Dict[str, object]] = []
    folds: List[Dict[str, object]] = []
    weights = np.full(len(ASSETS), 1.0 / len(ASSETS))

    for year in range(int(return_dates.min().year) + 7, int(return_dates.max().year) + 1):
        test_mask = return_dates.year == year
        val_mask = return_dates.year == year - 1
        if test_mask.sum() < MIN_TEST_SESSIONS or val_mask.sum() < MIN_VALID_SESSIONS:
            continue
        test_idx = np.flatnonzero(test_mask)
        val_idx = np.flatnonzero(val_mask)
        val_start = return_dates[val_idx[0]]
        train_idx = np.flatnonzero((return_dates < val_start) & (return_dates >= val_start - pd.DateOffset(years=8)))
        label_idx = train_idx[(train_idx + HORIZON < n) &
                              (return_dates[np.minimum(train_idx + HORIZON, n - 1)] < val_start)]
        if len(label_idx) < MIN_TRAIN_SESSIONS:
            continue

        # Per-asset price-change scales and risk contributions use train only.
        scale = np.std(changes[train_idx], axis=0, ddof=1)
        scale = np.where(np.isfinite(scale) & (scale > 1e-10), scale, 1.0)
        normalized = changes / scale[None, :]
        portfolio = normalized @ weights
        rc = risk_contributions(normalized[label_idx], weights)

        bands = np.column_stack([regime_raw[a] for a in ASSETS])
        band_mu = np.nanmean(bands[label_idx], axis=0)
        band_sd = np.nanstd(bands[label_idx], axis=0)
        band_sd = np.where(np.isfinite(band_sd) & (band_sd > 1e-8), band_sd, 1.0)
        regime = np.nansum(((bands - band_mu) / band_sd) * rc[None, :], axis=1)
        survival_by_asset, survival_methods = _fit_survival_scores(
            prices, cached, val_start - pd.DateOffset(days=1),
        )
        frag = np.column_stack([survival_by_asset[a] for a in ASSETS])
        frag = np.where(np.isfinite(frag), frag, 0.5)
        survival_weights = rc.copy()
        if survival_methods["WTI"].startswith("excluded:"):
            survival_weights[ASSETS.index("WTI")] = 0.0
        survival_weights = (survival_weights / survival_weights.sum()
                            if survival_weights.sum() > 0 else np.where(
                                np.arange(len(ASSETS)) == ASSETS.index("WTI"), 0.0, 1.0) /
                                (len(ASSETS) - 1))
        survival = frag @ survival_weights

        ewma_var = pd.Series(np.square(portfolio)).ewm(alpha=0.06, adjust=False, min_periods=20).mean().to_numpy()
        ewma = np.sqrt(ewma_var)
        fhs_score = fhs_ewma_downside_score(portfolio, window=252, horizon=HORIZON)
        fwd = forward_cache.setdefault(year, _forward_sum(portfolio))
        tail_cut = float(np.quantile(fwd[label_idx], 0.10))
        y = (fwd[label_idx] < tail_cut).astype(int)

        feature_sets = {
            "vol_regimen": np.column_stack([ewma, regime]),
            "vol_supervivencia": np.column_stack([ewma, survival]),
            "vol_regimen_supervivencia": np.column_stack([ewma, regime, survival]),
        }
        scores = {"solo_vol": ewma, "fhs_ewma": fhs_score}
        model_details = {}
        valid_labeled = label_idx[np.isfinite(fwd[label_idx])]
        y_labeled = y[np.isfinite(fwd[label_idx])]
        for name, features in feature_sets.items():
            good = np.isfinite(features[label_idx]).all(axis=1)
            x_train = features[label_idx][good]
            y_train = y[good]
            if len(np.unique(y_train)) < 2:
                model_details[name] = "insufficient train classes"
                continue
            scaler = StandardScaler().fit(x_train)
            model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED)
            model.fit(scaler.transform(x_train), y_train)
            test_features = features[val_idx]
            all_features = features
            valid_features = test_features
            valid_good = np.isfinite(valid_features).all(axis=1)
            test_features = all_features[test_idx]
            test_good = np.isfinite(test_features).all(axis=1)
            score = np.full(n, np.nan)
            score[val_idx[valid_good]] = model.predict_proba(scaler.transform(valid_features[valid_good]))[:, 1]
            score[test_idx[test_good]] = model.predict_proba(scaler.transform(test_features[test_good]))[:, 1]
            scores[name] = score
            model_details[name] = {"n_train": int(len(y_train)), "positive_rate_train": float(y_train.mean()),
                                   "coefficients": model.coef_[0].tolist()}

        val_end = int(val_idx[-1]) + 1
        test_start, test_end = int(test_idx[0]), int(test_idx[-1]) + 1
        fwd_test_event = np.isfinite(fwd) & (fwd < tail_cut)
        starts_all = np.flatnonzero(fwd_test_event)
        starts_all = starts_all[np.r_[True, np.diff(starts_all) >= HORIZON]]
        event_starts = starts_all[(starts_all >= test_start) & (starts_all < test_end)]
        fold = {"year": year, "date_start": str(return_dates[test_start].date()),
                "date_end": str(return_dates[test_end - 1].date()), "n_train_labels": int(len(label_idx)),
                "n_validation": int(len(val_idx)), "n_test": int(len(test_idx)),
                "tail_threshold_train": tail_cut, "weights_risk_units": weights.tolist(),
                "risk_scales_delta_price_train": scale.tolist(),
                "risk_contributions_train": dict(zip(ASSETS, rc.tolist())),
                "survival_feature_weights_train": dict(zip(ASSETS, survival_weights.tolist())),
                "channel_feature_offsets": {asset: cached[asset]["feature_offset"] for asset in ASSETS},
                "survival_methods": survival_methods, "model_details": model_details,
                "signals": {}}
        for name, score in scores.items():
            if not np.isfinite(score[val_idx]).any():
                continue
            threshold, val_rate = _calibrate(score[val_idx])
            val_alert = _alerts(score[val_idx], threshold)
            test_alert = _alerts(score[test_start:test_end], threshold)
            test_global_alert = np.zeros(n, dtype=bool)
            test_global_alert[test_start:test_end] = test_alert
            metrics = _event_metrics(test_global_alert, event_starts, test_start, len(test_idx))
            metrics.update({"year": year, "model": name, "threshold": threshold,
                            "validation_reviews_per_year_realized": val_rate,
                            "target_validation_reviews_per_year": REVIEW_BUDGET_YEAR})
            policies = {str(cost): _portfolio_policy(portfolio[test_start:test_end], test_alert, cost)
                        for cost in COST_BPS}
            metrics["exposure_policy"] = policies
            results.append(metrics)
            fold["signals"][name] = {
                "validation_review_rate": val_rate,
                "test_review_rate": metrics["reviews_per_year"],
                "test_false_alarms_per_year": metrics["false_alerts_per_year"],
                "test_episode_recall": metrics["episode_recall"],
            }
        folds.append(fold)

    if not results:
        raise RuntimeError("No complete annual walk-forward folds were produced")
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).drop(columns=["exposure_policy"]).to_csv(out_dir / "annual_metrics.csv", index=False)
    (out_dir / "fold_diagnostics.json").write_text(json.dumps(folds, indent=2), encoding="utf-8")
    flat_policies = [{"year": row["year"], "model": row["model"], "cost_bps": cost,
                      **policy} for row in results for cost, policy in row["exposure_policy"].items()]
    pd.DataFrame(flat_policies).to_csv(out_dir / "exposure_policy_sensitivity.csv", index=False)
    frame_results = pd.DataFrame(results)
    complete_years = frame_results.loc[frame_results["year"] < return_dates.max().year]
    aggregate_rows = []
    for model, rows in complete_years.groupby("model"):
        valid = rows.dropna(subset=["episode_recall"])
        total_events = int(valid["episodes"].sum())
        captured = int(np.rint((valid["episodes"] * valid["episode_recall"]).sum()))
        aggregate_rows.append({
            "model": model,
            "pooled_episode_recall": captured / total_events if total_events else None,
            "captured_episodes": captured,
            "test_episodes": total_events,
            "mean_annual_episode_recall": float(valid["episode_recall"].mean()) if len(valid) else None,
            "mean_false_alarms_per_year": float(rows["false_alerts_per_year"].mean()),
            "mean_reviews_per_year": float(rows["reviews_per_year"].mean()),
            "mean_validation_reviews_per_year": float(rows["validation_reviews_per_year_realized"].mean()),
        })
    aggregates = pd.DataFrame(aggregate_rows)
    policy_frame = pd.DataFrame(flat_policies)
    policy_complete = policy_frame.loc[policy_frame["year"] < return_dates.max().year]
    policy_columns = ["mean_exposure", "net_proxy_sharpe", "net_cumulative_pnl_risk_units",
                      "net_max_drawdown_risk_units", "oos_fwd10_q10_risk_units",
                      "oos_fwd10_es10_risk_units", "turnover_units"]
    policy_aggregates = policy_complete.groupby(["model", "cost_bps"], as_index=False)[policy_columns].mean()
    summary = {
        "experiment": "wprd1_multiactive_policy",
        "decision": "exploratory_proxy_not_book_backtest",
        "source": data_diag,
        "source_sha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        "assets": list(ASSETS),
        "portfolio_definition": "equal-weight of per-asset price changes scaled by train-only price-change SD; one risk unit per leg",
        "wtinegative_handling": "retain negative settlement and observed delta-price P&L; no log returns; train-only scales; use translation-invariant absolute channel width; exclude WTI from ratio-based survival only after the nonpositive print becomes observable and renormalize weights",
        "forecast_horizon_sessions": HORIZON,
        "event": "forward 10-session portfolio risk-unit loss below train q10; episodes merged within 10 sessions",
        "signals": ["solo_vol", "fhs_ewma", "vol_regimen", "vol_supervivencia", "vol_regimen_supervivencia"],
        "fhs_baseline": "252-session rolling empirical 10-session overlapping-block lower quantile of EWMA-filtered portfolio residuals, scaled by current EWMA sigma; causal portfolio FHS approximation",
        "operating_point": {"validation_target_reviews_per_year": REVIEW_BUDGET_YEAR,
                            "cooldown_sessions": COOLDOWN, "exposure_after_alert": EXPOSURE_REDUCED,
                            "reduced_exposure_sessions": HORIZON, "turn_cost_sensitivity_bps": list(COST_BPS)},
        "walk_forward": "expanding historical fit, previous calendar year for alert-load calibration, next year test; labels purged by forward horizon",
        "aggregates": aggregates.replace({np.nan: None}).to_dict(orient="records"),
        "paired_two_year_block_bootstrap_recall_delta_vs_fhs": {
            name: _bootstrap_recall_delta(complete_years, name, "fhs_ewma")
            for name in ("vol_supervivencia", "vol_regimen_supervivencia")
        },
        "exposure_policy_complete_year_aggregates": policy_aggregates.replace({np.nan: None}).to_dict(orient="records"),
        "limitations": [
            "Price-change risk units are an analytical proxy; they are not investable P&L or currency capital.",
            "Equal 1/N risk-unit weights do not describe the user's actual holdings, futures multipliers or margin.",
            "The logistic risk-score is a candidate prioritization model; no independent supervisory challenge has yet passed.",
            "Gross-exposure and basis-point cost outputs are simulated sensitivities, not realized performance.",
            "2026 is a partial-year case study; do not compare its annualized rates as if it were a full fold.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "reports" / "wprd1_multiactive_policy")
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.panel, args.out), indent=2))


if __name__ == "__main__":
    main()
