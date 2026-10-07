import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_daily_monitor.py")
SPEC = importlib.util.spec_from_file_location("dq_daily_monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


def test_trim_zero_return_rule_fires_once_at_twentieth_session():
    prices = np.array([100.0] * 23 + [101.0] + [101.0] * 20)
    positions = monitor.consecutive_zero_return_alert_positions(prices)
    assert positions.tolist() == [20, 43]


def test_trim_rule_rejects_invalid_threshold():
    with np.testing.assert_raises(ValueError):
        monitor.consecutive_zero_return_alert_positions(np.ones(5), threshold=0)


def test_three_sigma_uses_only_prior_returns():
    returns = np.r_[np.zeros(40), 0.1, np.zeros(5)]
    prices = 100.0 * np.exp(np.cumsum(returns))
    observed, flags = monitor.rolling_log_return_3sigma(prices, lookback=30, min_periods=20)
    assert observed[40] > 0.09
    assert flags[40]
    assert not flags[39]


def test_three_sigma_skips_nonpositive_price_transitions():
    returns, flags = monitor.rolling_log_return_3sigma(np.array([10.0, 0.0, 12.0]))
    assert np.isnan(returns[1:]).all()
    assert not flags.any()


def test_daily_alerts_labels_benchmark_and_trim_separately():
    prices = np.array([100.0] * 25)
    alerts = monitor.daily_alerts(prices, pd.bdate_range("2020-01-01", periods=25),
                                  "BRENT", k_sigma=4.0, tol_atr=2.0)
    trim = alerts[alerts["rule"] == "repetidos_consecutivos_20"]
    assert trim["date"].tolist() == [pd.Timestamp("2020-01-29")]
    assert trim["layer"].tolist() == ["trim"]
    assert alerts[alerts["rule"] == "retorno_3sigma_benchmark"].empty
