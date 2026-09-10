"""Temporal invariants for the forward-risk experiment."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location('forward_risk', Path(__file__).resolve().parents[1] / 'experiments/regime_forward_variance.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def prices():
    rng = np.random.default_rng(18)
    return pd.Series(60*np.exp(np.cumsum(rng.normal(0, .01, 500))), index=pd.bdate_range('2010-01-01', periods=500))

def test_target_is_exactly_next_ten_returns():
    p = prices()
    f = m.frame(p)
    expected = np.mean(np.diff(np.log(p.iloc[100:111].to_numpy()))**2)
    np.testing.assert_allclose(f.target.iloc[100], expected)
    assert f.label_end.iloc[100] == p.index[110]
    assert f.target.iloc[-10:].isna().all()

def test_future_changes_cannot_change_features():
    p = prices()
    q = p.copy()
    q.iloc[201:] *= np.linspace(1.1, 2, len(q)-201)
    cols = ['ewma', 'rv1', 'rv5', 'rv22']+m.GEOMETRY
    pd.testing.assert_frame_equal(m.frame(p)[cols].iloc[:201], m.frame(q)[cols].iloc[:201])
    assert m.frame(p).target.iloc[200] != m.frame(q).target.iloc[200]

def test_test_labels_never_enter_fit():
    f = m.frame(prices()).dropna()
    train, test = f.iloc[:300], f.iloc[310:]
    changed = test.copy()
    changed['target'] *= 1000
    for family in ['EWMA', 'HAR']:
        np.testing.assert_array_equal(m.predict(train, test, family, True), m.predict(train, changed, family, True))

def test_purge_removes_crossing_labels():
    f = m.frame(prices())
    cut = f.index[300]
    crossing = (f.index < cut) & (f.label_end >= cut)
    assert crossing.sum() == 10
    train = f[(f.index < cut) & (f.label_end < cut)]
    assert train.label_end.max() < cut

def test_invalid_prices_fail_explicitly():
    p = prices()
    p.iloc[80] = 0
    with pytest.raises(ValueError):
        m.frame(p)
