"""Read-only inventory of the local multivariable panel before as-of reconstruction."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

p=argparse.ArgumentParser()
p.add_argument('--data',required=True)
p.add_argument('--out',required=True)
a=p.parse_args()
root=Path(a.data)
df=pd.read_csv(root/'dataset_wide_with_target.csv',parse_dates=['date']).set_index('date')
fred=pd.read_csv(root/'brent_fred_daily.csv',parse_dates=['date']).set_index('date').BRENT
raw_columns=[c for c in df.columns if '_' not in c]
rows=[]
for col in raw_columns:
 s=df[col]
 rows.append({'variable':col,'first':str(s.first_valid_index()),'last':str(s.last_valid_index()),
              'available':int(s.notna().sum()),'missing':int(s.isna().sum()),
              'nonpositive':int((s<=0).sum()),'unchanged_consecutive':int((s==s.shift()).sum()),
              'release_time_available':False,'vintage_available':False})
joined=pd.concat([df.BRENT.rename('bundle'),fred.rename('fred')],axis=1).dropna()
summary={'panel_rows':len(df),'panel_columns':len(df.columns),'raw_variables':len(raw_columns),
         'weekend_rows':int((df.index.dayofweek>=5).sum()),'date_duplicates':int(df.index.duplicated().sum()),
         'panel_start':str(df.index.min()),'panel_end':str(df.index.max()),
         'brent_fred_end':str(fred.index.max()),'brent_common_dates':len(joined),
         'brent_median_absolute_source_difference':float((joined.bundle-joined.fred).abs().median()),
         'brent_match_fraction_atol_001':float(np.isclose(joined.bundle,joined.fred,atol=.01,rtol=0).mean()),
         'asof_ready':False,
         'missing_priority_information':['EIA inventories and release calendar','GPR vintages','OVX',
                                         'CPI vintages','industrial production vintages'],
         'notes':['Unchanged values do not prove invalidity; distinguish market closures and low-frequency series.',
                  'Brent source difference detected, exact instruments/providers not identified by this audit.',
                  'Negative interest rates and negative WTI are not to be clipped or log-transformed blindly.',
                  'Existing normalized features require training-period provenance; no full-sample leakage proven here.'],
         'sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                   ['dataset_wide_with_target.csv','brent_fred_daily.csv']}}
summary['volatility_recheck'] = {}
for convention, series in [('observed_no_fill', fred), ('business_ffill', fred.reindex(pd.bdate_range(fred.index.min(), fred.index.max())).ffill())]:
    ret = np.log(series).diff()
    vol = ret.rolling(20).std(ddof=1)*np.sqrt(252)
    recent = vol.loc['2026']
    top = vol.nlargest(400)
    summary['volatility_recheck'][convention] = {
        'return_acf_lag1': float(ret.autocorr(1)),
        'abs_return_acf_lag1': float(ret.abs().autocorr(1)),
        'abs_return_acf_lag5': float(ret.abs().autocorr(5)),
        'abs_return_acf_lag20': float(ret.abs().autocorr(20)),
        '2026_max_annualized_vol': float(recent.max()),
        '2026_max_date': str(recent.idxmax()),
        '2026_observations_in_top400': int((top.index.year == 2026).sum()),
        '2026_observations': int(series.loc['2026'].size),
        'estimator': 'std(log returns, window=20, ddof=1)*sqrt(252)',
        'event_attribution': 'not established by this descriptive calculation'}
out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
pd.DataFrame(rows).to_csv(out/'variable_inventory.csv',index=False)
(out/'data_audit.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
