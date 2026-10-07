import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = (Path(__file__).resolve().parents[1] / "code" / "applications" /
               "experiments" / "dq_return_distribution_comparison.py")
SPEC = importlib.util.spec_from_file_location("dq_return_distribution_comparison", MODULE_PATH)
dists = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dists)


def test_normal_reference_three_sigma_probability_is_expected():
    assert np.isclose(dists.THEORETICAL_GAUSSIAN_3SIGMA, 0.0026998, atol=1e-7)


def test_nonpositive_price_does_not_bridge_log_return(tmp_path):
    n = 160
    frame = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=n)})
    base = np.exp(np.cumsum(np.sin(np.arange(n) / 3.0) * 0.001 + 0.0001)) * 100
    for asset in dists.ASSETS:
        frame[asset] = base
    frame.loc[80, "BRENT"] = 0.0
    panel = tmp_path / "panel.csv"
    frame.to_csv(panel, index=False)

    _, metrics = dists.load_standardized_returns(panel)
    assert metrics["BRENT"]["n"] == n - 3
    assert metrics["WTI"]["n"] == n - 1
