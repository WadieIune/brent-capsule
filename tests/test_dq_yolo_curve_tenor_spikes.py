import importlib.util
from pathlib import Path

import numpy as np
import torch


SCRIPT = (Path(__file__).resolve().parents[1] / "code/applications/experiments"
          / "dq_yolo_curve_tenor_spikes.py")
SPEC = importlib.util.spec_from_file_location("dq_yolo_curve_tenor_spikes", SCRIPT)
curve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(curve)


def test_curve_pair_and_injected_spike_are_finite_and_local():
    primary, reference = curve.curve_pair(11)
    changed, event = curve.inject_spike(primary, reference, 1.0,
                                        np.random.default_rng(4), index=15)
    assert changed.shape == (curve.N_TENORS,)
    np.testing.assert_array_equal(changed[:14], primary[:14])
    np.testing.assert_array_equal(changed[16:], primary[16:])
    assert event == (15, 15)
    assert abs((changed[15] - reference[15]) - (primary[15] - reference[15])) == 1


def test_numeric_cnn_outputs_per_tenor_and_render_writes_image(tmp_path):
    p, r = curve.curve_pair(12)
    model = curve.CurveCNN1D()
    features = torch.from_numpy(curve.numeric_features(p[None], r[None]))
    assert model(features).shape == (1, curve.N_TENORS)
    path = tmp_path / "curve.png"
    curve.render(p, r, path, (10, 10))
    assert path.exists() and path.stat().st_size > 0
    other = tmp_path / "curve_with_label.png"
    curve.render(p, r, other, None)
    assert path.read_bytes() == other.read_bytes()
