"""Four matched-sample forward-risk ablations using verified causal CNN scores."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from regime_cnn_causal import digest
from regime_forward_variance import frame, predict, loss, block_interval

CNN = ['prob_ascending_channel','prob_descending_channel']
CONTRACT = {
    'status': 'exploratory_not_confirmatory', 'target': 'mean_next_10_observed_log_returns_squared',
    'test_years': '2016-2026_partial', 'validation_n': 252, 'purge': 'label_end strictly before fold start',
    'baseline_selection': 'EWMA vs log-HAR on validation QLIKE, same selected family in all ablations',
    'primary_comparison': 'base_geometry_cnn minus base_geometry',
    'secondary_comparison': 'base_cnn minus base',
    'diagnostic_minimum_qlike_reduction': .01,
    'criterion': 'both differences <= -0.01 and both upper 97.5% CI bounds < 0 for all block sizes',
    'blocks': [10,20,60], 'bootstrap_replicates': 2000, 'seed':1729,
    'economic_materiality': 'not established; diagnostic hurdle only; no deployment claim',
    'cnn': 'yearly cross-fit, frozen local ImageNet backbone, disjoint head training windows',
    'regularization': 'risk model L2 0.01; CNN head C=1; fixed before CNN risk evaluation',
}


def validate_predictions(scores, provenance, prices):
    meta = json.loads(Path(provenance).read_text())
    if meta['source_sha256'] != digest(prices) or meta['prediction_sha256'] != digest(scores):
        raise ValueError('Data or prediction hash mismatch')
    if meta.get('crossfit') != 'annual_expanding_disjoint_windows' or not meta.get('backbone_frozen'):
        raise ValueError('Unverified cross-fit/backbone')
    rows = pd.read_csv(scores, parse_dates=['date','window_start','head_train_end','fold_start'])
    if rows[['date','window_start','head_train_end','fold_start','head_sha256']+CNN].isna().any().any():
        raise ValueError('Missing prediction metadata')
    if rows.date.duplicated().any() or not rows.date.is_monotonic_increasing:
        raise ValueError('Invalid dates')
    if not np.isfinite(rows[CNN]).all().all() or not ((rows[CNN]>=0)&(rows[CNN]<=1)).all().all():
        raise ValueError('Invalid independent probabilities')
    if not ((rows.head_train_end < rows.window_start) & (rows.window_start <= rows.date)
            & (rows.head_train_end < rows.fold_start) & (rows.fold_start <= rows.date)).all():
        raise ValueError('Temporal provenance violation')
    folder = Path(provenance).parent
    for fold in meta['head_folds']:
        group = rows[rows.date.dt.year == fold['year']]
        if len(group) != fold['predict_n'] or not (group.head_sha256 == fold['head_sha256']).all():
            raise ValueError('Fold metadata mismatch')
        if digest(folder/f"heads_{fold['year']}.joblib") != fold['head_sha256']:
            raise ValueError('Head hash mismatch')
    if set(rows.date.dt.year) != {f['year'] for f in meta['head_folds']}:
        raise ValueError('Unrecorded head fold')
    return rows.set_index('date'), meta


def intervals(values, block):
    # 97.5% intervals: Bonferroni over the two directional comparisons, two-sided.
    rng = np.random.default_rng(1729)
    n = len(values)
    means = []
    for _ in range(2000):
        starts = rng.integers(0,n-block+1,size=int(np.ceil(n/block)))
        ix=(starts[:,None]+np.arange(block)).ravel()[:n]
        means.append(values[ix].mean())
    return np.quantile(means,[.0125,.9875]).tolist()


def run(args):
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    protocol = out/'protocol.json'
    # Contract must be frozen before inspecting CNN risk outcomes.
    if not protocol.exists() or json.loads(protocol.read_text()) != CONTRACT:
        raise ValueError('Run --freeze-contract first; contract mismatch or missing')
    scores, provenance = validate_predictions(args.scores,args.provenance,args.prices)
    raw = pd.read_csv(args.prices,parse_dates=['date']).sort_values('date').dropna(subset=['BRENT'])
    full = frame(raw.set_index('date').BRENT)
    if not scores.index.isin(full.index).all():
        raise ValueError('CNN dates absent from observed prices')
    # Validate 32-observation window dates against the exact target price calendar.
    starts = pd.Series(full.index,index=full.index).shift(31).reindex(scores.index)
    if not (starts == scores.window_start).all():
        raise ValueError('CNN uses a different price calendar')
    f = full.join(scores[CNN],how='inner').dropna()
    records,folds=[],[]
    variants={'base':(False,()),'base_geometry':(True,()),'base_cnn':(False,CNN),'base_geometry_cnn':(True,CNN)}
    for year in range(2016,f.index.max().year+1):
        test=f[f.index.year==year]
        if len(test)<50:
            continue
        start=test.index.min()
        available=f[(f.index<start)&(f.label_end<start)]
        valid=available.iloc[-252:]
        train=available[available.label_end<valid.index.min()]
        if len(train)<1000:
            raise ValueError('Insufficient matched-sample history')
        validation={family:float(np.mean(loss(valid.target,predict(train,valid,family,False)))) for family in ['EWMA','HAR']}
        selected=min(validation,key=validation.get)
        row=pd.DataFrame({'date':test.index,'year':year,'target':test.target.to_numpy(),'label_end':test.label_end.to_numpy(),'selected':selected})
        for name,(geo,extras) in variants.items():
            row[name]=predict(available,test,selected,geo,extras)
        records.append(row)
        folds.append({'year':year,'family':selected,'validation':validation,'train_n':len(train),
                      'train_label_end':str(train.label_end.max()),'validation_start':str(valid.index.min()),
                      'refit_label_end':str(available.label_end.max()),'test_start':str(start),
                      'test_n':len(test)})
    result=pd.concat(records,ignore_index=True)
    pairs={'cnn_over_base':('base_cnn','base'), 'cnn_over_geometry':('base_geometry_cnn','base_geometry'),
           'geometry_over_base':('base_geometry','base')}
    comparisons={}
    for name,(candidate,reference) in pairs.items():
        d=np.asarray(loss(result.target,result[candidate])-loss(result.target,result[reference]))
        result[name]=d
        comparisons[name]={'mean_delta_qlike':float(d.mean()),
                           'ci_97_5':{str(b):intervals(d,b) for b in CONTRACT['blocks']}}
    pass_gate=all(comparisons[name]['mean_delta_qlike'] <= -.01 and
                  all(ci[1]<0 for ci in comparisons[name]['ci_97_5'].values())
                  for name in ['cnn_over_base','cnn_over_geometry'])
    summary={'status':'provisional_exploratory','diagnostic_gate':'pass' if pass_gate else 'not_met',
             'n':len(result),'first_date':str(result.date.min()),'last_date':str(result.date.max()),
             'comparisons':comparisons,'folds':folds,'source_sha256':digest(args.prices),
             'provenance_sha256':digest(args.provenance),'code_sha256':digest(__file__),
             'predictor_sha256':digest(Path(__file__).with_name('regime_forward_variance.py')),
             'historical_deployability':False,'production_validated':False}
    result.to_csv(out/'forecasts.csv',index=False)
    annual=result.groupby('year')[list(pairs)].mean()
    annual.to_csv(out/'per_year.csv')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(annual.to_string())
    print(json.dumps({k:v for k,v in summary.items() if k!='folds'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--prices')
    p.add_argument('--scores')
    p.add_argument('--provenance')
    p.add_argument('--out',required=True)
    p.add_argument('--freeze-contract',action='store_true')
    args=p.parse_args()
    if args.freeze_contract:
        path=Path(args.out)/'protocol.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            raise ValueError('Contract already exists; do not overwrite')
        path.write_text(json.dumps(CONTRACT,indent=2)+'\n')
        print('CNN risk contract frozen')
    else:
        run(args)
