import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "code" / "applications" / "experiments" / "dq_representation_stack.py"
SPEC = importlib.util.spec_from_file_location("dq_representation_stack", MODULE_PATH)
stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stack)

PANEL = ROOT / "data" / "panel_extendido_2026-09-09.csv"


def test_local_renormalization_matches_the_full_series_pipeline():
    """La renormalización local es la optimización que hace viable el experimento.

    Si se desvía de `pricelab.normalize`, todas las features de retorno quedan
    medidas sobre otra tubería que la de los experimentos previos.
    """
    prices, _ = stack.pricelab.read_prices(PANEL)
    full = stack.pricelab.normalize(prices)
    bounds = stack.pricelab.window_bounds(full)
    for a, b in bounds[::97]:
        np.testing.assert_allclose(stack.normalize_target_window(prices, a, b),
                                   full[a:b, 0], rtol=1e-9, atol=1e-11)


def test_vintage_is_zero_when_nothing_was_restated():
    rng = np.random.default_rng(0)
    windows = 80.0 + np.cumsum(rng.normal(0, 1, size=(16, 21, 5)), axis=1)
    np.testing.assert_allclose(stack.vintage_discrepancy(windows, windows), 0.0, atol=1e-12)


def test_vintage_sees_a_restatement_and_ignores_the_unseen_tail():
    """Solo se compara el solape: la cola posterior al snapshot no existía."""
    rng = np.random.default_rng(1)
    stored = 80.0 + np.cumsum(rng.normal(0, 1, size=(1, 21, 5)), axis=1)
    restated = stored.copy()
    restated[0, 3, 0] *= 1.05                      # dentro del solape
    assert stack.vintage_discrepancy(restated, stored)[0] > 0.04
    fresh = stored.copy()
    fresh[0, -1, 0] *= 1.05                        # en la cola no comparable
    np.testing.assert_allclose(stack.vintage_discrepancy(fresh, stored), 0.0, atol=1e-12)


def test_vintage_rejects_a_snapshot_without_overlap():
    rng = np.random.default_rng(2)
    windows = 80.0 + np.cumsum(rng.normal(0, 1, size=(2, 4, 5)), axis=1)
    try:
        stack.vintage_discrepancy(windows, windows, lag=4)
    except ValueError:
        return
    raise AssertionError("se esperaba ValueError sin solape que comparar")


def test_fresh_mode_only_corrupts_the_sessions_after_the_snapshot():
    """Es lo que hace a vintage ciego en `fresh`; si no, el modo no significa nada."""
    prices, _ = stack.pricelab.read_prices(PANEL)
    a, b = 300, 320
    rng = np.random.default_rng(3)
    for family in stack.channel.PRICE_FAMILIES:
        corrupted, stored = stack._inject(prices, a, b, family, "fresh", rng)
        window = corrupted[a:b + 1]
        untouched = window.shape[0] - stack.SNAPSHOT_LAG
        np.testing.assert_allclose(window[:untouched, 0], stored[:untouched, 0],
                                   rtol=1e-12, err_msg=f"{family} tocó el solape")


def test_extract_returns_one_column_per_declared_feature():
    rng = np.random.default_rng(4)
    prices = 80.0 + np.cumsum(rng.normal(0, 1, size=(8, 21, 5)), axis=1)
    z = rng.normal(0, 1, size=(8, 20, 5)).astype(np.float32)
    cnn = stack.base.DQConv1D(5).eval()
    matrix = stack.extract(prices, prices, z, cnn)
    assert matrix.shape == (8, len(stack.FEATURES))
    assert np.isfinite(matrix).all()
