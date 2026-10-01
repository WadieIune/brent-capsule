"""Full prespecified 27-cell sensitivity, exploratory, no selected winner."""
import itertools
import json
import numpy as np
import pandas as pd

def evaluate_fold(year, dates, scenario, labels, prior, models, target, output):
    counts=np.bincount(labels,minlength=6)
    physical=1e6*np.expm1(scenario[:,0]-scenario[:,1])
    oil,fx=1e6*np.expm1(scenario[:,0]),1e6*np.expm1(-scenario[:,1])
    actions=[]; means=[]
    for hp in (0,.25,.5,.75,1):
        for hf in (0,.25,.5,.75,1):
            if hp+hf>1: continue
            residual=physical-hp*oil-hf*fx
            for reserve in np.linspace(0,150000,31):
                sf=np.maximum(residual-reserve,0)
                actions.append((hp,hf,reserve))
                means.append([sf[labels==c].mean() for c in range(6)])
    a=np.asarray(actions); means=np.asarray(means)
    probabilities=[]; calibration=[]; decisions=[]
    observed=output['observed_labels']
    for model, probs in models.items():
        mixed=.8*probs+.2*prior
        for stage,pr in [('raw',probs),('mixed',mixed)]:
            ll=-np.log(np.maximum(pr[np.arange(len(pr)),observed],1e-12))
            brier=((pr-np.eye(6)[observed])**2).sum(axis=1)
            for j,date in enumerate(dates):
                calibration.append(dict(year=year,date=str(date.date()),model=model,stage=stage,
                    logloss=float(ll[j]),brier=float(brier[j])))
        for j,date in enumerate(dates):
            probabilities.append(dict(year=year,date=str(date.date()),model=model,
                observed_class=int(observed[j]),**{f'p{c}':float(probs[j,c]) for c in range(6)}))
        predicted_sf=mixed@means.T
        for funding,penalty,bps in itertools.product((.01,.05,.10),(.25,1.,2.),(10,50,100)):
            fee=1e6*(bps/10000)*(a[:,0]+a[:,1])
            objectives=fee[None,:]+funding*10/252*a[None,:,2]+penalty*predicted_sf
            objectives[:,a[:,2]+fee>150000]=np.inf
            best=np.argmin(objectives,axis=1)
            chosen=a[best]; cost=fee[best]
            loss=1e6*(np.expm1(target[:,0]-target[:,1])-chosen[:,0]*np.expm1(target[:,0])-chosen[:,1]*np.expm1(-target[:,1]))
            shortage=np.maximum(loss-chosen[:,2],0)
            total=cost+funding*10/252*chosen[:,2]+penalty*shortage
            for j,date in enumerate(dates):
                decisions.append(dict(year=year,date=str(date.date()),model=model,funding=funding,
                    penalty=penalty,hedge_bps=bps,hp=float(chosen[j,0]),hf=float(chosen[j,1]),
                    reserve_eur=float(chosen[j,2]),shortfall_eur=float(shortage[j]),
                    residual_loss_eur=float(loss[j]),total_cost_eur=float(total[j])))
    # Reference fixed after initial results: descriptive exploratory comparator only.
    for funding,penalty,bps in itertools.product((.01,.05,.10),(.25,1.,2.),(10,50,100)):
        loss=1e6*np.exp(target[:,0])*np.expm1(-target[:,1])
        shortage=np.maximum(loss-60000,0)
        for j,date in enumerate(dates):
            decisions.append(dict(year=year,date=str(date.date()),model='fixed_hedge_reference',
                funding=funding,penalty=penalty,hedge_bps=bps,hp=1.,hf=0.,reserve_eur=60000.,
                shortfall_eur=float(shortage[j]),residual_loss_eur=float(loss[j]),
                total_cost_eur=float(1e6*bps/10000+funding*10/252*60000+penalty*shortage[j])))
    return probabilities,calibration,decisions

def save_results(out, probabilities, calibration, decisions):
    pd.DataFrame(probabilities).to_csv(out/'probabilities.csv',index=False)
    c=pd.DataFrame(calibration);d=pd.DataFrame(decisions)
    c.to_csv(out/'calibration_by_date.csv',index=False)
    d.to_csv(out/'sensitivity_decisions.csv',index=False)
    cal=c.groupby(['model','stage'])[['logloss','brier']].mean().reset_index()
    cal.to_csv(out/'calibration_summary.csv',index=False)
    key=['funding','penalty','hedge_bps','model']
    agg=d.groupby(key).agg(mean_total_cost_eur=('total_cost_eur','mean'),
        mean_reserve_eur=('reserve_eur','mean'),mean_shortfall_eur=('shortfall_eur','mean'),
        shortfall_rate=('shortfall_eur',lambda x:float((x>0).mean())),
        mean_oil_hedge=('hp','mean'),mean_fx_hedge=('hf','mean')).reset_index()
    agg.to_csv(out/'sensitivity_summary.csv',index=False)
    comparisons=[]
    for keys,g in agg.groupby(['funding','penalty','hedge_bps']):
        indexed=g.set_index('model')
        for comp in ('historical','tabular','cnn_1d','fixed_hedge_reference'):
            comparisons.append(dict(funding=float(keys[0]),penalty=float(keys[1]),hedge_bps=int(keys[2]),comparator=comp,
                cnn_minus_comparator_cost_eur=float(indexed.loc['cnn_visual','mean_total_cost_eur']-indexed.loc[comp,'mean_total_cost_eur'])))
    pd.DataFrame(comparisons).to_csv(out/'sensitivity_comparisons.csv',index=False)
    info={'status':'exploratory_full_grid_no_confirmatory_selection','grid_cells':27,
          'calibration':cal.to_dict('records'),'comparisons':comparisons,
          'limitations':['Historical design already inspected.', 'One seed; uncalibrated classifier probabilities.',
          'Costs hypothetical, instruments idealized, no regulatory capital claim.',
          'Fixed reference introduced after original backtest; exploratory only.',
          'Class Brier/logloss evaluates fold-specific classes, not tail calibration.']}
    (out/'sensitivity_manifest.json').write_text(json.dumps(info,indent=2))
    print(cal.to_string(index=False),flush=True)
