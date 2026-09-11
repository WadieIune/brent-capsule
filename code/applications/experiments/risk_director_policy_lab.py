"""Offline policy lab for Risk Director signals.

This diagnostic evaluates whether forecasts rank future high-risk days well enough
to support review/hedging policies. It is not full reinforcement learning: no
counterfactual market simulator is assumed and no adaptive policy is trained on
the test period.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from harness import Experiment, ExperimentResult, RunContext  # noqa: E402
from experiments.risk_director_scientific_eval import _default_panel_path, run_evaluation  # noqa: E402


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_forecasts(panel_path: Path, out_dir: Path) -> Path:
    src = _repo_root() / "code" / "applications" / "outputs_scientific" / "risk_director_scientific_eval" / "forecasts.csv"
    if src.exists():
        return src
    tmp = out_dir / "scientific_source"
    run_evaluation(panel_path, tmp)
    return tmp / "forecasts.csv"


def _budget_policy(forecast: np.ndarray, budget: float) -> np.ndarray:
    thr = float(np.quantile(forecast, 1.0 - budget))
    return forecast >= thr


def _policy_metrics(y: np.ndarray, event: np.ndarray, alert: np.ndarray, hedge_effect: float, alert_cost: float) -> Dict[str, float]:
    # Proxy loss: alert reduces realized risk by hedge_effect but costs alert_cost.
    action = alert.astype(float)
    proxy_cost = y * (1.0 - hedge_effect * action) + alert_cost * action
    no_action_cost = y
    return {
        "alert_rate": float(action.mean()),
        "precision": float(event[alert].mean()) if alert.any() else float("nan"),
        "capture": float((event & alert).sum() / max(1, event.sum())),
        "mean_target_alert": float(y[alert].mean()) if alert.any() else float("nan"),
        "mean_target_rest": float(y[~alert].mean()) if (~alert).any() else float("nan"),
        "proxy_cost": float(proxy_cost.mean()),
        "proxy_cost_delta_vs_no_action": float(proxy_cost.mean() - no_action_cost.mean()),
    }


def run_policy_lab(forecasts_path: Path, out_dir: Path) -> Dict[str, object]:
    df = pd.read_csv(forecasts_path, parse_dates=["date"])
    y = df["target"].to_numpy(dtype=float)
    base = df["base"].to_numpy(dtype=float)
    external = df["external"].to_numpy(dtype=float)
    event_thr = float(np.quantile(y[df["date"] < pd.Timestamp("2026-01-01")], 0.90))
    if not np.isfinite(event_thr):
        event_thr = float(np.quantile(y, 0.90))
    event = y >= event_thr

    budgets = [0.05, 0.10, 0.20]
    hedge_effects = [0.25, 0.50]
    alert_costs = [event_thr * x for x in [0.02, 0.05, 0.10]]
    rows: List[Dict[str, object]] = []
    for budget in budgets:
        for model_name, forecast in [("base", base), ("external", external)]:
            alert = _budget_policy(forecast, budget)
            for hedge_effect in hedge_effects:
                for alert_cost in alert_costs:
                    met = _policy_metrics(y, event, alert, hedge_effect, alert_cost)
                    rows.append({
                        "model": model_name,
                        "budget": budget,
                        "hedge_effect": hedge_effect,
                        "alert_cost": alert_cost,
                        **met,
                    })
    out = pd.DataFrame(rows)
    comp = []
    for (budget, hedge_effect, alert_cost), g in out.groupby(["budget", "hedge_effect", "alert_cost"]):
        vals = {r["model"]: r for _, r in g.iterrows()}
        if "base" not in vals or "external" not in vals:
            continue
        comp.append({
            "budget": float(budget),
            "hedge_effect": float(hedge_effect),
            "alert_cost": float(alert_cost),
            "external_minus_base_proxy_cost": float(vals["external"]["proxy_cost"] - vals["base"]["proxy_cost"]),
            "external_minus_base_capture": float(vals["external"]["capture"] - vals["base"]["capture"]),
            "external_minus_base_precision": float(vals["external"]["precision"] - vals["base"]["precision"]),
        })
    comp_df = pd.DataFrame(comp)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / "policy_grid.csv", index=False)
    comp_df.to_csv(out_dir / "policy_comparison.csv", index=False)
    summary = {
        "status": "diagnostic_offline_policy_lab",
        "forecasts_path": str(forecasts_path),
        "n": int(len(df)),
        "event_threshold": event_thr,
        "event_rate": float(event.mean()),
        "best_external_advantage": float(comp_df["external_minus_base_proxy_cost"].min()) if len(comp_df) else float("nan"),
        "median_external_advantage": float(comp_df["external_minus_base_proxy_cost"].median()) if len(comp_df) else float("nan"),
        "share_cost_grids_external_better": float((comp_df["external_minus_base_proxy_cost"] < 0).mean()) if len(comp_df) else float("nan"),
        "max_capture_gain": float(comp_df["external_minus_base_capture"].max()) if len(comp_df) else float("nan"),
        "limitations": [
            "Diagnostic ranking/policy evaluation, not trained RL.",
            "Alert budgets are equalized ex post for sensitivity; deployable thresholds must be validation-frozen.",
            "Proxy cost is not business P&L; it needs exposure and hedge cost from the user.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


class RiskDirectorPolicyLabExperiment(Experiment):
    id = "risk_director_policy_lab"
    title = "Laboratorio offline de politicas Risk Director"

    def preflight(self, ctx: RunContext) -> List[str]:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        return [] if panel_path.exists() else [f"no existe panel_path={panel_path}"]

    def run(self, ctx: RunContext) -> ExperimentResult:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        out = Path(ctx.experiment_dir())
        forecasts = _ensure_forecasts(panel_path, out)
        summary = run_policy_lab(forecasts, out)
        return ExperimentResult(
            metrics={k: v for k, v in summary.items() if k != "limitations"},
            artifacts=[str(out / "summary.json"), str(out / "policy_grid.csv"), str(out / "policy_comparison.csv")],
            decision="review",
            notes="diagnostico offline; no es RL entrenado",
        )
