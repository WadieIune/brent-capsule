#!/usr/bin/env python3
"""As-of early-warning benchmark for future Brent volatility and downside tails.

This is a market-risk monitor, not a data-quality detector or trading policy.
The first pilot uses lagged univariate statistics and XGBoost; channel/CNN
features are reserved for a subsequent incremental ablation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[3]
HORIZON = 20
TRAIN_END = "2004-12-31"
VALIDATION_END = "2007-12-31"
ALERT_BUDGET = 0.05
FEATURE_WINDOWS = (20, 60, 90)


def load_brent(path: Path) -> pd.Series:
    frame = pd.read_csv(path, parse_dates=["date"])
    if not {"date", "BRENT"}.issubset(frame.columns):
        raise ValueError("Se requieren columnas date y BRENT")
    frame = frame[["date", "BRENT"]].dropna().sort_values("date")
    if frame["date"].duplicated().any():
        raise ValueError("Fechas duplicadas en Brent")
    if (frame["BRENT"] <= 0).any():
        raise ValueError("Log-retornos requieren precios positivos")
    return frame.set_index("date")["BRENT"].astype(float)


def causal_features(prices: pd.Series) -> pd.DataFrame:
    """Trailing-only features; row t uses prices/returns no later than t."""
    ret = np.log(prices).diff()
    out = pd.DataFrame(index=prices.index)
    for window in FEATURE_WINDOWS:
        roll = ret.rolling(window, min_periods=window)
        out[f"vol_{window}"] = roll.std(ddof=1) * np.sqrt(252.0)
        out[f"mean_{window}"] = roll.mean() * 252.0
        out[f"downside_vol_{window}"] = ret.clip(upper=0).rolling(
            window, min_periods=window
        ).std(ddof=1) * np.sqrt(252.0)
        out[f"zero_fraction_{window}"] = ret.eq(0).rolling(
            window, min_periods=window
        ).mean()
        out[f"q05_{window}"] = roll.quantile(0.05)
    out["vol_ratio_20_90"] = out["vol_20"] / out["vol_90"].replace(0, np.nan)
    out["return_20"] = np.log(prices / prices.shift(20))
    out["return_60"] = np.log(prices / prices.shift(60))
    out["drawdown_20"] = prices / prices.rolling(20, min_periods=20).max() - 1.0
    out["drawdown_60"] = prices / prices.rolling(60, min_periods=60).max() - 1.0
    out["autocorr_1_60"] = ret.rolling(60, min_periods=60).apply(
        lambda x: pd.Series(x).autocorr(lag=1), raw=False
    )
    return out.replace([np.inf, -np.inf], np.nan)


def future_targets(prices: pd.Series, horizon: int = HORIZON) -> pd.DataFrame:
    """Forward outcomes indexed at forecast origin t; excludes return at t."""
    ret = np.log(prices).diff()
    reverse = ret.iloc[::-1]
    future_vol = reverse.rolling(horizon, min_periods=horizon).std(ddof=1).iloc[::-1]
    future_vol.index = future_vol.index
    future_vol = future_vol.shift(-1) * np.sqrt(252.0)
    future_sum = reverse.rolling(horizon, min_periods=horizon).sum().iloc[::-1]
    future_sum = future_sum.shift(-1)
    return pd.DataFrame({"future_vol": future_vol, "future_return": future_sum})


def _positive_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    padded = np.r_[False, np.asarray(mask, dtype=bool), False].astype(np.int8)
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def episode_metrics(y: np.ndarray, alerts: np.ndarray,
                    horizon: int = HORIZON) -> dict[str, float | int]:
    """Cluster overlapping positive forecast origins into risk episodes."""
    runs = _positive_runs(y)
    episodes: list[tuple[int, int]] = []
    for start, end in runs:
        if episodes and start - episodes[-1][1] < horizon:
            episodes[-1] = (episodes[-1][0], end)
        else:
            episodes.append((start, end))
    leads: list[int] = []
    for start, _ in episodes:
        prior = np.flatnonzero(alerts[max(0, start - horizon):start + 1])
        if len(prior):
            alert_idx = max(0, start - horizon) + int(prior[-1])
            leads.append(start - alert_idx)
    return {
        "episodes": len(episodes),
        "episodes_hit": len(leads),
        "episode_recall": len(leads) / len(episodes) if episodes else float("nan"),
        "median_lead_sessions": float(np.median(leads)) if leads else float("nan"),
    }


def _alert_threshold(validation_scores: np.ndarray,
                     budget: float = ALERT_BUDGET) -> float:
    scores = validation_scores[np.isfinite(validation_scores)]
    if not len(scores):
        raise ValueError("No hay scores finitos en validación")
    return float(np.quantile(scores, 1.0 - budget, method="higher"))


def _cusum_score(returns: pd.Series, baseline: float, allowance: float) -> pd.Series:
    """One-sided CUSUM of log squared returns for upward variance shifts."""
    variance = returns.pow(2).clip(lower=1e-12)
    increments = np.log(variance / max(baseline, 1e-12)) - allowance
    values = np.zeros(len(increments), dtype=float)
    for i, value in enumerate(increments.fillna(0).to_numpy()):
        values[i] = max(0.0, (values[i - 1] if i else 0.0) + value)
    return pd.Series(values, index=returns.index)


def _fit_xgb(x: pd.DataFrame, y: np.ndarray) -> XGBClassifier:
    model = XGBClassifier(
        n_estimators=180, max_depth=3, learning_rate=0.03,
        subsample=0.85, colsample_bytree=0.85, reg_lambda=2.0,
        min_child_weight=10, eval_metric="logloss", n_jobs=1,
        random_state=17,
    )
    model.fit(x, y)
    return model


def _evaluate(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    valid = np.isfinite(scores)
    yv, sv = y[valid], scores[valid]
    alerts = sv >= threshold
    return {
        "n": int(len(yv)),
        "event_prevalence": float(yv.mean()),
        "alert_rate": float(alerts.mean()),
        "precision": float(yv[alerts].mean()) if alerts.any() else 0.0,
        "recall_by_origin": float(alerts[yv == 1].mean()) if (yv == 1).any() else 0.0,
        "average_precision": float(average_precision_score(yv, sv)) if len(np.unique(yv)) > 1 else float("nan"),
        "roc_auc": float(roc_auc_score(yv, sv)) if len(np.unique(yv)) > 1 else float("nan"),
        **episode_metrics(yv, alerts),
    }


def run(path: Path, output: Path) -> dict:
    prices = load_brent(path)
    ret = np.log(prices).diff()
    features = causal_features(prices)
    targets = future_targets(prices)
    dates = prices.index
    train_end = pd.Timestamp(TRAIN_END)
    val_end = pd.Timestamp(VALIDATION_END)
    train_mask = (dates <= train_end) & features.notna().all(axis=1) & targets.notna().all(axis=1)
    val_mask = (dates > train_end) & (dates <= val_end) & features.notna().all(axis=1) & targets.notna().all(axis=1)
    test_mask = (dates > val_end) & features.notna().all(axis=1) & targets.notna().all(axis=1)
    # Purge origins whose forward labels cross a split boundary.
    train_mask &= dates <= train_end - pd.offsets.BDay(HORIZON)
    val_mask &= dates <= val_end - pd.offsets.BDay(HORIZON)

    train = features.loc[train_mask]
    validation = features.loc[val_mask]
    test = features.loc[test_mask]
    result: dict = {
        "protocol": {
            "source": str(path),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "date_start": str(dates.min().date()), "date_end": str(dates.max().date()),
            "train_end": TRAIN_END, "validation_end": VALIDATION_END,
            "test_start": str(test.index.min().date()), "test_end": str(test.index.max().date()),
            "horizon_sessions": HORIZON, "alert_budget_on_validation": ALERT_BUDGET,
            "split": "chronological; 20 business-day label purge at train/validation boundaries",
            "interpretation": "market-regime early warning, not DQ defect detection or trading advice",
            "features": list(features.columns),
            "limits": ["one asset in this first pilot", "test spans multiple regimes and calibration drift",
                       "overlapping forward labels; episode metrics are descriptive",
                       "event thresholds are fitted on train only; alert threshold on validation only"],
        },
        "targets": {},
    }

    for name, raw_target, direction, quantile in (
        ("high_volatility", targets["future_vol"], "above", 0.90),
        ("downside_tail", targets["future_return"], "below", 0.05),
    ):
        event_cut = float(raw_target.loc[train_mask].quantile(quantile))
        y = (raw_target > event_cut if direction == "above" else raw_target < event_cut).astype(int)
        y_train, y_val, y_test = y.loc[train_mask].to_numpy(), y.loc[val_mask].to_numpy(), y.loc[test_mask].to_numpy()
        x_train, x_val, x_test = train, validation, test

        models: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        model = _fit_xgb(x_train, y_train)
        models["xgboost"] = (
            model.predict_proba(x_val)[:, 1], model.predict_proba(x_test)[:, 1]
        )

        if name == "high_volatility":
            baseline_scores = {
                "rolling_vol20": features["vol_20"],
                "volatility_acceleration": features["vol_ratio_20_90"],
            }
        else:
            baseline_scores = {
                "downside_vol20": features["downside_vol_20"],
                "negative_momentum20": -features["return_20"],
            }
        baseline_scores["variance_cusum"] = _cusum_score(
            ret, float(ret.loc[train_mask].pow(2).median()),
            allowance=float(np.log(2.0)),
        )
        for key, score in baseline_scores.items():
            models[key] = (
                score.loc[val_mask].to_numpy(), score.loc[test_mask].to_numpy()
            )

        by_method = {}
        for method, (val_score, test_score) in models.items():
            threshold = _alert_threshold(val_score)
            by_method[method] = {
                "threshold_validation": threshold,
                "validation_alert_rate": float(np.mean(val_score >= threshold)),
                "test": _evaluate(y_test, test_score, threshold),
            }
        result["targets"][name] = {
            "definition": (
                f"next-{HORIZON}-session annualized realized volatility > train q90"
                if direction == "above" else
                f"next-{HORIZON}-session cumulative log return < train q05"
            ),
            "train_event_threshold": event_cut,
            "n_train": int(train_mask.sum()), "n_validation": int(val_mask.sum()),
            "n_test": int(test_mask.sum()),
            "validation_prevalence": float(y_val.mean()),
            "test_prevalence": float(y_test.mean()),
            "methods": by_method,
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=ROOT / "data" / "brent_fred_daily.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "reports" / "regime_early_warning" / "summary.json")
    args = parser.parse_args()
    result = run(args.panel, args.output)
    for target, block in result["targets"].items():
        print(f"\n{target}: {block['definition']} · test {block['n_test']} sessions")
        for method, metrics in block["methods"].items():
            m = metrics["test"]
            print(f"  {method:28s} AP={m['average_precision']:.3f} AUC={m['roc_auc']:.3f} "
                  f"alert={m['alert_rate']:.3f} episode_recall={m['episode_recall']:.3f} "
                  f"lead={m['median_lead_sessions']:.1f}")
    print(f"\n-> {args.output}")


if __name__ == "__main__":
    main()
