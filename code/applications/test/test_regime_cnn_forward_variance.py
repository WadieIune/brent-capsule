"""Leakage and provenance rejection checks for the CNN-risk bridge."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

EXPERIMENTS=Path(__file__).resolve().parents[1]/'experiments'
sys.path.insert(0,str(EXPERIMENTS))
import regime_cnn_forward_variance as m
from regime_forward_variance import frame,predict


def bundle(tmp_path):
    prices=tmp_path/'prices.csv'
    prices.write_text('date,BRENT\n2005-01-03,50\n')
    head=tmp_path/'heads_2005.joblib'
    head.write_bytes(b'fixture head hash')
    rows=pd.DataFrame({'date':['2005-01-03','2005-01-04'],
        'window_start':['2004-11-17','2004-11-18'],
        'head_train_end':['2004-11-16']*2,'fold_start':['2005-01-03']*2,
        'head_sha256':[m.digest(head)]*2,
        m.CNN[0]:[.7,.8],m.CNN[1]:[.6,.5]})
    scores=tmp_path/'scores.csv'
    rows.to_csv(scores,index=False)
    manifest={'source_sha256':m.digest(prices),'prediction_sha256':m.digest(scores),
        'crossfit':'annual_expanding_disjoint_windows','backbone_frozen':True,
        'head_folds':[{'year':2005,'predict_n':2,'head_sha256':m.digest(head)}]}
    provenance=tmp_path/'provenance.json'
    provenance.write_text(json.dumps(manifest))
    return scores,provenance,prices


def update_scores(scores,provenance,rows):
    rows.to_csv(scores,index=False)
    manifest=json.loads(provenance.read_text())
    manifest['prediction_sha256']=m.digest(scores)
    provenance.write_text(json.dumps(manifest))


def test_independent_scores_need_not_sum_to_one(tmp_path):
    scores,provenance,prices=bundle(tmp_path)
    rows,_=m.validate_predictions(scores,provenance,prices)
    assert (rows[m.CNN].sum(axis=1)>1).all()


@pytest.mark.parametrize('column,value',[('head_train_end','2004-11-17'),
    ('fold_start','2005-01-05'),('window_start','2005-01-05'),
    ('prob_ascending_channel',1.1),('prob_descending_channel',float('nan'))])
def test_temporal_and_probability_violations_rejected(tmp_path,column,value):
    scores,provenance,prices=bundle(tmp_path)
    rows=pd.read_csv(scores)
    rows.loc[0,column]=value
    update_scores(scores,provenance,rows)
    with pytest.raises(ValueError):
        m.validate_predictions(scores,provenance,prices)


def test_modified_head_rejected(tmp_path):
    scores,provenance,prices=bundle(tmp_path)
    (tmp_path/'heads_2005.joblib').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Head hash'):
        m.validate_predictions(scores,provenance,prices)


def test_modified_source_rejected(tmp_path):
    scores,provenance,prices=bundle(tmp_path)
    prices.write_text('different')
    with pytest.raises(ValueError,match='hash mismatch'):
        m.validate_predictions(scores,provenance,prices)


def test_cnn_model_never_reads_test_targets():
    rng=np.random.default_rng(9)
    p=pd.Series(60*np.exp(np.cumsum(rng.normal(0,.01,500))),index=pd.bdate_range('2000-01-01',periods=500))
    f=frame(p).dropna()
    f[m.CNN]=rng.uniform(.1,.9,(len(f),2))
    train,test=f.iloc[:300],f.iloc[310:]
    changed=test.copy()
    changed['target']=100
    for geo in [False,True]:
        np.testing.assert_array_equal(predict(train,test,'HAR',geo,m.CNN),predict(train,changed,'HAR',geo,m.CNN))
