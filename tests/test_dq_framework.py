import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "applications" / "dq_framework.py"
SPEC = importlib.util.spec_from_file_location("dq_framework", MODULE_PATH)
dq = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dq
SPEC.loader.exec_module(dq)


def _dates(n):
    return pd.bdate_range("2024-01-01", periods=n)


def test_log_returns_for_positive_prices_and_differences_for_signed_prices():
    prices = np.array([100.0, 110.0, 99.0])
    log_r = dq.transform_returns(prices, "positive_price")
    np.testing.assert_allclose(log_r[1:], np.log([1.1, 0.9]))

    signed = np.array([2.0, 0.0, -3.0])
    diff = dq.transform_returns(signed, "signed_price")
    np.testing.assert_array_equal(diff[1:], [-2.0, -3.0])


def test_return_scores_do_not_use_future_observations():
    rng = np.random.default_rng(12)
    returns = rng.normal(size=120)
    z1, h1 = dq.causal_return_scores(returns, lookback=30, min_history=10)
    extended = np.r_[returns, 1000.0]
    z2, h2 = dq.causal_return_scores(extended, lookback=30, min_history=10)
    np.testing.assert_allclose(z1, z2[:len(returns)], equal_nan=True)
    np.testing.assert_allclose(h1, h2[:len(returns)], equal_nan=True)


def test_trim_fires_on_twentieth_zero_return_and_can_be_whitelisted():
    prices = np.r_[100.0, np.repeat(100.0, 20)]
    contract = dq.SeriesContract("BRENT", "positive_price", "USD/bbl")
    report = dq.analyze_series(prices, _dates(len(prices)), contract)
    trim = [a for a in report.alerts if a.rule == "trim_zero_return_run"]
    assert len(trim) == 1
    assert trim[0].timestamp == _dates(len(prices))[20]
    assert trim[0].evidence["run_length"] == 20

    whitelisted = dq.SeriesContract("DFF", "rate", "percent", zero_run_is_expected=True)
    report = dq.analyze_series(prices, _dates(len(prices)), whitelisted)
    assert not any(a.rule in {"trim_zero_return_run", "repeated_price_run"}
                   for a in report.alerts)


def test_signed_negative_price_is_not_flagged_as_invalid_or_logged():
    values = np.array([2.0, 1.0, 0.0, -1.0, -1.0])
    contract = dq.SeriesContract("WTI", "signed_price", "USD/bbl")
    report = dq.analyze_series(values, _dates(len(values)), contract)
    assert not any(a.rule == "nonpositive_value" for a in report.alerts)
    assert report.returns[3] == -1.0
    assert report.returns[4] == 0.0


def test_context_and_model_scores_enter_layer_two_with_evidence():
    values = 100.0 * np.exp(np.cumsum(np.r_[0.0, np.zeros(24)]))
    dates = _dates(len(values))
    contract = dq.SeriesContract("BRENT", "positive_price", "USD/bbl")
    context = np.zeros(len(values))
    cnn = np.zeros(len(values))
    context[10] = 0.8
    cnn[12] = 0.9
    report = dq.analyze_series(
        values, dates, contract,
        context_scores={"channel_survival": (context, 0.5)},
        model_scores={"cnn_1d": (cnn, 0.7)},
    )
    alerts = {a.rule: a for a in report.alerts if a.layer == "intelligent"}
    assert alerts["context:channel_survival"].timestamp == dates[10]
    assert alerts["model:cnn_1d"].timestamp == dates[12]
    assert alerts["model:cnn_1d"].disposition == "review"


def test_model_scores_must_align_to_observation_timestamps():
    contract = dq.SeriesContract("BRENT", "positive_price", "USD/bbl")
    with np.testing.assert_raises(ValueError):
        dq.analyze_series(np.array([100.0, 101.0]), _dates(2), contract,
                          model_scores={"cnn": (np.zeros(1), 0.5)})


def test_duplicate_timestamps_are_flagged_even_when_dates_are_sorted():
    dates = pd.DatetimeIndex(["2024-01-01", "2024-01-01", "2024-01-02"])
    contract = dq.SeriesContract("BRENT", "positive_price", "USD/bbl")
    report = dq.analyze_series(np.array([100.0, 101.0, 102.0]), dates, contract)
    alerts = [a for a in report.alerts if a.rule == "duplicate_timestamp"]
    assert len(alerts) == 1
    assert alerts[0].timestamp == dates[1]
