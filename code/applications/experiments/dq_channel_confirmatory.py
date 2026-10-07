#!/usr/bin/env python3
"""Confirmatory DQ study across price, return and channel representations.

Thresholds are calibrated on clean validation only. Test windows do not overlap.
The episode pipeline and one clean-trained XGB-AFT model are rerun/frozen to
measure how injected price defects distort channel survival. Portfolio impact is
reported as an equal-weight VaR proxy, not regulatory capital or euros.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta, norm

ROOT = Path(__file__).resolve().parents[3]
WINDOW = 20
STRIDE = 20
FIT_END = pd.Timestamp("2018-12-31")
VAL_END = pd.Timestamp("2020-08-20")
DQ_FP = 0.05
SURVIVAL_CUTOFF = pd.Timestamp("2018-12-31")
ALPHA = 0.99
VAR_WINDOW = 250
STRESS_EVERY = 4
SEEDS = (42, 71, 123)
RISK_ASSETS = ("BRENT", "COPPER", "EUROSTOXX50", "GOLD", "SP500")
TRAIN_FAMILIES = ("stale", "reversible_jump", "decoupling")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EXP = ROOT / "code/applications/experiments"
cnn_base = load_module("dq_cnn1d_supervised", EXP / "dq_cnn1d_supervised.py")
channel = load_module("dq_channel_representation", EXP / "dq_channel_representation.py")
price = load_module("dq_quantize_price_grid", EXP / "dq_quantize_price_grid.py")
sys.path.insert(0, str(ROOT / "code/part2_channel_survival"))
import channel_survival as survival  # noqa: E402


def calibration_threshold(scores: np.ndarray, fpr: float = DQ_FP) -> float:
    scores = np.asarray(scores, dtype=float)
    scores = scores[np.isfinite(scores)]
    if not len(scores):
        raise ValueError("No hay scores limpios para calibrar")
    allowed = int(np.floor(fpr * len(scores)))
    return float(np.sort(scores)[max(0, len(scores) - allowed - 1)])


def exact_binomial_interval(events: int, total: int, confidence: float = 0.95):
    """Two-sided Clopper-Pearson interval for an observed alert rate."""
    if total <= 0 or events < 0 or events > total:
        raise ValueError("Se requiere 0 <= eventos <= total y total > 0")
    tail = (1.0 - confidence) / 2.0
    lower = 0.0 if events == 0 else float(beta.ppf(tail, events, total - events + 1))
    upper = 1.0 if events == total else float(beta.ppf(1.0 - tail, events + 1, total - events))
    return [lower, upper]


def make_windows(panel_path: Path):
    prices, dates = price.read_prices(panel_path)
    scaled = price.normalize(prices)
    ret_dates = dates[1:]
    bounds = price.window_bounds(scaled, WINDOW, STRIDE)
    starts = pd.DatetimeIndex([ret_dates[a] for a, _ in bounds])
    ends = pd.DatetimeIndex([ret_dates[b - 1] for _, b in bounds])
    train = ends <= FIT_END
    val = (starts > FIT_END) & (ends <= VAL_END)
    test = starts > VAL_END
    p_windows = np.asarray([prices[a:b + 1] for a, b in bounds], dtype=float)
    z_windows = np.asarray([scaled[a:b] for a, b in bounds], dtype=np.float32)
    return {
        "prices": prices, "dates": dates, "scaled": scaled, "bounds": bounds,
        "starts": starts, "ends": ends, "p": p_windows, "z": z_windows,
        "train_mask": train, "val_mask": val, "test_mask": test,
        "train_p": p_windows[train], "val_p": p_windows[val], "test_p": p_windows[test],
        "train_z": z_windows[train], "val_z": z_windows[val], "test_z": z_windows[test],
        "test_bounds": [b for b, keep in zip(bounds, test) if keep],
    }


def channel_scores(p_windows: np.ndarray) -> dict[str, np.ndarray]:
    return {name: np.asarray(scorer(p_windows), dtype=float)
            for name, scorer in channel.CHANNEL_CONTROLS.items()}


def base_scores(z_windows: np.ndarray, models: list) -> dict[str, np.ndarray]:
    cnn = np.mean([cnn_base.score_cnn(m, z_windows) for m in models], axis=0)
    return {
        "cnn1d": cnn,
        "cross_asset_1_minus_r2": cnn_base.score_cross_asset(z_windows),
        "3sigma_vol_normalizada": cnn_base.score_3sigma(z_windows),
    }


def all_scores(p_windows: np.ndarray, z_windows: np.ndarray, models: list):
    out = channel_scores(p_windows)
    out["reticula_precio"] = price.grid_step_score(p_windows)
    out.update(base_scores(z_windows, models))
    return out


def inject_window(window: np.ndarray, family: str, seed: int):
    return channel.PRICE_FAMILIES[family](
        window.copy(), 0, len(window), np.random.default_rng(seed))


def recompute_window_scores(prices: np.ndarray, bounds: list[tuple[int, int]],
                            families: tuple[str, ...], models: list):
    output = {f: {} for f in families}
    for fi, family in enumerate(families):
        for wi, (a, b) in enumerate(bounds):
            corrupted = inject_window(prices[a:b + 1], family, 10_000 + fi * 1000 + wi)
            full = prices.copy()
            full[a:b + 1] = corrupted
            p_window = full[a:b + 1][None, :, :]
            z_window = price.normalize(full)[a:b][None, :, :].astype(np.float32)
            scores = all_scores(p_window, z_window, models)
            for name, values in scores.items():
                output[family].setdefault(name, []).append(float(values[0]))
    return {f: {name: np.asarray(values) for name, values in by_detector.items()}
            for f, by_detector in output.items()}


def fit_xgb_combiner(train_prices: np.ndarray, train_bounds: list[tuple[int, int]],
                     train_z: np.ndarray, cnn_models: list, seed: int = 42):
    from xgboost import XGBClassifier

    clean_scores = all_scores(
        np.asarray([train_prices[a:b + 1] for a, b in train_bounds]), train_z, cnn_models)
    feature_names = list(clean_scores)
    features = [np.column_stack([clean_scores[n] for n in feature_names])]
    labels = [np.zeros(len(train_z), dtype=int)]
    for fi, family in enumerate(TRAIN_FAMILIES):
        corrupted_p, corrupted_z = [], []
        for wi, (a, b) in enumerate(train_bounds):
            full = train_prices.copy()
            full[a:b + 1] = inject_window(full[a:b + 1], family, 800_000 + seed + fi * 1000 + wi)
            corrupted_p.append(full[a:b + 1])
            corrupted_z.append(price.normalize(full)[a:b])
        sc = all_scores(np.asarray(corrupted_p), np.asarray(corrupted_z, dtype=np.float32), cnn_models)
        features.append(np.column_stack([sc[n] for n in feature_names]))
        labels.append(np.ones(len(corrupted_z), dtype=int))
    xgb_model = XGBClassifier(
        n_estimators=250, max_depth=3, learning_rate=0.04,
        subsample=0.85, colsample_bytree=0.85, reg_lambda=2.0,
        objective="binary:logistic", eval_metric="aucpr", random_state=seed,
        tree_method="hist", device="cpu",
    )
    xgb_model.fit(np.vstack(features), np.concatenate(labels))
    return xgb_model, feature_names


def fit_clean_aft(clean_episodes: pd.DataFrame):
    import xgboost as xgb

    train = survival.administrative_censoring(clean_episodes, SURVIVAL_CUTOFF)
    train = train.loc[train.start_date <= SURVIVAL_CUTOFF].copy()
    train = train.replace([np.inf, -np.inf], np.nan).dropna(subset=survival.FEATURES)
    x = train[survival.FEATURES].to_numpy(dtype=float)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    xs = (x - mean) / scale
    duration = train.duration.to_numpy(dtype=float).clip(min=0.5)
    event = train.event.to_numpy(dtype=int)
    dtrain = xgb.DMatrix(xs)
    dtrain.set_float_info("label_lower_bound", duration)
    dtrain.set_float_info("label_upper_bound", np.where(event == 1, duration, np.inf))
    model = xgb.train(survival._xgb_aft_params(False), dtrain, num_boost_round=200)
    return model, mean, scale, int(len(train)), int(event.sum())


def predict_survival_10(model, mean, scale, episodes: pd.DataFrame):
    import xgboost as xgb
    if episodes.empty:
        return episodes.assign(p_survive_10=pd.Series(dtype=float))
    valid = episodes.replace([np.inf, -np.inf], np.nan).dropna(subset=survival.FEATURES).copy()
    xs = (valid[survival.FEATURES].to_numpy(dtype=float) - mean) / scale
    median_life = np.clip(model.predict(xgb.DMatrix(xs)), 1e-3, None)
    valid["p_survive_10"] = 1.0 - norm.cdf((np.log(10.0) - np.log(median_life)) / survival.XGB_SCALE)
    return valid


def apply_stress_to_brent(brent: pd.Series, win_rows: list[tuple[pd.Timestamp, pd.Timestamp]],
                          family: str):
    result = brent.copy()
    rng = np.random.default_rng(20261007 + list(channel.PRICE_FAMILIES).index(family))
    applied = 0
    for wi, (start, end) in enumerate(win_rows):
        if wi % STRESS_EVERY != 0:
            continue
        mask = (result.index >= start) & (result.index <= end)
        idx = np.flatnonzero(mask)
        if len(idx) < 5:
            continue
        segment = result.iloc[idx].to_numpy(dtype=float)[:, None]
        changed = channel.PRICE_FAMILIES[family](segment, 0, len(segment), rng)[:, 0]
        result.iloc[idx] = changed
        applied += 1
    return result, applied


def episode_comparison(clean_episodes: pd.DataFrame, altered_episodes: pd.DataFrame,
                       model, mean, scale):
    clean_test = clean_episodes.loc[clean_episodes.start_date > VAL_END]
    altered_test = altered_episodes.loc[altered_episodes.start_date > VAL_END]
    clean_pred = predict_survival_10(model, mean, scale, clean_test)
    altered_pred = predict_survival_10(model, mean, scale, altered_test)
    clean_by = clean_pred.drop_duplicates("start_date").set_index("start_date")
    altered_by = altered_pred.drop_duplicates("start_date").set_index("start_date")
    common = clean_by.index.intersection(altered_by.index)
    deltas = (altered_by.loc[common, "p_survive_10"] - clean_by.loc[common, "p_survive_10"])
    return {
        "clean_test_episodes": int(len(clean_test)),
        "altered_test_episodes": int(len(altered_test)),
        "starts_added": int(len(altered_by.index.difference(clean_by.index))),
        "starts_removed": int(len(clean_by.index.difference(altered_by.index))),
        "matched_start_dates": int(len(common)),
        "matched_mean_abs_delta_p_survive_10": float(deltas.abs().mean()) if len(deltas) else None,
        "matched_mean_signed_delta_p_survive_10": float(deltas.mean()) if len(deltas) else None,
    }


def risk_view(frame: pd.DataFrame, reference_returns: np.ndarray,
              test_mask: np.ndarray):
    px = frame[list(RISK_ASSETS)].to_numpy(dtype=float)
    if not np.isfinite(px).all() or (px <= 0).any():
        raise ValueError("La cartera proxy requiere precios completos y positivos")
    r = np.diff(np.log(px), axis=0)
    port = r.mean(axis=1)
    var = np.full(len(port), np.nan)
    for t in range(VAR_WINDOW, len(port)):
        var[t] = -float(np.quantile(port[t - VAR_WINDOW:t], 1.0 - ALPHA))
    valid = test_mask[1:] & np.isfinite(var)
    realized = reference_returns[valid]
    estimate = var[valid]
    exceptions = realized < -estimate
    tail = realized[realized <= np.quantile(realized, 1.0 - ALPHA)]
    return {
        "test_observations": int(valid.sum()),
        "mean_historical_var_99": float(np.mean(estimate)),
        "exceptions_on_clean_reference": int(exceptions.sum()),
        "exception_rate_on_clean_reference": float(np.mean(exceptions)),
        "clean_reference_es_99": float(-np.mean(tail)) if len(tail) else None,
        "capital_eur": None,
        "capital_note": "No holdings/notional supplied; report is an equal-weight return-risk proxy, not capital in EUR or regulatory capital.",
    }


def run(panel_path: Path, brent_path: Path, out: Path):
    data = make_windows(panel_path)
    masks = data["train_mask"], data["val_mask"], data["test_mask"]
    tr_bounds = [b for b, keep in zip(data["bounds"], masks[0]) if keep]
    va_bounds = [b for b, keep in zip(data["bounds"], masks[1]) if keep]
    te_bounds = data["test_bounds"]
    families = tuple(channel.PRICE_FAMILIES)

    # The shared fit_cnn helper currently constructs and trains on CPU.
    models = [cnn_base.fit_cnn(data["train_z"], data["val_z"], seed=s, epochs=40)
              for s in SEEDS]
    validation = all_scores(data["val_p"], data["val_z"], models)
    thresholds = {name: calibration_threshold(score) for name, score in validation.items()}
    xgb_model, xgb_features = fit_xgb_combiner(
        data["prices"], tr_bounds, data["train_z"], models)
    xgb_val = np.column_stack([validation[n] for n in xgb_features])
    thresholds["xgboost_combiner"] = calibration_threshold(
        xgb_model.predict_proba(xgb_val)[:, 1])

    clean_test_scores = all_scores(data["test_p"], data["test_z"], models)
    clean_fpr = {name: float(np.mean(scores > thresholds[name]))
                 for name, scores in clean_test_scores.items()}
    clean_test_xgb = np.column_stack([clean_test_scores[n] for n in xgb_features])
    clean_fpr["xgboost_combiner"] = float(np.mean(
        xgb_model.predict_proba(clean_test_xgb)[:, 1] > thresholds["xgboost_combiner"]))
    fpr_intervals = {}
    for name, rate in clean_fpr.items():
        events = int(round(rate * len(data["test_z"])))
        fpr_intervals[name] = {
            "alerts": events,
            "test_windows": int(len(data["test_z"])),
            "clopper_pearson_95": exact_binomial_interval(events, len(data["test_z"])),
        }

    injected = recompute_window_scores(data["prices"], te_bounds, families, models)
    recalls = {}
    for family in families:
        recalls[family] = {}
        for name, scores in injected[family].items():
            if name == "xgboost_combiner":
                continue
            recalls[family][name] = float(np.mean(scores > thresholds[name]))
        xgb_scores = np.column_stack([injected[family][n] for n in xgb_features])
        recalls[family]["xgboost_combiner"] = float(np.mean(
            xgb_model.predict_proba(xgb_scores)[:, 1] > thresholds["xgboost_combiner"]))

    # Full-price channel/survival rebuild, frozen AFT fit on clean pre-2019 episodes.
    brent = survival.load_brent(str(brent_path))
    clean_episodes = survival.extract_episodes(brent.to_numpy(), pd.DatetimeIndex(brent.index))
    aft, aft_mean, aft_scale, aft_n, aft_events = fit_clean_aft(clean_episodes)
    test_dates = [(data["starts"][i], data["ends"][i]) for i, keep in enumerate(masks[2]) if keep]
    survival_stress, risk_stress = {}, {}

    # Portfolio risk uses the same market dates and defect schedule; reference
    # exceptions are evaluated against clean equal-weight returns.
    frame = pd.read_csv(panel_path, parse_dates=["date"])
    frame = frame[["date", *RISK_ASSETS]].dropna().reset_index(drop=True)
    frame = frame.set_index("date")
    clean_px = frame.copy()
    clean_risk_returns = np.diff(np.log(clean_px[list(RISK_ASSETS)].to_numpy(float)), axis=0).mean(axis=1)
    clean_test_mask = pd.DatetimeIndex(clean_px.index) > VAL_END
    clean_risk = risk_view(clean_px, clean_risk_returns, clean_test_mask)
    risk_stress["clean"] = clean_risk

    for family in families:
        altered_brent, count = apply_stress_to_brent(brent, test_dates, family)
        altered_episodes = survival.extract_episodes(
            altered_brent.to_numpy(), pd.DatetimeIndex(altered_brent.index))
        survival_stress[family] = {
            "corrupted_blocks": count,
            **episode_comparison(clean_episodes, altered_episodes, aft, aft_mean, aft_scale),
        }
        altered_frame = clean_px.copy()
        rng = np.random.default_rng(900_000 + list(families).index(family))
        for wi, (start, end) in enumerate(test_dates):
            if wi % STRESS_EVERY:
                continue
            idx = np.flatnonzero((altered_frame.index >= start) & (altered_frame.index <= end))
            if len(idx) < 5:
                continue
            block = altered_frame.iloc[idx].to_numpy(float)
            altered_frame.iloc[idx] = channel.PRICE_FAMILIES[family](block, 0, len(block), rng)
        scenario_returns = np.diff(np.log(altered_frame[list(RISK_ASSETS)].to_numpy(float)), axis=0).mean(axis=1)
        risk_stress[family] = risk_view(altered_frame, clean_risk_returns, clean_test_mask)
        risk_stress[family]["delta_mean_var_pct"] = float(
            100 * (risk_stress[family]["mean_historical_var_99"] / clean_risk["mean_historical_var_99"] - 1))
        risk_stress[family]["corrupted_test_return_vol_pct"] = float(
            100 * np.std(scenario_returns[clean_test_mask[1:]]) / max(np.std(clean_risk_returns[clean_test_mask[1:]]), 1e-12) - 100)

    report = {
        "protocol": {
            "panel": str(panel_path), "brent_survival_series": str(brent_path),
            "window_length_sessions": WINDOW, "stride_sessions": STRIDE,
            "nonoverlapping_windows": True, "train_end": str(FIT_END.date()),
            "validation_end": str(VAL_END.date()), "test_start": str(data["starts"][masks[2]][0].date()),
            "n_windows": {"train": int(masks[0].sum()), "validation": int(masks[1].sum()), "test": int(masks[2].sum())},
            "threshold_calibration": "clean validation only; frozen for test",
            "target_fpr": DQ_FP, "families": list(families),
            "xgb_dq_training_families": list(TRAIN_FAMILIES),
            "xgb_dq_holdout_families": [f for f in families if f not in TRAIN_FAMILIES],
            "stress_injection_density": f"one corruption per {STRESS_EVERY} non-overlapping test windows",
            "survival_model": "single XGB-AFT fit on clean channel episodes start_date <= 2018-12-31, admin-censored at cutoff; frozen across corruption scenarios",
            "survival_train_episodes": aft_n, "survival_train_events": aft_events,
            "risk_proxy": "equal-weight BRENT/COPPER/EUROSTOXX50/GOLD/SP500; rolling 250-session historical VaR 99%; no positions supplied",
            "limitations": ["only one market panel; synthetic defects", "non-overlap reduces test sample size", "risk view is not regulatory capital or currency P&L", "episode extraction retains the existing production definition and its limitations"],
            "device_cnn": "cpu (dq_cnn1d_supervised.fit_cnn)",
            "device_xgboost_dq": "cpu",
        },
        "thresholds_from_clean_validation": thresholds,
        "realized_clean_test_fpr": clean_fpr,
        "realized_clean_test_fpr_exact_95ci": fpr_intervals,
        "localized_window_recall_by_family": recalls,
        "channel_episode_and_frozen_aft_impact": survival_stress,
        "equal_weight_risk_proxy": risk_stress,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=ROOT / "data/panel_extendido_2026-09-09.csv")
    parser.add_argument("--brent", type=Path, default=ROOT / "data/brent_fred_daily.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "results/reports/dq_channel_confirmatory")
    args = parser.parse_args()
    print(json.dumps(run(args.panel, args.brent, args.out), indent=2))


if __name__ == "__main__":
    main()
