import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_channel_confirmatory.py")
SPEC = importlib.util.spec_from_file_location("dq_channel_confirmatory", MODULE_PATH)
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


def test_threshold_uses_validation_scores_with_finite_sample_rank():
    # At n=20 and 5% FPR, one validation exceedance is allowed.
    assert study.calibration_threshold(np.arange(20), fpr=0.05) == 18.0


def test_threshold_rejects_empty_finite_validation_sample():
    with np.testing.assert_raises(ValueError):
        study.calibration_threshold(np.array([np.nan, np.inf]))


def test_zero_alerts_still_has_nonzero_exact_upper_bound():
    lower, upper = study.exact_binomial_interval(0, 71)
    assert lower == 0.0
    assert 0.05 < upper < 0.051


def test_confirmatory_windows_are_configured_non_overlapping():
    assert study.WINDOW == study.STRIDE == 20
