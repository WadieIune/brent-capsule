from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np


MODULE = (Path(__file__).resolve().parents[1] / "code/applications/experiments"
          / "dq_yolo_volatility_spikes.py")
SPEC = spec_from_file_location("dq_yolo_volatility_spikes", MODULE)
dq = module_from_spec(SPEC)
SPEC.loader.exec_module(dq)


def test_spike_injection_is_local_and_reproducible():
    clean, _ = dq.sample_window(100)
    corrupt, location = dq.sample_window(100, 4.0)
    assert np.array_equal(clean, dq.sample_window(100)[0])
    assert np.count_nonzero(corrupt - clean) == 1
    assert corrupt[location] - clean[location] == 4.0


def test_causal_sigma_has_no_warmup_alerts():
    x, _ = dq.sample_window(101)
    score = dq.causal_3sigma_score(x)
    assert np.all(score[:32] == 0.0)
    assert np.isfinite(score).all()


def test_yolo_boxes_are_normalized_and_centered_on_spike(tmp_path):
    x, location = dq.sample_window(102, 3.0)
    dq.write_yolo_item(tmp_path, "test", 0, x, location)
    label = (tmp_path / "labels/test/000000.txt").read_text().split()
    assert int(label[0]) == 0
    xc, yc, width, height = map(float, label[1:])
    assert 0 < xc < 1 and 0 < yc < 1
    assert 0 < width < 1 and 0 < height < 1
