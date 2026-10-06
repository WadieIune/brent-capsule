import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import torch


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "applications" / "experiments" / "brent_regime_autoencoder.py"
SPEC = importlib.util.spec_from_file_location("brent_regime_autoencoder", MODULE_PATH)
ae = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ae)


def test_windows_are_trailing_and_causal():
    values = np.arange(40, dtype=float)
    windows, ends = ae.build_windows(values, lookback=5)
    assert windows.shape == (36, 5)
    assert windows[0].tolist() == [0, 1, 2, 3, 4]
    assert windows[-1].tolist() == [35, 36, 37, 38, 39]
    assert ends[0] == 4 and ends[-1] == 39


def test_autoencoder_bottleneck_and_output_shape():
    model = ae.ReturnAutoencoder(width=12, latent_dim=3)
    x = torch.zeros((4, 12))
    assert model.mu.out_features == 3
    assert model(x).shape == x.shape
    assert ae.latent_means(model, x.numpy()).shape == (4, 3)
    assert ae.sample_returns(model, center=0.0, scale=1.0,
                             observation_noise_sd=0.1, n=5).shape == (5, 12)


def test_alert_cooldown_and_event_merge():
    alert = ae._alerts(np.ones(31), threshold=0.5, cooldown=10)
    assert np.flatnonzero(alert).tolist() == [0, 10, 20, 30]
    event = np.zeros(40, dtype=bool)
    event[[3, 7, 18, 30]] = True
    assert ae._episodes(event, merge=10).tolist() == [3, 18, 30]


def test_threshold_calibration_respects_cooldown_and_reports_attainable_load():
    score = np.linspace(0, 1, 252)
    threshold = ae._calibrate_threshold(score, target_reviews_per_year=20)
    reviews = ae._alerts(score, threshold).sum()
    assert 0 < reviews < 20


def test_paired_block_bootstrap_is_deterministic_and_paired():
    rows = []
    for year, (candidate, baseline) in enumerate(zip([0.6, 0.4, 0.7, 0.5, 0.8, 0.6],
                                                       [0.5, 0.5, 0.6, 0.6, 0.7, 0.7])):
        rows.extend([{"year": year, "model": "a", "recall": candidate},
                     {"year": year, "model": "b", "recall": baseline}])
    data = pd.DataFrame(rows)
    first = ae._block_bootstrap_delta(data, "a", "b", block_years=2, draws=100, seed=1)
    second = ae._block_bootstrap_delta(data, "a", "b", block_years=2, draws=100, seed=1)
    assert first == second
    assert np.isclose(first["delta_mean"], 0.0)
