#!/usr/bin/env python3
"""Compare channel controls on levels and rolling-return representations.

Defects are injected into price observations, then returns are recomputed. CNN
and XGBoost are evaluated with frozen validation thresholds and untouched test.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import roc_auc_score
import xgboost
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[3]
EXP = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, EXP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load("dq_cnn1d_supervised")
channel = _load("dq_channel_representation")
pricelab = _load("dq_quantize_price_grid")
gate = _load("dq_conformal_gate")

WINDOW = base.WINDOW
WINDOW_STRIDE = base.WINDOW_STRIDE
FP_TARGET = base.FP_TARGET
FIT_END = base.FIT_END
VAL_END = base.VAL_END
SEEDS = (42, 71, 123)
FIT_FAMILIES = tuple(base.FAMILIES)
ALL_FAMILIES = tuple(channel.PRICE_FAMILIES)
CHANNELS = {
    "coherence": channel.channel_coherence_score,
    "breach": channel.channel_breach_score,
    "geometry_shift": channel.channel_geometry_shift_score,
    "oscillation_deficit": channel.channel_oscillation_score,
}


def returns_from_prices(price_windows: np.ndarray) -> np.ndarray:
    """Log returns, except WTI dollar changes to preserve the negative settle."""
    prices = np.asarray(price_windows, dtype=float)
    out = np.empty((len(prices), prices.shape[1] - 1, prices.shape[2]), dtype=float)
    log_cols = [i for i, asset in enumerate(base.ASSETS) if asset != "WTI"]
    out[:, :, log_cols] = np.diff(np.log(prices[:, :, log_cols]), axis=1)
    wti = base.ASSETS.index("WTI")
    out[:, :, wti] = np.diff(prices[:, :, wti], axis=1)
    return out


def cumulative_return_path(return_windows: np.ndarray) -> np.ndarray:
    """Rebase the cumulative return path at zero for each window."""
    returns = np.asarray(return_windows, dtype=float)
    origin = np.zeros((len(returns), 1, returns.shape[2]), dtype=float)
    return np.concatenate([origin, np.cumsum(returns, axis=1)], axis=1)


def zero_return_run_scores(return_windows: np.ndarray, target: int = 0) -> np.ndarray:
    """Longest exact-zero return run for the target series in each window."""
    returns = np.asarray(return_windows, dtype=float)
    scores = np.zeros(len(returns), dtype=float)
    for i, window in enumerate(returns):
        run = best = 0
        for value in window[:, target]:
            run = run + 1 if np.isfinite(value) and value == 0.0 else 0
            best = max(best, run)
        scores[i] = best
    return scores


def causal_hampel_scores(z_windows: np.ndarray, target: int = 0,
                         min_history: int = 8) -> np.ndarray:
    """Maximum robust-z of each target return vs strictly preceding window data."""
    windows = np.asarray(z_windows, dtype=float)
    scores = np.zeros(len(windows), dtype=float)
    for i, window in enumerate(windows):
        series = window[:, target]
        for t in range(min_history, len(series)):
            history = series[:t]
            history = history[np.isfinite(history)]
            if len(history) < min_history or not np.isfinite(series[t]):
                continue
            median = float(np.median(history))
            mad = float(np.median(np.abs(history - median))) * 1.4826
            if mad > 1e-12:
                scores[i] = max(scores[i], abs(float(series[t]) - median) / mad)
    return scores


def normalize_corrupted_window(full_prices: np.ndarray, start: int, stop: int,
                               corrupted_window: np.ndarray) -> np.ndarray:
    """Causal rolling normalization for a changed [start, stop) return window."""
    roll = 60
    lo = max(0, start - roll - 1)
    segment = full_prices[lo:stop + 1].copy()
    offset = start - lo
    segment[offset:offset + len(corrupted_window)] = corrupted_window
    returns = np.empty((len(segment) - 1, segment.shape[1]), dtype=float)
    log_cols = [i for i, asset in enumerate(base.ASSETS) if asset != "WTI"]
    returns[:, log_cols] = np.diff(np.log(segment[:, log_cols]), axis=0)
    wti = base.ASSETS.index("WTI")
    returns[:, wti] = np.diff(segment[:, wti])
    result = np.full((stop - start, len(base.ASSETS)), np.nan, dtype=float)
    for j in range(returns.shape[1]):
        series = pd.Series(returns[:, j])
        mean = series.rolling(roll, min_periods=20).mean().shift(1).to_numpy()
        sigma = series.rolling(roll, min_periods=20).std().shift(1).to_numpy()
        for k in range(stop - start):
            i = offset + k
            if np.isfinite(mean[i]) and np.isfinite(sigma[i]) and sigma[i] > 1e-10:
                result[k, j] = (returns[i, j] - mean[i]) / sigma[i]
    if not np.isfinite(result).all():
        raise ValueError("Inyección produjo retornos normalizados no finitos")
    return result.astype(np.float32)


def channel_features(windows: np.ndarray) -> np.ndarray:
    return np.column_stack([fn(windows) for fn in CHANNELS.values()])


def representations(price_windows: np.ndarray, z_windows: np.ndarray) -> dict[str, np.ndarray]:
    raw_returns = returns_from_prices(price_windows)
    return {
        "price_levels": price_windows,
        "cumulative_returns": cumulative_return_path(raw_returns),
        "raw_returns": raw_returns,
        "causal_z_returns": np.asarray(z_windows, dtype=float),
    }


def detector_features(price_windows: np.ndarray, z_windows: np.ndarray,
                      cnn_score: np.ndarray | None = None) -> dict[str, np.ndarray]:
    reps = representations(price_windows, z_windows)
    raw_returns = reps["raw_returns"]
    result = {f"channel_{name}": channel_features(value)
              for name, value in reps.items()}
    result["price_controls"] = np.column_stack([
        result["channel_price_levels"], pricelab.grid_step_score(price_windows)])
    return_controls = np.column_stack([
        result["channel_causal_z_returns"],
        base.score_cross_asset(z_windows),
        base.score_3sigma(z_windows),
        np.max(np.abs(z_windows[:, :, 0]), axis=1),
        causal_hampel_scores(z_windows),
        zero_return_run_scores(raw_returns),
    ])
    result["return_controls"] = return_controls
    if cnn_score is not None:
        result["return_controls_plus_cnn"] = np.column_stack([return_controls, cnn_score])
    return result


def _fit_cnn(x_train: np.ndarray, y_train: np.ndarray,
             x_valid: np.ndarray, y_valid: np.ndarray, seed: int,
             device: torch.device) -> nn.Module:
    torch.manual_seed(seed)
    np.random.seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    model = base.DQConv1D(x_train.shape[2]).to(device)
    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
        batch_size=128, shuffle=True,
    )
    valid_x = torch.from_numpy(x_valid).to(device)
    valid_y = torch.from_numpy(y_valid).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss()
    best_loss, best_state, patience = float("inf"), None, 0
    for _ in range(50):
        model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            valid_loss = float(loss_fn(model(valid_x), valid_y))
        if valid_loss < best_loss - 1e-5:
            best_loss = valid_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= 8:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model


def _score_cnn(model: nn.Module, windows: np.ndarray,
               device: torch.device) -> np.ndarray:
    x = torch.from_numpy(np.clip(windows, -15.0, 15.0).astype(np.float32)).to(device)
    with torch.no_grad():
        return torch.sigmoid(model(x)).cpu().numpy()


def _labeled_windows(full_prices: np.ndarray, windows: np.ndarray,
                     bounds: list[tuple[int, int]], indices: np.ndarray,
                     families: tuple[str, ...], seed: int):
    clean_x, dirty_by_family = [], {f: [] for f in families}
    rng = np.random.default_rng(seed)
    for local_i, idx in enumerate(indices):
        a, b = bounds[int(idx)]
        clean = windows[local_i]
        clean_x.append(clean)
        price_window = full_prices[a:b + 1]
        for family in families:
            changed = channel.PRICE_FAMILIES[family](
                price_window, 0, len(price_window), rng)
            dirty_by_family[family].append(
                normalize_corrupted_window(full_prices, a, b, changed))
    clean_x = np.asarray(clean_x, dtype=np.float32)
    dirty_by_family = {f: np.asarray(v, dtype=np.float32)
                       for f, v in dirty_by_family.items()}
    x = np.concatenate([clean_x, *dirty_by_family.values()])
    y = np.r_[np.zeros(len(clean_x)),
              np.ones(sum(len(v) for v in dirty_by_family.values()))].astype(np.float32)
    return x, y, dirty_by_family


def _inject_test(full_prices, bounds, price_windows, families, seed):
    rng = np.random.default_rng(seed)
    dirty = {f: [] for f in families}
    dirty_z = {f: [] for f in families}
    for i, (a, b) in enumerate(bounds):
        for family in families:
            changed = channel.PRICE_FAMILIES[family](
                price_windows[i], 0, len(price_windows[i]), rng)
            dirty[family].append(changed)
            dirty_z[family].append(normalize_corrupted_window(full_prices, a, b, changed))
    return ({f: np.asarray(v, dtype=float) for f, v in dirty.items()},
            {f: np.asarray(v, dtype=np.float32) for f, v in dirty_z.items()})


def _xgb(seed: int) -> XGBClassifier:
    return XGBClassifier(n_estimators=300, max_depth=3, min_child_weight=10,
                         learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                         reg_lambda=1.0, eval_metric="logloss", random_state=seed,
                         n_jobs=8, tree_method="hist")


def _record(result, model_name, calibration_scores, test_scores,
            injected_scores, target=FP_TARGET, fixed_threshold=None,
            inclusive=False):
    threshold = (gate.calibration_threshold(calibration_scores, target)
                 if fixed_threshold is None else float(fixed_threshold))
    exceeds = (lambda scores: scores >= threshold) if inclusive else (lambda scores: scores > threshold)
    row = result.setdefault(model_name, {"test_false_positive_rate": [],
                                         "calibration_false_positive_rate": [],
                                         "recall_by_family": {}})
    row["calibration_false_positive_rate"].append(float(np.mean(exceeds(calibration_scores))))
    row["test_false_positive_rate"].append(float(np.mean(exceeds(test_scores))))
    dirty_test = np.concatenate(list(injected_scores.values()))
    row.setdefault("test_roc_auc", []).append(float(roc_auc_score(
        np.r_[np.zeros(len(test_scores)), np.ones(len(dirty_test))],
        np.r_[test_scores, dirty_test],
    )))
    row.setdefault("roc_auc_by_family", {})
    for family, scores in injected_scores.items():
        row["recall_by_family"].setdefault(family, []).append(
            float(np.mean(exceeds(scores))))
        row["roc_auc_by_family"].setdefault(family, []).append(float(roc_auc_score(
            np.r_[np.zeros(len(test_scores)), np.ones(len(scores))],
            np.r_[test_scores, scores],
        )))


def _mean_sd(values):
    return {"mean": float(np.mean(values)), "std": float(np.std(values))}


def rolling_thresholds(initial_scores: np.ndarray, stream_scores: np.ndarray,
                       target: float = FP_TARGET, window: int = 68,
                       update_accepted_only: bool = False) -> np.ndarray:
    """Causal rolling thresholds; score at t is never used to threshold itself."""
    history = list(np.asarray(initial_scores, dtype=float)[-window:])
    stream = np.asarray(stream_scores, dtype=float)
    thresholds = np.empty(len(stream), dtype=float)
    for i, score in enumerate(stream):
        threshold = gate.calibration_threshold(np.asarray(history), target)
        thresholds[i] = threshold
        if not update_accepted_only or score <= threshold:
            history.append(float(score))
            history = history[-window:]
    return thresholds


def _record_rolling(result, model_name, calibration_scores, test_scores,
                    injected_scores):
    for policy, accepted_only in (("rolling_all_past", False),
                                  ("rolling_non_alerts", True)):
        thresholds = rolling_thresholds(
            calibration_scores, test_scores, update_accepted_only=accepted_only)
        row = result.setdefault(model_name, {}).setdefault(policy, {
            "test_false_positive_rate": [], "recall_by_family": {},
            "threshold_start": [], "threshold_end": [],
        })
        row["test_false_positive_rate"].append(
            float(np.mean(test_scores > thresholds)))
        row["threshold_start"].append(float(thresholds[0]))
        row["threshold_end"].append(float(thresholds[-1]))
        for family, scores in injected_scores.items():
            row["recall_by_family"].setdefault(family, []).append(
                float(np.mean(scores > thresholds)))


def run(panel: Path, output_dir: Path, seeds: tuple[int, ...] = SEEDS) -> dict:
    torch.use_deterministic_algorithms(True)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    raw = panel.read_bytes()
    frame = pd.read_csv(panel, parse_dates=["date"])
    frame = frame[["date", *base.ASSETS]].dropna().reset_index(drop=True)
    full_prices = frame[list(base.ASSETS)].to_numpy(dtype=float)
    dates = pd.DatetimeIndex(frame["date"])
    scaled = pricelab.normalize(full_prices)
    bounds = pricelab.window_bounds(scaled)
    return_dates = dates[1:]
    starts = pd.DatetimeIndex([return_dates[a] for a, _ in bounds])
    ends = pd.DatetimeIndex([return_dates[b - 1] for _, b in bounds])
    train_idx = np.flatnonzero(ends <= FIT_END)
    val_idx = np.flatnonzero((starts > FIT_END) & (ends <= VAL_END))
    test_idx = np.flatnonzero(starts > VAL_END)
    purge = int(np.ceil(WINDOW / WINDOW_STRIDE)) - 1
    n_fit = int(0.70 * len(val_idx))
    cal_start = n_fit + purge
    if len(val_idx) - cal_start < 20:
        raise ValueError("Validación insuficiente para ajuste/calibración temporal")
    fit_idx, cal_idx = val_idx[:n_fit], val_idx[cal_start:]

    z_windows = np.asarray([scaled[a:b] for a, b in bounds], dtype=np.float32)
    p_windows = np.asarray([full_prices[a:b + 1] for a, b in bounds], dtype=float)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    result: dict[str, dict] = {}
    rolling_result: dict[str, dict] = {}

    for seed in seeds:
        x_train, y_train, _ = _labeled_windows(
            full_prices, z_windows[train_idx], bounds, train_idx, FIT_FAMILIES, seed + 100)
        x_valid, y_valid, _ = _labeled_windows(
            full_prices, z_windows[fit_idx], bounds, fit_idx, FIT_FAMILIES, seed + 200)
        cnn = _fit_cnn(x_train, y_train, x_valid, y_valid, seed, device)

        fit_clean_features = detector_features(
            p_windows[fit_idx], z_windows[fit_idx], _score_cnn(cnn, z_windows[fit_idx], device))
        fit_dirty_p, fit_dirty_z = _inject_test(
            full_prices, [bounds[i] for i in fit_idx], p_windows[fit_idx],
            FIT_FAMILIES, seed + 300)
        xgb_train_inputs = {}
        for config in ("price_controls", "return_controls", "return_controls_plus_cnn"):
            clean_rows = [fit_clean_features[config]]
            dirty_rows = []
            for family in FIT_FAMILIES:
                dirty_cnn = _score_cnn(cnn, fit_dirty_z[family], device)
                features = detector_features(fit_dirty_p[family], fit_dirty_z[family], dirty_cnn)
                dirty_rows.append(features[config])
            xgb_train_inputs[config] = (
                np.vstack(clean_rows + dirty_rows),
                np.r_[np.zeros(len(fit_idx)), np.ones(len(fit_idx) * len(FIT_FAMILIES))],
            )
        xgb_models = {}
        for config, (x, y) in xgb_train_inputs.items():
            model = _xgb(seed).fit(x, y)
            xgb_models[config] = model

        cal_p, cal_z = p_windows[cal_idx], z_windows[cal_idx]
        test_p, test_z = p_windows[test_idx], z_windows[test_idx]
        cal_scores = _score_cnn(cnn, cal_z, device)
        test_scores = _score_cnn(cnn, test_z, device)
        dirty_test_p, dirty_test_z = _inject_test(
            full_prices, [bounds[i] for i in test_idx], test_p,
            ALL_FAMILIES, seed + 400)
        dirty_cnn_scores = {f: _score_cnn(cnn, z, device)
                            for f, z in dirty_test_z.items()}

        cal_features = detector_features(cal_p, cal_z, cal_scores)
        test_features = detector_features(test_p, test_z, test_scores)
        dirty_features = {
            f: detector_features(dirty_test_p[f], dirty_test_z[f], dirty_cnn_scores[f])
            for f in ALL_FAMILIES
        }

        direct = {
            "cnn_rolling_z_returns": (cal_scores, test_scores, dirty_cnn_scores),
            "trim_zero_return_run_20": (
                zero_return_run_scores(returns_from_prices(cal_p)),
                zero_return_run_scores(returns_from_prices(test_p)),
                {f: zero_return_run_scores(returns_from_prices(dirty_test_p[f]))
                 for f in ALL_FAMILIES}),
            "causal_hampel_target_return": (
                causal_hampel_scores(cal_z), causal_hampel_scores(test_z),
                {f: causal_hampel_scores(dirty_test_z[f]) for f in ALL_FAMILIES}),
            "max_abs_target_rolling_z_return": (
                np.max(np.abs(cal_z[:, :, 0]), axis=1),
                np.max(np.abs(test_z[:, :, 0]), axis=1),
                {f: np.max(np.abs(dirty_test_z[f][:, :, 0]), axis=1)
                 for f in ALL_FAMILIES}),
            "cross_asset_1_minus_r2": (
                base.score_cross_asset(cal_z), base.score_cross_asset(test_z),
                {f: base.score_cross_asset(dirty_test_z[f]) for f in ALL_FAMILIES}),
            "max_abs_rolling_z_return": (
                base.score_3sigma(cal_z), base.score_3sigma(test_z),
                {f: base.score_3sigma(dirty_test_z[f]) for f in ALL_FAMILIES}),
        }
        for rep in ("price_levels", "cumulative_returns", "raw_returns", "causal_z_returns"):
            for j, name in enumerate(CHANNELS):
                key = f"{rep}_channel_{name}"
                direct[key] = (
                    cal_features[f"channel_{rep}"][:, j],
                    test_features[f"channel_{rep}"][:, j],
                    {f: dirty_features[f][f"channel_{rep}"][:, j] for f in ALL_FAMILIES},
                )
        for name, (cal, test, dirty) in direct.items():
            if name == "trim_zero_return_run_20":
                _record(result, name, cal, test, dirty,
                        fixed_threshold=WINDOW, inclusive=True)
            else:
                _record(result, name, cal, test, dirty)
                _record_rolling(rolling_result, name, cal, test, dirty)

        for config, model in xgb_models.items():
            cal = model.predict_proba(cal_features[config])[:, 1]
            test = model.predict_proba(test_features[config])[:, 1]
            dirty = {f: model.predict_proba(dirty_features[f][config])[:, 1]
                     for f in ALL_FAMILIES}
            model_name = f"xgb_{config}"
            _record(result, model_name, cal, test, dirty)
            _record_rolling(rolling_result, model_name, cal, test, dirty)

    summarized = {}
    for name, row in result.items():
        summarized[name] = {
            "calibration_false_positive_rate": _mean_sd(row["calibration_false_positive_rate"]),
            "test_false_positive_rate": _mean_sd(row["test_false_positive_rate"]),
            "test_roc_auc": _mean_sd(row["test_roc_auc"]),
            "recall_by_family": {f: _mean_sd(v) for f, v in row["recall_by_family"].items()},
            "roc_auc_by_family": {f: _mean_sd(v) for f, v in row["roc_auc_by_family"].items()},
        }
    rolling_summary = {}
    for name, policies in rolling_result.items():
        rolling_summary[name] = {}
        for policy, row in policies.items():
            rolling_summary[name][policy] = {
                "test_false_positive_rate": _mean_sd(row["test_false_positive_rate"]),
                "recall_by_family": {f: _mean_sd(v)
                                     for f, v in row["recall_by_family"].items()},
                "threshold_start": _mean_sd(row["threshold_start"]),
                "threshold_end": _mean_sd(row["threshold_end"]),
            }
    output = {
        "protocol": {
            "source": str(panel),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "code_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (Path(__file__), EXP / "dq_cnn1d_supervised.py",
                             EXP / "dq_channel_representation.py",
                             EXP / "dq_quantize_price_grid.py",
                             EXP / "dq_conformal_gate.py")
            },
            "software": {
                "numpy": np.__version__, "pandas": pd.__version__,
                "torch": torch.__version__, "xgboost": xgboost.__version__,
            },
            "assets": list(base.ASSETS),
            "train_windows": int(len(train_idx)),
            "validation_model_selection_windows": int(len(fit_idx)),
            "validation_purged_windows": int(purge),
            "validation_calibration_windows": int(len(cal_idx)),
            "test_windows": int(len(test_idx)),
            "test_start": str(starts[test_idx[0]].date()),
            "test_end": str(ends[test_idx[-1]].date()),
            "window_sessions": WINDOW,
            "window_stride_sessions": WINDOW_STRIDE,
            "nominal_fpr_target": FP_TARGET,
            "threshold": "frozen empirical order statistic from later clean validation; test is not used for threshold/model selection",
            "rolling_thresholds": {
                "window": 68,
                "policies": {
                    "rolling_all_past": "uses prior unlabeled test scores; causal but assumes prior scores are suitable calibration data",
                    "rolling_non_alerts": "updates only with prior non-alert scores; causal but non-alert does not imply clean",
                },
                "injected_recall": "counterfactual current-window injection scored against thresholds derived from the corresponding unmodified observed stream",
                "limitations": "exploratory; the rolling stream is unadjudicated, windows overlap, and no calibration guarantee is claimed",
            },
            "defect_protocol": "price-space corruption followed by causal recomputation of raw and standardized returns",
            "statistical_controls": {
                "trim_zero_return_run_20": "fixed rule at >=20 exact consecutive target-asset zero returns; not recalibrated",
                "causal_hampel_target_return": "maximum robust-z against preceding observations only",
                "max_abs_target_rolling_z_return": "3-sigma-style target series score; same validation threshold protocol",
            },
            "fit_families": list(FIT_FAMILIES),
            "test_families": list(ALL_FAMILIES),
            "return_transforms": ["raw_returns", "cumulative_returns_rebased_at_zero", "causal_rolling_z_returns"],
            "cnn_device": str(device),
            "seeds": list(seeds),
            "limitations": [
                "test windows overlap by 75%; windows are not independent replicates",
                "synthetic defect labels; no real incident prevalence or PPV",
                "ROC AUC is descriptive on synthetic defects and overlapping windows; it is not a calibrated operating-point comparison",
                "FPR is reported as observed and may differ from the nominal calibration target",
                "XGB return feature bank includes channel, cross-asset, 3-sigma, causal Hampel, target-series z and TRIM run length; CNN is tested as an additional feature",
            ],
        },
        "results": summarized,
        "rolling_calibration": rolling_summary,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_rolling_return_channel")
    args = parser.parse_args()
    out = run(args.panel, args.output)
    for name, row in out["results"].items():
        print(f"{name:42s} FPR OOS={row['test_false_positive_rate']['mean']:.3f}")
    print("\nRolling threshold OOS FPR:")
    for name, policies in out["rolling_calibration"].items():
        for policy, row in policies.items():
            print(f"{name:42s} {policy:20s} "
                  f"FPR={row['test_false_positive_rate']['mean']:.3f}")
    print(f"\n-> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
