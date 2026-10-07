import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import torch


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_cnn1d_supervised.py")
SPEC = importlib.util.spec_from_file_location("dq_cnn1d_supervised", MODULE_PATH)
dqcnn = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dqcnn)


def test_cnn_accepts_batch_of_multivariate_trailing_windows():
    model = dqcnn.DQConv1D(n_assets=5)
    score = model(torch.zeros((4, dqcnn.WINDOW, 5)))
    assert score.shape == (4,)


def test_decoupling_preserves_target_marginal_but_changes_alignment():
    window = np.arange(100, dtype=np.float32).reshape(20, 5)
    changed = dqcnn.inject(window, "decoupling", np.random.default_rng(3))
    np.testing.assert_array_equal(np.sort(changed[:, 0]), np.sort(window[:, 0]))
    assert not np.array_equal(changed[:, 0], window[:, 0])
    np.testing.assert_array_equal(changed[:, 1:], window[:, 1:])


def test_jump_injection_is_reversible_and_stale_is_zero():
    window = np.zeros((20, 5), dtype=np.float32)
    jump = dqcnn.inject(window, "reversible_jump", np.random.default_rng(1))
    assert np.isclose(jump[:, 0].sum(), 0.0)
    assert np.count_nonzero(jump[:, 0]) == 2
    stale = dqcnn.inject(np.ones((20, 5), dtype=np.float32), "stale",
                         np.random.default_rng(1))
    assert np.count_nonzero(stale[:, 0]) == 0


def test_alert_threshold_never_exceeds_target_fp_without_ties():
    scores = np.linspace(0, 1, 100)
    threshold = dqcnn.threshold_at_fp(scores, fp=0.05)
    assert np.mean(scores > threshold) == 0.05


def test_load_windows_preserves_negative_wti_settlement_as_dollar_change(tmp_path):
    dates = pd.date_range("2020-01-01", periods=90)
    frame = {"date": dates, "BRENT": np.linspace(50.0, 60.0, len(dates)),
             "WTI": np.linspace(45.0, 40.0, len(dates)),
             "DTWEXBGS": np.linspace(110.0, 105.0, len(dates)),
             "COPPER": np.linspace(2.5, 2.8, len(dates)),
             "EUROSTOXX50": np.linspace(3000.0, 3500.0, len(dates))}
    frame["WTI"][50] = -37.63
    path = tmp_path / "panel.csv"
    pd.DataFrame(frame).to_csv(path, index=False)
    windows, starts, ends, _ = dqcnn.load_windows(path)
    assert len(windows) > 0
    assert starts[0] < ends[0]
    assert np.isfinite(windows).all()
