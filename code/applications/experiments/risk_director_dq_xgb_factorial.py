"""Synthetic-stale stress factorial, not proof of natural-data DQ benefit.

Common reference labels/calendars isolate information-quality effects; reference
scenario outcomes are assumed separately audited, including in training.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from xgboost import XGBClassifier
from risk_director_capital_cnn import optimize

H=10

def contaminate(prices,seed=71):
    rng=np.random.default_rng(seed)
    dirty=prices.copy()
    truth=pd.DataFrame(False,index=prices.index,columns=prices.columns)
    for col in prices:
        for i in range(70,len(prices)-5):
            if rng.random()<.005:
                length=int(rng.integers(2,6))
                dirty.iloc[i:i+length,dirty.columns.get_loc(col)]=dirty.iloc[i-1][col]
                truth.iloc[i:i+length,truth.columns.get_loc(col)]=True
    return dirty,truth

def audit(prices):
    # Detect only consecutive exact repeats, causally. No claim to infer stale from one repeat.
    equal=prices.eq(prices.shift())
    flagged=equal & equal.shift(fill_value=False)
    return prices.mask(flagged),flagged

def features(prices):
    # No filling; adjacent-invalid returns remain missing; true calendar preserved.
    r=np.log(prices).diff()
    variance=r.pow(2).ewm(alpha=.06,adjust=False,ignore_na=True,min_periods=20).mean()
    cols=[]
    for lag in range(64):
        cols.append(r.shift(lag).add_suffix(f'_lag{lag}'))
    cols.extend([variance.add_suffix('_ewma'),prices.isna().astype(float).add_suffix('_missing')])
    return pd.concat(cols,axis=1),variance

def run(panel,out,seed):
    ref=pd.read_csv(panel,parse_dates=['date']).set_index('date')[['BRENT','EURUSD']].dropna()
    if not ref.index.is_monotonic_increasing or ref.index.has_duplicates:
        raise ValueError('Reference dates must be sorted and unique')
    if not np.isfinite(ref.to_numpy()).all() or (ref<=0).any().any():
        raise ValueError('Reference Brent/EURUSD prices must be finite and positive')
    dirty,truth=contaminate(ref,seed)
    cleaned,flags=audit(dirty)
    datasets={'dirty':dirty,'dq':cleaned,'reference':ref}
    target=np.log(ref.shift(-H)/ref)
    ends=pd.Series(ref.index,index=ref.index).shift(-H)
    decision_ids=np.arange(np.searchsorted(ref.index,pd.Timestamp('2024-01-01')),len(ref)-H,H)
    records=[]; scores=[]; folds=[]
    for year in (2024,2025,2026):
        tr=np.flatnonzero((ref.index>=pd.Timestamp('2015-01-01')) & (ends<pd.Timestamp(year-1,1,1)))
        va=np.flatnonzero((ref.index>=pd.Timestamp(year-1,1,1)) & (ends<pd.Timestamp(year,1,1)))
        te=decision_ids[(ref.index[decision_ids].year==year)]
        y=target.to_numpy()
        if len(te)<1:continue
        scale=np.maximum(y[tr].std(axis=0),1e-8)
        km=KMeans(n_clusters=6,n_init=10,random_state=42).fit(y[tr]/scale)
        labels=km.predict(np.nan_to_num(y/scale))
        counts=np.bincount(labels[tr],minlength=6);prior=counts/counts.sum()
        hist_daily=np.log(ref).diff().iloc[tr].pow(2).mean().to_numpy()
        for quality,prices in datasets.items():
            x,v=features(prices)
            # One-observation delay for all features and conditional volatility.
            x=x.shift().to_numpy(dtype='float32');v=v.shift().to_numpy()
            classifier=XGBClassifier(n_estimators=300,max_depth=3,min_child_weight=10,
                learning_rate=.04,subsample=.8,colsample_bytree=.8,reg_lambda=10,
                objective='multi:softprob',num_class=6,n_jobs=2,random_state=42,
                eval_metric='mlogloss',early_stopping_rounds=20)
            classifier.fit(x[tr],labels[tr],eval_set=[(x[va],labels[va])],verbose=False)
            prediction=classifier.predict_proba(x[te])
            for model,probs in [('fhs_ewma',np.tile(prior,(len(te),1))),('xgb_fhs',prediction)]:
                mixed=.8*probs+.2*prior
                for j,idx in enumerate(te):
                    weights=mixed[j,labels[tr]]/counts[labels[tr]]
                    # Shared reference library; observation-quality changes conditioning only.
                    if not np.isfinite(v[idx]).all():
                        raise ValueError('Conditional variance forecast is unavailable')
                    vol_ratio=np.sqrt(np.maximum(v[idx],1e-12)/np.maximum(hist_daily,1e-12))
                    vol_ratio=np.clip(vol_ratio,.25,4)  # fixed safety bound, not selected in test.
                    scenario=y[tr]*vol_ratio
                    objective,hp,hf,reserve,fee=optimize(scenario,weights)
                    rb,rfx=y[idx]
                    loss=1e6*(np.expm1(rb-rfx)-hp*np.expm1(rb)-hf*np.expm1(-rfx))
                    deficit=max(0,loss-reserve)
                    cost=fee+.05*H/252*reserve+2*deficit
                    records.append(dict(date=str(ref.index[idx].date()),end=str(ends.iloc[idx].date()),
                        year=year,quality=quality,model=model,hp=hp,hf=hf,reserve_eur=reserve,
                        residual_loss_eur=loss,shortfall_eur=deficit,total_cost_eur=cost))
                    scores.append(dict(date=str(ref.index[idx].date()),quality=quality,model=model,
                        logloss=float(-np.log(max(mixed[j,labels[idx]],1e-12))),
                        brier=float(((mixed[j]-np.eye(6)[labels[idx]])**2).sum())))
            folds.append(dict(year=year,quality=quality,train_n=len(tr),validation_n=len(va),test_n=len(te),
                best_iteration=int(classifier.best_iteration),train_label_end_max=str(ends.iloc[tr].max().date()),
                validation_label_end_max=str(ends.iloc[va].max().date())))
        print(f'Finished factorial {year}',flush=True)
    out.mkdir(parents=True,exist_ok=True)
    d=pd.DataFrame(records);s=pd.DataFrame(scores)
    d.to_csv(out/'decisions.csv',index=False);s.to_csv(out/'scores.csv',index=False)
    summary=d.groupby(['quality','model']).agg(mean_cost=('total_cost_eur','mean'),
        mean_reserve=('reserve_eur','mean'),mean_shortfall=('shortfall_eur','mean'),
        shortfall_rate=('shortfall_eur',lambda a:float((a>0).mean())),n=('date','size')).reset_index()
    cal=s.groupby(['quality','model'])[['logloss','brier']].mean().reset_index()
    summary=summary.merge(cal,on=['quality','model'])
    summary.to_csv(out/'summary.csv',index=False)
    means=summary.set_index(['quality','model']).mean_cost
    dq_effect=means['dq','fhs_ewma']-means['dirty','fhs_ewma']
    model_effect=means['dirty','xgb_fhs']-means['dirty','fhs_ewma']
    interaction=(means['dq','xgb_fhs']-means['dq','fhs_ewma'])-model_effect
    truth_count=int(truth.to_numpy().sum()); detected=int((truth&flags).to_numpy().sum())
    manifest=dict(status='synthetic_stale_stress_exploratory',injection_seed=seed,model_seed=42,
        panel_sha256=hashlib.sha256(panel.read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),folds=folds,
        cost_effects_eur=dict(dq_under_baseline=float(dq_effect),xgb_under_dirty=float(model_effect),interaction=float(interaction)),
        flags=dict(injected_cells=truth_count,flagged_cells=int(flags.to_numpy().sum()),true_flagged_cells=detected),
        limitations=['Synthetic stale injection; no claim of equivalent natural corruption.',
          'DQ is causal repeated-price masking, not complete geometric detector and not CNN.',
          'Both inputs and reference outcome library retain same calendar and future reference target.',
          'Reference historical outcome library assumed separately audited; isolates input conditioning only.',
          'FHS uses shared multiday reference scenarios scaled by current EWMA ratio, not full daily path simulation.',
          'Model missings supported by XGBoost; no oracle price recovery.',
          'Idealized hedges, fixed hypothetical costs, capital economic proxy, no regulatory claim.',
          'Single injection seed/model seed; no robust attribution or prospectively confirmed gain.'])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(summary.to_string(index=False));print(json.dumps(manifest['cost_effects_eur']))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--seed',type=int,default=71)
    a=ap.parse_args();run(a.panel,a.out,a.seed)
