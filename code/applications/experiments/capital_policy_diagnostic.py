"""Sensitivity of frozen optimizer to scenario probabilities, no model tuning."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

ROOT=Path(__file__).resolve().parents[3]
raw=pd.read_csv(ROOT/'data/panel_extendido_2026-09-09.csv',parse_dates=['date']).set_index('date')
p=raw[['BRENT','EURUSD']].dropna()
r=np.log(p.shift(-10)/p)
end=pd.Series(p.index,index=p.index).shift(-10)
rows=[]
for year in (2024,2025,2026):
    mask=(r.index>=pd.Timestamp('2015-01-01')) & (end<pd.Timestamp(year-1,1,1))
    scenario=r.loc[mask].to_numpy()
    labels=KMeans(n_clusters=6,random_state=42,n_init=10).fit_predict(scenario/scenario.std(axis=0))
    counts=np.bincount(labels,minlength=6)
    prior=counts/counts.sum()
    physical=1e6*np.expm1(scenario[:,0]-scenario[:,1])
    oil,fx=1e6*np.expm1(scenario[:,0]),1e6*np.expm1(-scenario[:,1])
    actions=[]; shortfalls=[]
    for hp in (0,.25,.5,.75,1):
        for hf in (0,.25,.5,.75,1):
            if hp+hf>1: continue
            fee=1000*(hp+hf)
            residual=physical-hp*oil-hf*fx
            for reserve in np.linspace(0,150000,31):
                if fee+reserve>150000: continue
                actions.append((hp,hf,reserve,fee))
                shortfalls.append(np.maximum(residual-reserve,0))
    a=np.asarray(actions); sf=np.asarray(shortfalls)
    # All vertices of the allowed 20%-historical probability simplex.
    for name,q in [('historical',prior)]+[(f'vertex_{c}',.2*prior+.8*np.eye(6)[c]) for c in range(6)]:
        w=q[labels]/counts[labels]
        obj=a[:,3]+.05*10/252*a[:,2]+2*(sf@w)
        order=np.argsort(obj,kind='stable')
        best,second=order[:2]
        different=np.flatnonzero(np.any(a[:,:2]!=a[best,:2],axis=1))
        alt=different[np.argmin(obj[different])]
        rows.append(dict(year=year,distribution=name,hp=float(a[best,0]),hf=float(a[best,1]),
            reserve=float(a[best,2]),objective=float(obj[best]),second_gap=float(obj[second]-obj[best]),
            different_hedge_gap=float(obj[alt]-obj[best]),best_alternative_hedge=a[alt,:2].tolist()))
out=ROOT/'code/applications/outputs_capital/capital_policy_diagnostic';out.mkdir(parents=True,exist_ok=True)
pd.DataFrame(rows).to_csv(out/'probability_vertices.csv',index=False)
summary={'status':'diagnostic_not_predictive_validation','rows':rows,
    'tail_probability_implied':(.05*10/252)/2,
    'interpretation':'Vertices cover extrema of fixed-mixture class probabilities, not plausible forecasts; policy changes here do not prove achievable CNN advantage.'}
(out/'summary.json').write_text(json.dumps(summary,indent=2))
print(pd.DataFrame(rows).to_string(index=False))
