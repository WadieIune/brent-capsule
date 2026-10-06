import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "applications" / "experiments" / "wprd1_multiactive_policy.py"
SPEC = importlib.util.spec_from_file_location("wprd1_multiactive_policy", MODULE_PATH)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def test_panel_preserves_negative_wti_and_joint_trading_dates(tmp_path):
    dates = pd.bdate_range("2020-04-16", periods=4)
    data = {"date": dates}
    for asset in policy.ASSETS:
        data[asset] = [10.0, 11.0, 12.0, 13.0]
    data["WTI"] = [20.0, 18.0, -37.63, 10.0]
    path = tmp_path / "panel.csv"
    pd.DataFrame(data).to_csv(path, index=False)
    prices, diag = policy.load_panel(path)
    assert len(prices) == 4
    assert prices["WTI"].min() == -37.63
    assert diag["nonpositive_prices"]["WTI"][0]["date"] == "2020-04-20"


def test_wti_survival_feature_universe_is_fixed_across_folds():
    assert not policy.survival_feature_eligible("WTI")
    assert policy.survival_feature_eligible("BRENT")


def test_forward_loss_label_uses_only_future_sessions():
    forward = policy._forward_sum(np.array([1.0, 2.0, -3.0, 4.0]), horizon=2)
    assert forward[0] == -1.0
    assert forward[1] == 1.0
    assert np.isnan(forward[-2:]).all()


def test_fhs_ewma_forecast_is_causal_and_tracks_tail_shift():
    rng = np.random.default_rng(4)
    pnl = rng.normal(0.0, 0.01, size=700)
    pnl[400:430] = rng.normal(-0.04, 0.02, size=30)
    score = policy.fhs_ewma_downside_score(pnl)
    assert np.isnan(score[269])
    assert np.isfinite(score[270:]).all()
    assert score[420] > np.median(score[300:390])
    changed_future = pnl.copy()
    changed_future[421:] *= 10.0
    rescored = policy.fhs_ewma_downside_score(changed_future)
    assert np.allclose(score[:421], rescored[:421], equal_nan=True)


def test_bootstrap_pairs_candidates_on_same_years():
    frame = pd.DataFrame([
        {"year": year, "model": model, "episode_recall": recall}
        for year, values in enumerate([(0.7, 0.5), (0.6, 0.5), (0.4, 0.3), (0.8, 0.7)])
        for model, recall in zip(("candidate", "fhs_ewma"), values)
    ])
    result = policy._bootstrap_recall_delta(frame, "candidate", "fhs_ewma", draws=100)
    assert result["n_years"] == 4
    assert np.isclose(result["delta_mean"], 0.125)
    assert result["ci95"][0] >= 0.0


def test_exposure_reduction_has_common_horizon_and_round_trip_cost():
    pnl = np.zeros(15)
    alerts = np.zeros(15, dtype=bool)
    alerts[2] = True
    result = policy._portfolio_policy(pnl, alerts, cost_bps=10)
    assert np.isclose(result["mean_exposure"], 2.0 / 3.0)
    assert result["turnover_units"] == 1.0
    assert result["net_cumulative_pnl_risk_units"] == -0.001
