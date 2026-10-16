import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_rolling_return_channel.py")
SPEC = importlib.util.spec_from_file_location("dq_rolling_return_channel", MODULE_PATH)
dq = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dq)


def _prices(n=180, seed=8):
    rng = np.random.default_rng(seed)
    out = np.empty((n, len(dq.base.ASSETS)))
    for j, asset in enumerate(dq.base.ASSETS):
        changes = rng.normal(0, 0.5 if asset == "WTI" else 0.01, n)
        if asset == "WTI":
            out[:, j] = 35 + np.cumsum(changes)
        else:
            out[:, j] = 100 * np.exp(np.cumsum(changes))
    return out


def test_returns_use_log_changes_and_wti_dollar_changes():
    prices = _prices(25)[None, ...]
    actual = dq.returns_from_prices(prices)[0]
    wti = dq.base.ASSETS.index("WTI")
    for j, asset in enumerate(dq.base.ASSETS):
        expected = (np.diff(prices[0, :, j]) if asset == "WTI" else
                    np.diff(np.log(prices[0, :, j])))
        np.testing.assert_allclose(actual[:, j], expected)
    assert actual.shape == (1, 24, len(dq.base.ASSETS))[1:]
    assert np.isfinite(actual[:, wti]).all()


def test_cumulative_return_path_is_rebased_and_cumulative():
    returns = np.arange(2 * 4 * 3, dtype=float).reshape(2, 4, 3) / 10
    path = dq.cumulative_return_path(returns)
    assert path.shape == (2, 5, 3)
    np.testing.assert_array_equal(path[:, 0], 0)
    np.testing.assert_allclose(np.diff(path, axis=1), returns)


def test_unmodified_window_normalization_matches_production_pipeline():
    prices = _prices()
    expected = dq.pricelab.normalize(prices)[80:100]
    actual = dq.normalize_corrupted_window(prices, 80, 100, prices[80:101])
    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)


def test_price_scale_does_not_change_log_return_representations():
    prices = _prices(30)[None, ...]
    multipliers = np.array([2.0 if asset != "WTI" else 1.0
                            for asset in dq.base.ASSETS])
    scaled = prices * multipliers[None, None, :]
    np.testing.assert_allclose(dq.returns_from_prices(prices),
                               dq.returns_from_prices(scaled), atol=1e-12)


def test_rolling_threshold_is_causal_and_non_alert_policy_excludes_alerts():
    initial = np.arange(1, 6, dtype=float)
    stream = np.array([100.0, 3.0])
    all_past = dq.rolling_thresholds(initial, stream, target=0.2, window=5)
    non_alerts = dq.rolling_thresholds(
        initial, stream, target=0.2, window=5, update_accepted_only=True)
    initial_threshold = dq.gate.calibration_threshold(initial, target=0.2)
    assert all_past[0] == initial_threshold
    assert non_alerts[0] == initial_threshold
    assert all_past[1] > initial_threshold
    assert non_alerts[1] == initial_threshold
