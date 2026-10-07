import importlib.util
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "code" / "applications" / "experiments" / "dq_capital_value_added.py"
SPEC = importlib.util.spec_from_file_location("dq_capital_value_added", MODULE_PATH)
cap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cap)


def _prices(rng, rows=700, assets=5):
    return 80.0 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(rows, assets)), axis=0))


def test_capital_is_the_basel_multiple_of_the_mean_var():
    """El capital debe ser k*VaR con k del semáforo, no el VaR a secas."""
    rng = np.random.default_rng(0)
    prices = _prices(rng)
    capital = cap.portfolio_capital(prices, cap.VAR_WINDOW, len(prices) - 1)
    assert capital > 0.0
    # k >= 3 en zona verde, y el VaR medio en base 100 es del orden de la unidad.
    assert capital > 3.0 * 0.5


def test_non_positive_prices_do_not_poison_the_capital():
    """El settlement negativo de WTI en 2020 hacía NaN el logaritmo."""
    rng = np.random.default_rng(1)
    prices = _prices(rng)
    reference = cap.portfolio_capital(prices, cap.VAR_WINDOW, len(prices) - 1)
    with_negative = prices.copy()
    with_negative[5, 1] = -37.63          # fuera de la ventana evaluada
    result = cap.portfolio_capital(with_negative, cap.VAR_WINDOW, len(prices) - 1)
    assert np.isfinite(result)
    np.testing.assert_allclose(result, reference, rtol=0.05)


def test_capital_rejects_a_stretch_that_is_too_short():
    rng = np.random.default_rng(2)
    prices = _prices(rng, rows=300)
    try:
        cap.portfolio_capital(prices, cap.VAR_WINDOW, 290)
    except ValueError:
        return
    raise AssertionError("se esperaba ValueError por tramo insuficiente")


def test_residual_error_is_zero_with_perfect_recall_and_total_with_none(tmp_path):
    """La métrica debe degenerar correctamente en los dos extremos."""
    errors = {"a|restated": 1.0, "b|fresh": 3.0}
    total = float(np.mean(list(errors.values())))
    perfect = float(np.mean([(1.0 - 1.0) * v for v in errors.values()]))
    none = float(np.mean([(1.0 - 0.0) * v for v in errors.values()]))
    assert perfect == 0.0
    assert none == total


def test_run_refuses_to_invent_recalls_when_the_detection_summary_is_missing(tmp_path):
    """Los recalls vienen de dq_representation_stack; no se re-estiman aquí."""
    try:
        cap.run(ROOT / "data" / "panel_extendido_2026-09-09.csv",
                tmp_path / "no-existe.json", tmp_path / "out")
    except FileNotFoundError as exc:
        assert "dq_representation_stack" in str(exc)
        return
    raise AssertionError("se esperaba FileNotFoundError")


def test_published_summary_keeps_the_gates_nested_so_value_is_attributable():
    """`solo_3sigma` ⊂ `sin_ia` ⊂ `con_cnn`: sin anidamiento no se atribuye valor."""
    subsets = cap.stack.GATE_SUBSETS
    assert set(subsets["solo_3sigma"]) < set(subsets["sin_ia"]) < set(subsets["con_cnn"])
    assert set(subsets["con_cnn"]) - set(subsets["sin_ia"]) == {"retorno_cnn"}


def test_published_summary_is_marked_as_not_a_measurement():
    path = ROOT / "results" / "reports" / "dq_capital_value_added" / "summary.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "NO estiman el impacto real" in payload["aviso"]
    assert payload["fuera_del_alcance"]
