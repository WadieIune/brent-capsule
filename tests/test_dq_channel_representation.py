import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_channel_representation.py")
SPEC = importlib.util.spec_from_file_location("dq_channel_representation", MODULE_PATH)
ch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ch)


def _prices(rng, n_rows=21, n_assets=5):
    common = np.cumsum(rng.normal(0, 0.8, size=(n_rows, 1)), axis=0)
    idio = np.cumsum(rng.normal(0, 0.3, size=(n_rows, n_assets)), axis=0)
    return 80.0 + common + idio


def test_band_position_is_invariant_to_level_and_trend():
    """La posición dentro de banda debe aislar la forma: ni nivel ni pendiente.

    Es lo que hace del canal una representación distinta del precio crudo.
    """
    rng = np.random.default_rng(0)
    window = _prices(rng)[None, :, :]
    shifted = window + 25.0
    trended = window + np.arange(window.shape[1])[None, :, None] * 0.7
    base = ch.band_position(window)
    np.testing.assert_allclose(base, ch.band_position(shifted), atol=1e-8)
    np.testing.assert_allclose(base, ch.band_position(trended), atol=1e-8)


def test_band_position_is_invariant_to_scale():
    rng = np.random.default_rng(1)
    window = _prices(rng)[None, :, :]
    np.testing.assert_allclose(ch.band_position(window),
                               ch.band_position(window * 3.0), atol=1e-8)


def test_oscillation_deficit_fires_on_a_series_that_stopped_moving():
    """Una serie estancada o propagada deja de girar; eso es lo que mide."""
    rng = np.random.default_rng(2)
    prices = _prices(rng, n_rows=60)
    alive = ch.channel_oscillation_score(prices[None, :, :])[0]
    stale = ch.channel_oscillation_score(
        ch.p_stale(prices, 0, len(prices), rng)[None, :, :])[0]
    ffill = ch.channel_oscillation_score(
        ch.p_weekly_ffill(prices, 0, len(prices), rng)[None, :, :])[0]
    assert stale > alive
    assert ffill > alive


def test_geometry_shift_fires_on_a_mid_window_source_switch():
    rng = np.random.default_rng(3)
    prices = _prices(rng, n_rows=40)
    clean = ch.channel_geometry_shift_score(prices[None, :, :])[0]
    switched = ch.p_source_switch(prices, 0, len(prices),
                                  np.random.default_rng(4))[None, :, :]
    assert ch.channel_geometry_shift_score(switched)[0] > clean


def test_every_price_injection_touches_only_the_target_and_only_in_range():
    rng = np.random.default_rng(5)
    prices = _prices(rng, n_rows=40)
    for name, injector in ch.PRICE_FAMILIES.items():
        out = injector(prices, 10, 30, np.random.default_rng(6))
        np.testing.assert_array_equal(out[:, 1:], prices[:, 1:],
                                      err_msg=f"{name} tocó los pares")
        np.testing.assert_array_equal(out[:10, 0], prices[:10, 0],
                                      err_msg=f"{name} tocó antes del tramo")
        np.testing.assert_array_equal(out[30:, 0], prices[30:, 0],
                                      err_msg=f"{name} tocó después del tramo")
        assert not np.allclose(out[10:30, 0], prices[10:30, 0]), f"{name} no alteró nada"


def test_stale_injection_really_flatlines_the_price():
    rng = np.random.default_rng(7)
    prices = _prices(rng, n_rows=40)
    out = ch.p_stale(prices, 10, 30, rng)
    assert len(np.unique(out[10:30, 0])) == 1


def test_weekly_ffill_leaves_at_most_one_move_per_five_sessions():
    rng = np.random.default_rng(8)
    prices = _prices(rng, n_rows=40)
    out = ch.p_weekly_ffill(prices, 0, 40, np.random.default_rng(9))
    moves = np.count_nonzero(np.diff(out[:, 0]))
    assert moves <= 40 // 5 + 1


def test_channel_coherence_separates_a_decoupled_target():
    """El desacople rompe la co-movimiento de posiciones dentro de banda."""
    rng = np.random.default_rng(10)
    windows = np.stack([_prices(rng) for _ in range(40)])
    decoupled = np.stack([ch.p_decoupling(w, 0, len(w), np.random.default_rng(11 + i))
                          for i, w in enumerate(windows)])
    assert (ch.channel_coherence_score(decoupled).mean()
            > ch.channel_coherence_score(windows).mean())
