import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_conformal_gate.py")
SPEC = importlib.util.spec_from_file_location("dq_conformal_gate", MODULE_PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def _panel(rng, n=400, k=5):
    """Ventanas sintéticas con pares correlacionados, en el formato (n, tiempo, activo)."""
    common = rng.normal(0, 1, size=(n, 20, 1))
    idio = rng.normal(0, 0.4, size=(n, 20, k))
    return (common + idio).astype(np.float32)


def test_cross_asset_score_is_blind_to_rescaling_of_the_target():
    """Espacio nulo analítico: 1 - R² no cambia al reescalar la serie objetivo."""
    rng = np.random.default_rng(0)
    windows = _panel(rng, n=32)
    rescaled = np.stack([gate.inject_rescale(w, np.random.default_rng(i))
                         for i, w in enumerate(windows)])
    # La invariancia es exacta sobre los reales (y -> c·y reajusta beta y R² no cambia);
    # la tolerancia solo absorbe el error de `lstsq` sobre entradas float32.
    np.testing.assert_allclose(gate.score_cross_asset(windows),
                               gate.score_cross_asset(rescaled), rtol=1e-5, atol=1e-6)


def test_every_cheap_control_is_exactly_blind_to_a_sign_flip():
    """Los tres controles baratos son invariantes al signo de la serie objetivo.

    `1-R²` porque la regresión reajusta beta; 3σ y el ratio de volatilidad porque
    dependen de |·| y de la desviación típica. Es el espacio nulo que la CNN sí
    cubre (recall 0,998 frente a ~0,056 de azar en los tres).
    """
    rng = np.random.default_rng(23)
    windows = _panel(rng, n=48)
    flipped = np.stack([gate.inject_sign_flip(w, rng) for w in windows])
    for scorer in (gate.score_cross_asset, gate.score_3sigma,
                   gate.volatility_ratio_score):
        np.testing.assert_allclose(scorer(windows), scorer(flipped),
                                   rtol=1e-5, atol=1e-6)


def test_unseen_families_are_disjoint_from_the_trained_ones():
    """Ninguna familia no vista puede colarse en el entrenamiento de la CNN."""
    assert not set(gate.UNSEEN_FAMILIES) & set(gate.FAMILIES)


def test_every_unseen_injector_changes_only_the_target_series():
    rng = np.random.default_rng(29)
    window = _panel(rng, n=1)[0]
    for name, injector in gate.UNSEEN_FAMILIES.items():
        out = injector(window, np.random.default_rng(31))
        np.testing.assert_array_equal(out[:, 1:], window[:, 1:],
                                      err_msg=f"{name} tocó los pares")
        assert not np.allclose(out[:, 0], window[:, 0]), f"{name} no alteró el objetivo"


def test_lag1_is_a_one_session_shift_not_a_wider_decoupling():
    """`decoupling` usa desplazamientos de 2+; lag1 debe ser exactamente de 1."""
    rng = np.random.default_rng(37)
    window = _panel(rng, n=1)[0]
    out = gate.inject_lag1(window, rng)
    np.testing.assert_allclose(out[1:, 0], window[:-1, 0], rtol=1e-6)


def test_weekly_ffill_preserves_the_total_return_of_the_window():
    """El forward-fill redistribuye el movimiento, no lo crea ni lo destruye."""
    rng = np.random.default_rng(41)
    window = _panel(rng, n=1)[0]
    out = gate.inject_weekly_ffill(window, np.random.default_rng(43))
    assert np.count_nonzero(out[:, 0]) < len(out) // 2
    np.testing.assert_allclose(out[:, 0].sum(), window[:, 0].sum(), rtol=1e-4)


def test_rescale_injection_touches_only_the_target_series():
    rng = np.random.default_rng(3)
    window = _panel(rng, n=1)[0]
    out = gate.inject_rescale(window, np.random.default_rng(5))
    np.testing.assert_array_equal(out[:, 1:], window[:, 1:])
    assert not np.allclose(out[:, 0], window[:, 0])


def test_volatility_ratio_score_detects_rescaling():
    rng = np.random.default_rng(7)
    windows = _panel(rng, n=64)
    rescaled = np.stack([gate.inject_rescale(w, np.random.default_rng(100 + i))
                         for i, w in enumerate(windows)])
    assert (gate.volatility_ratio_score(rescaled).mean()
            > gate.volatility_ratio_score(windows).mean())


def test_aci_holds_the_false_alarm_budget_under_a_level_shift():
    """Un umbral congelado se descalibra con deriva; ACI vuelve al objetivo."""
    rng = np.random.default_rng(11)
    calibration = rng.normal(0, 1, size=400)
    drifted = rng.normal(1.5, 1, size=600)          # deriva de nivel en el flujo limpio
    frozen = float(np.quantile(calibration, 0.95))
    frozen_fpr = float(np.mean(drifted > frozen))
    aci_fpr = float(np.mean(gate.aci_flags(calibration, drifted, drifted, target=0.05)))
    assert frozen_fpr > 0.30                        # el congelado se dispara
    assert abs(aci_fpr - 0.05) < 0.03               # el adaptativo se mantiene


def test_aci_is_causal_in_the_evaluated_stream():
    """El futuro del flujo evaluado no puede cambiar las alertas ya emitidas."""
    rng = np.random.default_rng(13)
    calibration = rng.normal(0, 1, size=200)
    clean = rng.normal(0, 1, size=100)
    evaluated = rng.normal(0, 1, size=100)
    first = gate.aci_flags(calibration, clean, evaluated)
    altered = evaluated.copy()
    altered[60:] += 50.0
    second = gate.aci_flags(calibration, clean, altered)
    np.testing.assert_array_equal(first[:60], second[:60])


def test_aci_rejects_mismatched_stream_lengths():
    rng = np.random.default_rng(17)
    try:
        gate.aci_flags(rng.normal(size=50), rng.normal(size=10), rng.normal(size=11))
    except ValueError:
        return
    raise AssertionError("se esperaba ValueError por longitudes distintas")


def test_matched_fpr_recall_imposes_the_budget_on_clean_data():
    rng = np.random.default_rng(19)
    clean = rng.normal(0, 1, size=(2000, 20, 5)).astype(np.float32)
    scorer = gate.score_3sigma
    recall_on_clean = gate.matched_fpr_recall(scorer, clean, clean, target=0.05)
    assert abs(recall_on_clean - 0.05) < 0.01
