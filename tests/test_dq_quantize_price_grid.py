import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_quantize_price_grid.py")
SPEC = importlib.util.spec_from_file_location("dq_quantize_price_grid", MODULE_PATH)
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)


def _price_window(rng, n_rows=21, n_assets=5, tick=0.01):
    """Ventana de precios con el tick nativo de 0,01 que tiene el panel real."""
    level = 80.0 + np.cumsum(rng.normal(0, 1.0, size=(n_rows, n_assets)), axis=0)
    return np.round(level / tick) * tick


def test_grid_control_recovers_the_injected_truncation_step():
    rng = np.random.default_rng(0)
    window = _price_window(rng)
    assert q.grid_step_score(window[None, :, :])[0] == 0.01
    for step in q.INJECTED_STEPS:
        truncated = q.quantize_prices(window, 0, len(window), step)
        assert q.grid_step_score(truncated[None, :, :])[0] == step


def test_grid_control_ignores_peer_precision():
    """Mezclar los pares arruinaba el control: cada serie tiene su propio tick."""
    rng = np.random.default_rng(1)
    window = _price_window(rng)
    window[:, 1:] += rng.normal(0, 1e-3, size=window[:, 1:].shape)  # pares sin rejilla
    truncated = q.quantize_prices(window, 0, len(window), 0.50)
    assert q.grid_step_score(truncated[None, :, :])[0] == 0.50


def test_quantize_touches_only_the_target_and_only_in_range():
    rng = np.random.default_rng(2)
    window = _price_window(rng)
    out = q.quantize_prices(window, 5, 12, 0.50)
    np.testing.assert_array_equal(out[:, 1:], window[:, 1:])
    np.testing.assert_array_equal(out[:5, 0], window[:5, 0])
    np.testing.assert_array_equal(out[12:, 0], window[12:, 0])
    np.testing.assert_allclose(out[5:12, 0], 0.50 * np.round(window[5:12, 0] / 0.50))


def test_grid_control_separates_clean_from_truncated_without_false_alarms():
    """Separación perfecta, no un score constante que marque todo (checklist #6)."""
    rng = np.random.default_rng(3)
    clean = np.stack([_price_window(rng) for _ in range(40)])
    truncated = np.stack([q.quantize_prices(w, 0, len(w), 0.25) for w in clean])
    clean_scores = q.grid_step_score(clean)
    dirty_scores = q.grid_step_score(truncated)
    assert np.all(clean_scores == 0.01)
    assert np.all(dirty_scores == 0.25)
    threshold = np.quantile(clean_scores, 0.95)
    assert np.mean(clean_scores > threshold) == 0.0
    assert np.mean(dirty_scores > threshold) == 1.0


def test_normalize_matches_the_original_pipeline():
    """La tubería replicada debe coincidir con la de `dq_cnn1d_supervised`."""
    panel = Path(__file__).resolve().parents[1] / "data" / "panel_extendido_2026-09-09.csv"
    prices, _ = q.read_prices(panel)
    scaled = q.normalize(prices)
    windows, _, _, _ = q.base.load_windows(panel)
    bounds = q.window_bounds(scaled)
    assert len(bounds) == len(windows)
    rebuilt = np.asarray([scaled[a:b] for a, b in bounds], dtype=np.float32)
    np.testing.assert_allclose(rebuilt, windows, rtol=1e-5, atol=1e-6)
