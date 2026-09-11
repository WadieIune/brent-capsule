"""Scientific evaluation for the CNN-info-Risk Director chain.

This first confirmatory-style battery evaluates whether external information in
the extended panel improves ten-observation forward Brent risk forecasts over
EWMA/HAR controls. CNN scores are not re-used here; the prior CNN bridge remains
provisional and is connected in the report as the next representation block.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from harness import Experiment, ExperimentResult, RunContext  # noqa: E402

HORIZON = 10
EXT_COLS = [
    "WTI", "SPREAD_WTI_BRENT", "RATIO_WTI_BRENT", "VIX", "DTWEXBGS",
    "DGS2", "DGS10", "DGS30", "SPREAD_US10Y_US2Y", "DFF", "SOFR",
    "NATGAS", "GOLD", "SILVER", "COPPER", "SP500", "DAX", "EUROSTOXX50",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_panel_path() -> Path:
    return _repo_root() / "data" / "panel_extendido_2026-09-09.csv"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qlike(y: np.ndarray, f: np.ndarray) -> np.ndarray:
    f = np.maximum(np.asarray(f, dtype=float), 1e-12)
    y = np.maximum(np.asarray(y, dtype=float), 0.0)
    return np.log(f) + y / f


def block_interval(values: np.ndarray, block: int, reps: int = 2000, seed: int = 1729) -> List[float]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < block + 1:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(reps):
        starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
        idx = (starts[:, None] + np.arange(block)).ravel()[:n]
        means.append(float(np.mean(v[idx])))
    return [float(x) for x in np.quantile(means, [0.025, 0.975])]


def build_frame(panel_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(panel_path, parse_dates=["date"]).sort_values("date")
    panel = raw.set_index("date")
    brent = pd.to_numeric(panel["BRENT"], errors="coerce").dropna()
    if (brent <= 0).any():
        raise ValueError("BRENT must be positive")
    r = np.log(brent).diff()
    r2 = r.pow(2)
    f = pd.DataFrame(index=brent.index)
    f["target"] = sum(r2.shift(-j) for j in range(1, HORIZON + 1)) / HORIZON
    f["label_end"] = pd.Series(brent.index, index=brent.index).shift(-HORIZON)
    f["ewma"] = r2.ewm(alpha=0.06, adjust=False).mean()
    f["rv1"] = r2.rolling(1).mean()
    f["rv5"] = r2.rolling(5).mean()
    f["rv22"] = r2.rolling(22).mean()
    f["ret5"] = np.log(brent).diff(5)
    f["ret20"] = np.log(brent).diff(20)
    f["vol20"] = r.rolling(20).std() * np.sqrt(252)

    # As-of external features: last observed value at or before Brent date plus age.
    for col in EXT_COLS:
        if col not in panel.columns:
            continue
        s0 = pd.to_numeric(panel[col], errors="coerce")
        last_date = pd.Series(panel.index.where(s0.notna()), index=panel.index).ffill()
        s = s0.ffill().reindex(f.index).ffill()
        d = pd.Series(last_date, index=panel.index).reindex(f.index).ffill()
        age = [(idx.date() - val.date()).days if pd.notna(val) else np.nan for idx, val in d.items()]
        f[f"x_{col}_level"] = s
        f[f"x_{col}_chg5"] = np.log(s).diff(5) if (s.dropna() > 0).all() else s.diff(5)
        f[f"x_{col}_age"] = age
    return f.dropna(subset=["target", "label_end", "ewma", "rv1", "rv5", "rv22"])


def _base_design(df: pd.DataFrame, family: str) -> Tuple[np.ndarray, np.ndarray]:
    floor = 1e-12
    if family == "EWMA":
        offset = np.log(df["ewma"].clip(lower=floor).to_numpy())
        x = np.empty((len(df), 0))
    elif family == "HAR":
        offset = np.log(df["rv22"].clip(lower=floor).to_numpy())
        x = np.column_stack([
            np.log(df["rv1"].clip(lower=floor).to_numpy()) - offset,
            np.log(df["rv5"].clip(lower=floor).to_numpy()) - offset,
        ])
    else:
        raise ValueError(f"unknown family {family}")
    return offset, x


def _safe_matrix(df: pd.DataFrame, cols: Iterable[str]) -> np.ndarray:
    arr = df[list(cols)].to_numpy(dtype=float)
    return arr


def predict(train: pd.DataFrame, test: pd.DataFrame, family: str, extra_cols: List[str]) -> np.ndarray:
    off, x0 = _base_design(train, family)
    off_t, xt0 = _base_design(test, family)
    if extra_cols:
        x = np.column_stack([x0, _safe_matrix(train, extra_cols)])
        xt = np.column_stack([xt0, _safe_matrix(test, extra_cols)])
    else:
        x, xt = x0, xt0
    if x.shape[1]:
        mu = np.nanmean(x, axis=0)
        sd = np.nanstd(x, axis=0)
        sd = np.maximum(sd, 1e-8)
        x = np.nan_to_num((x - mu) / sd, nan=0.0, posinf=0.0, neginf=0.0)
        xt = np.nan_to_num((xt - mu) / sd, nan=0.0, posinf=0.0, neginf=0.0)
        x = np.column_stack([np.ones(len(x)), x])
        xt = np.column_stack([np.ones(len(xt)), xt])
    else:
        x = np.ones((len(train), 1))
        xt = np.ones((len(test), 1))
    y = train["target"].to_numpy(dtype=float)

    ridge = 0.05 if extra_cols else 0.01

    def objective(b: np.ndarray) -> Tuple[float, np.ndarray]:
        eta = off + x @ b
        ratio = y * np.exp(-eta)
        val = float(np.mean(eta + ratio) + ridge * np.dot(b[1:], b[1:]) / 2.0)
        grad = x.T @ (1.0 - ratio) / len(y)
        grad[1:] += ridge * b[1:]
        return val, grad

    fit = minimize(objective, np.zeros(x.shape[1]), jac=True, method="L-BFGS-B")
    if not fit.success:
        raise RuntimeError(str(fit.message))
    return np.exp(off_t + xt @ fit.x)


def event_metrics(y: np.ndarray, base: np.ndarray, challenger: np.ndarray, train_y: np.ndarray) -> Dict[str, object]:
    event_thr = float(np.quantile(train_y, 0.90))
    alert_base_thr = float(np.quantile(base, 0.90))
    alert_ch_thr = float(np.quantile(challenger, 0.90))
    event = y >= event_thr
    out: Dict[str, object] = {"event_threshold_train_q90": event_thr, "event_rate": float(event.mean())}
    for name, forecast, thr in [("base", base, alert_base_thr), ("external", challenger, alert_ch_thr)]:
        alert = forecast >= thr
        tp = float(np.mean(alert & event))
        out[f"{name}_alert_rate"] = float(alert.mean())
        out[f"{name}_precision"] = float(event[alert].mean()) if alert.any() else float("nan")
        out[f"{name}_capture"] = float((alert & event).sum() / max(1, event.sum()))
        out[f"{name}_avg_target_alert_over_rest"] = float(np.mean(y[alert]) / np.mean(y[~alert])) if alert.any() and (~alert).any() else float("nan")
        out[f"{name}_joint_event_alert_rate"] = tp
    return out


def run_evaluation(panel_path: Path, out_dir: Path) -> Dict[str, object]:
    f = build_frame(panel_path)
    extra_cols = [c for c in f.columns if c.startswith("x_")]
    records: List[pd.DataFrame] = []
    folds: List[Dict[str, object]] = []
    for year in range(2016, int(f.index.max().year) + 1):
        test = f[f.index.year == year]
        if len(test) < 30:
            continue
        start = test.index.min()
        available = f[(f.index < start) & (f["label_end"] < start)]
        available = available.dropna(subset=extra_cols)
        valid = available.iloc[-252:]
        train = available[available["label_end"] < valid.index.min()]
        if len(train) < 1000 or len(valid) < 100:
            continue
        scores = {}
        for fam in ["EWMA", "HAR"]:
            scores[fam] = float(np.mean(qlike(valid["target"].to_numpy(), predict(train, valid, fam, []))))
        selected = min(scores, key=scores.get)
        fit_train = available
        base = predict(fit_train, test.dropna(subset=[]), selected, [])
        # Test rows need external features for the external model.
        test_ext = test.dropna(subset=extra_cols)
        base_ext = predict(fit_train, test_ext, selected, [])
        ext = predict(fit_train, test_ext, selected, extra_cols)
        row = pd.DataFrame({
            "date": test_ext.index,
            "year": year,
            "target": test_ext["target"].to_numpy(dtype=float),
            "label_end": test_ext["label_end"].astype(str).to_numpy(),
            "selected": selected,
            "base": base_ext,
            "external": ext,
        })
        row["delta_qlike_external_minus_base"] = qlike(row["target"].to_numpy(), row["external"].to_numpy()) - qlike(row["target"].to_numpy(), row["base"].to_numpy())
        records.append(row)
        folds.append({
            "year": year,
            "selected": selected,
            "validation_qlike": scores,
            "train_n": int(len(train)),
            "validation_n": int(len(valid)),
            "test_n": int(len(test_ext)),
            "test_start": str(start.date()),
            "refit_end_label": str(available["label_end"].max().date()),
            "purged_before_test": int(((f.index < start) & (f["label_end"] >= start)).sum()),
        })
    if not records:
        raise RuntimeError("no folds produced")
    forecasts = pd.concat(records, ignore_index=True)
    d = forecasts["delta_qlike_external_minus_base"].to_numpy(dtype=float)
    train_targets = f[f.index < pd.Timestamp("2016-01-01")]["target"].dropna().to_numpy(dtype=float)
    ev = event_metrics(
        forecasts["target"].to_numpy(dtype=float),
        forecasts["base"].to_numpy(dtype=float),
        forecasts["external"].to_numpy(dtype=float),
        train_targets,
    )
    annual = forecasts.groupby("year").agg(
        n=("target", "size"),
        delta_qlike_external_minus_base=("delta_qlike_external_minus_base", "mean"),
        mean_target=("target", "mean"),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    forecasts.to_csv(out_dir / "forecasts.csv", index=False)
    annual.to_csv(out_dir / "per_year.csv")
    summary = {
        "status": "provisional_scientific_battery",
        "panel_path": str(panel_path),
        "panel_sha256": _sha256(panel_path),
        "n_forecasts": int(len(forecasts)),
        "date_min": str(pd.to_datetime(forecasts["date"]).min().date()),
        "date_max": str(pd.to_datetime(forecasts["date"]).max().date()),
        "delta_qlike_external_minus_base": float(np.mean(d)),
        "block_ci_95": {str(b): block_interval(d, b) for b in [10, 20, 60]},
        "event_metrics": ev,
        "folds": folds,
        "limitations": [
            "First battery for external information; CNN representation is evaluated separately.",
            "External panel is dated by observation; per-variable publication lags still need policy delays.",
            "No hyperparameter search beyond fixed ridge log-QLIKE bridge.",
            "Close-to-close squared returns are noisy proxies of realized variance.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


class RiskDirectorScientificEvalExperiment(Experiment):
    id = "risk_director_scientific_eval"
    title = "Evaluacion cientifica: informacion externa sobre riesgo Brent a 10 sesiones"

    def preflight(self, ctx: RunContext) -> List[str]:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        return [] if panel_path.exists() else [f"no existe panel_path={panel_path}"]

    def run(self, ctx: RunContext) -> ExperimentResult:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        out = Path(ctx.experiment_dir())
        summary = run_evaluation(panel_path, out)
        return ExperimentResult(
            metrics={k: v for k, v in summary.items() if k not in {"folds", "limitations"}},
            artifacts=[str(out / "summary.json"), str(out / "forecasts.csv"), str(out / "per_year.csv")],
            decision="review",
            notes=f"delta QLIKE externo-base={summary['delta_qlike_external_minus_base']:.6f}; pendiente challenge",
        )
