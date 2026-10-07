import importlib.util
from pathlib import Path

import numpy as np
import torch


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_curve_cnn1d.py")
SPEC = importlib.util.spec_from_file_location("dq_curve_cnn1d", MODULE_PATH)
curve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(curve)


def test_curve_cnn_output_and_local_bump_shape_score():
    model = curve.CurveCNN1D()
    assert model(torch.zeros((3, 3))).shape == (3,)
    smooth = np.array([[20.0, 30.0, 35.0]])
    bumped = curve.inject_bump(smooth, 4.0, np.random.default_rng(1), node=1)
    assert curve.linear_shape_score(bumped)[0] > curve.linear_shape_score(smooth)[0]


def test_bump_is_local_and_exact_in_basis_points():
    smooth = np.zeros((2, 3))
    bumped = curve.inject_bump(smooth, 3.0, np.random.default_rng(1), node=1)
    np.testing.assert_array_equal(bumped[:, [0, 2]], smooth[:, [0, 2]])
    assert np.all(np.abs(bumped[:, 1]) == 3.0)


def test_three_sigma_node_score_is_causal():
    rng = np.random.default_rng(8)
    values = np.cumsum(rng.normal(0, 0.02, size=(120, 4)), axis=0)
    original = curve.three_sigma_node_score(values)
    changed = values.copy()
    changed[80:] += 100.0
    rescored = curve.three_sigma_node_score(changed)
    np.testing.assert_allclose(original[:80], rescored[:80], equal_nan=True)
