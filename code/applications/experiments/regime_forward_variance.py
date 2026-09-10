"""Exploratory ten-observation forward risk forecast; no CNN claim.

Run with --prices CSV --out DIR. Uses observed positive closes without ffill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HORIZON = 10
GEOMETRY = ['slope_norm', 'r2', 'width_rel', 'position']


def frame(prices):
    p = prices.astype(float)
    if not p.index.is_monotonic_increasing or p.index.has_duplicates:
        raise ValueError('Dates must be unique and increasing')
    if not np.isfinite(p).all() or (p <= 0).any():
        raise ValueError('Prices must be finite and positive')
    r2 = np.log(p).diff().pow(2)
    f = pd.DataFrame(index=p.index)
    f['target'] = sum(r2.shift(-j) for j in range(1, HORIZON + 1)) / HORIZON
    f['label_end'] = pd.Series(p.index, index=p.index).shift(-HORIZON)
    f['ewma'] = r2.ewm(alpha=.06, adjust=False).mean()
    for w in [1, 5, 22]:
        f[f'rv{w}'] = r2.rolling(w).mean()
    # Local OLS on 32 observed raw closes; no full-series normalization/smoothing.
    x = np.arange(32, dtype=float)
    xc = x - x.mean()
    vals = p.to_numpy()
    geo = np.full((len(p), 4), np.nan)
    for t in range(31, len(p)):
        y = vals[t-31:t+1]
        slope = np.dot(xc, y-y.mean()) / np.dot(xc, xc)
        fitted = y.mean() + slope*xc
        resid = y-fitted
        sd = np.sqrt(np.mean(resid**2))
        ss = np.sum((y-y.mean())**2)
        geo[t] = [slope/y.mean(), 1-np.sum(resid**2)/ss if ss else 0,
                  4*sd/y.mean(), resid[-1]/max(sd, 1e-12)]
    f[GEOMETRY] = geo
    f['pos'] = np.arange(len(p))
    return f


def design(f, family, geometry):
    floor = 1e-12
    if family == 'EWMA':
        offset = np.log(f.ewma.clip(lower=floor).to_numpy())
        x = np.empty((len(f), 0))
    else:
        offset = np.log(f.rv22.clip(lower=floor).to_numpy())
        x = np.column_stack([np.log(f[c].clip(lower=floor))-offset
                             for c in ['rv1', 'rv5']])
    if geometry:
        x = np.column_stack([x, f[GEOMETRY].to_numpy()])
    return offset, x


def predict(train, test, family, geometry, extra_columns=()):
    off, x = design(train, family, geometry)
    off_test, xt = design(test, family, geometry)
    if extra_columns:
        x = np.column_stack([x, train[list(extra_columns)].to_numpy()])
        xt = np.column_stack([xt, test[list(extra_columns)].to_numpy()])
    mu, sd = x.mean(axis=0), x.std(axis=0)
    sd = np.maximum(sd, 1e-8)
    x = np.column_stack([np.ones(len(x)), (x-mu)/sd])
    xt = np.column_stack([np.ones(len(xt)), (xt-mu)/sd])
    y = train.target.to_numpy()
    def objective(b):
        eta = off+x@b
        ratio = y*np.exp(-eta)
        penalty = .01*np.dot(b[1:], b[1:])/2
        grad = x.T@(1-ratio)/len(y)
        grad[1:] += .01*b[1:]
        return np.mean(eta+ratio)+penalty, grad
    fit = minimize(objective, np.zeros(x.shape[1]), jac=True, method='L-BFGS-B')
    if not fit.success:
        raise RuntimeError(fit.message)
    return np.exp(off_test+xt@fit.x)


def loss(y, forecast):
    # Difference-compatible QLIKE, finite even when realized squared returns = 0.
    return np.log(forecast)+y/forecast


def block_interval(values, block, seed=1729, reps=2000):
    rng = np.random.default_rng(seed)
    n = len(values)
    means = []
    for _ in range(reps):
        starts = rng.integers(0, n-block+1, size=int(np.ceil(n/block)))
        idx = (starts[:, None]+np.arange(block)).ravel()[:n]
        means.append(np.mean(values[idx]))
    return np.quantile(means, [.025, .975]).tolist()


def run(prices, out):
    raw = pd.read_csv(prices)
    raw['date'] = pd.to_datetime(raw.date)
    raw['BRENT'] = pd.to_numeric(raw.BRENT, errors='raise')
    dropped = int(raw.BRENT.isna().sum())
    raw = raw.dropna(subset=['BRENT']).sort_values('date')
    f = frame(raw.set_index('date').BRENT).dropna()
    f = f.loc['2000-01-01':]
    records, folds = [], []
    for year in range(2016, f.index.max().year+1):
        test = f[f.index.year == year]
        if len(test) < 50:
            continue
        start = test.index.min()
        available = f[(f.index < start) & (f.label_end < start)]
        valid = available.iloc[-252:]
        train = available[available.label_end < valid.index.min()]
        if len(train) < 1000:
            continue
        scores = {family: float(np.mean(loss(valid.target.to_numpy(),
                   predict(train, valid, family, False)))) for family in ['EWMA', 'HAR']}
        chosen = min(scores, key=scores.get)
        fold = {'year': year, 'selected': chosen, 'validation_qlike': scores,
                'train_end_label': str(train.label_end.max()),
                'validation_start': str(valid.index.min()),
                'refit_end_label': str(available.label_end.max()), 'test_start': str(start),
                'purged_before_test': int(((f.index < start) & (f.label_end >= start)).sum()),
                'purged_before_validation': int(((available.index < valid.index.min()) &
                                               (available.label_end >= valid.index.min())).sum())}
        folds.append(fold)
        row = pd.DataFrame({'date': test.index, 'year': year, 'target': test.target.to_numpy(),
                            'label_end': test.label_end.to_numpy(), 'selected': chosen})
        for family in ['EWMA', 'HAR']:
            for geo in [False, True]:
                name = family+('_geometry' if geo else '')
                row[name] = predict(available, test, family, geo)
        row['base'] = row[chosen]
        row['geometry'] = row[chosen+'_geometry']
        records.append(row)
    result = pd.concat(records, ignore_index=True)
    result['delta_qlike'] = loss(result.target, result.geometry)-loss(result.target, result.base)
    delta = result.delta_qlike.to_numpy()
    annual = result.groupby('year').agg(n=('delta_qlike', 'size'), delta_qlike=('delta_qlike', 'mean'))
    summary = {'status': 'exploratory_provisional', 'cnn_status': 'not_evaluated_provenance_pending',
               'n': len(result), 'delta_qlike_geometry_minus_base': float(delta.mean()),
               'block_intervals_95': {str(b): block_interval(delta, b) for b in [10, 20, 60]},
               'source_sha256': hashlib.sha256(Path(prices).read_bytes()).hexdigest(),
               'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'source_missing_prices_removed': dropped, 'folds': folds,
               'limitations': ['Historical test reused; no confirmatory claim.',
                  'HAR uses squared close returns, not intraday realized variance.',
                  'Ten observed intervals, not a verified exchange calendar.',
                  'Target is a second moment, not directly ES or ten-day aggregate variance.',
                  'No GARCH, CNN or economic materiality threshold evaluated.',
                  'Bootstrap intervals are pointwise, conditional on fitted forecasts.']}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result.to_csv(out/'forecasts.csv', index=False)
    annual.to_csv(out/'per_year.csv')
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(annual.to_string())
    print(json.dumps({k:v for k,v in summary.items() if k != 'folds'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prices', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    run(args.prices, args.out)
