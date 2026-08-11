"""Smoke tests de las aplicaciones sobre serie sintética (sin datos propietarios).

Verifican que el harness ejecuta cada experimento end-to-end, que produce un
manifest reproducible y que las métricas tienen la forma esperada. No comprueban
poder predictivo (eso depende del dato real): comprueban que NO hay fugas de
excepción y que la tubería es ejecutable.

Ejecutar:  python -m pytest code/applications/tests -q
       o:  python code/applications/tests/test_smoke.py
"""
from __future__ import annotations

import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Harness  # noqa: E402
from experiments import ALL_EXPERIMENTS  # noqa: E402


def _config(tmp_out: str) -> dict:
    return {"synthetic": True, "cutoff": None, "alpha": 0.99, "horizon": 10,
            "prices_path": None}


def test_synthetic_series_shape():
    s = common.synthetic_brent(n=800, seed=1)
    assert len(s) == 800
    assert (s > 0).all()


def test_all_experiments_run(tmp_path=None):
    out = str(tmp_path) if tmp_path else os.path.join(_APP, "outputs_test")
    harness = Harness(out_dir=out, task_id="smoke")
    for E in ALL_EXPERIMENTS:
        m = harness.run(E(), config=_config(out))
        assert m["error"] is None, f"{E.__name__} falló: {m.get('error')}"
        assert m["decision"] in {"accept", "reject", "review"}
        assert os.path.exists(m["manifest_path"])
        assert isinstance(m["metrics"], dict) and m["metrics"]


def test_var_backtest_tests_present():
    out = os.path.join(_APP, "outputs_test")
    harness = Harness(out_dir=out, task_id="smoke")
    from experiments import PredictedVaRExperiment

    m = harness.run(PredictedVaRExperiment(), config=_config(out))
    assert m["error"] is None
    met = m["metrics"]
    assert met.get("survival_method")  # integración de supervivencia ejecutada
    if "historical" in met:  # si hubo test suficiente
        assert "kupiec" in met["historical"]
        assert "christoffersen" in met["historical"]


def test_forecast_survival_feature_present():
    out = os.path.join(_APP, "outputs_test")
    harness = Harness(out_dir=out, task_id="smoke")
    from experiments import ChannelVolForecastExperiment

    m = harness.run(ChannelVolForecastExperiment(), config=_config(out))
    assert m["error"] is None
    met = m["metrics"]
    assert met.get("survival_method") in {"cox", "km_bucket", "none"}
    if "model_geometry_plus_survival" in met:
        assert "auc" in met["model_geometry_plus_survival"]


def test_survival_featurizer_km_fallback():
    """La supervivencia debe funcionar sin lifelines (KM por buckets)."""
    s = common.synthetic_brent(n=1200, seed=3)
    prices = s.to_numpy()
    dates = __import__("pandas").DatetimeIndex(s.index)
    episodes = common.cs.extract_episodes(prices, dates)
    fz = common.SurvivalFeaturizer().fit(episodes, cutoff=None)
    assert fz.method in {"cox", "km_bucket"}
    _idx, _flags, feats = common.window_features(prices)
    pk = fz.predict_pk(feats, 10)
    assert len(pk) == len(feats)
    finite = pk[pk == pk]
    assert ((finite >= 0.0) & (finite <= 1.0)).all()


if __name__ == "__main__":
    test_synthetic_series_shape()
    test_survival_featurizer_km_fallback()
    test_all_experiments_run()
    test_var_backtest_tests_present()
    test_forecast_survival_feature_present()
    print("OK smoke tests")
