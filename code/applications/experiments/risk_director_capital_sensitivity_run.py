"""Exploratory CNN scenario-weighted capital optimizer; idealized spot hedges.

No regulatory capital claim. Decisions every ten common observations, with one
observation information delay; actual release vintages remain unavailable.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pandas as pd
import torch
from torch import nn
from capital_sensitivity import evaluate_fold, save_results
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression

WINDOW, HORIZON = 64, 10


def images(x):
    # Frozen training-standardized coordinates; amplitude retained, no window scaling.
    z = (1+np.tanh(x / 3))/2
    s = np.sqrt(np.maximum(0, 1-z*z))
    return np.concatenate([z[..., :, None]*z[..., None, :] - s[..., :, None]*s[..., None, :],
                           s[..., :, None]*z[..., None, :] - z[..., :, None]*s[..., None, :]], axis=1).astype('float32')


class Network(nn.Module):
    def __init__(self, channels, classes, visual):
        super().__init__()
        conv = nn.Conv2d if visual else nn.Conv1d
        pool = nn.AdaptiveAvgPool2d((1, 1)) if visual else nn.AdaptiveAvgPool1d(1)
        self.body = nn.Sequential(conv(channels, 12, 5, padding=2), nn.ReLU(),
                                  conv(12, 16, 3, padding=1), nn.ReLU(), pool, nn.Flatten())
        self.head = nn.Linear(16, classes)

    def forward(self, x):
        return self.head(self.body(x))


def fit_network(x, labels, valid, valid_labels, classes, visual, seed):
    torch.manual_seed(seed)
    model = Network(x.shape[1], classes, visual)
    opt = torch.optim.AdamW(model.parameters(), lr=.002, weight_decay=.001)
    rng = np.random.default_rng(seed)
    best, saved, bad = np.inf, None, 0
    for epoch in range(30):
        model.train()
        for batch in np.array_split(rng.permutation(len(x)), max(1, int(np.ceil(len(x)/64)))):
            opt.zero_grad()
            loss = nn.functional.cross_entropy(model(torch.from_numpy(x[batch])), torch.tensor(labels[batch], dtype=torch.long))
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            score = float(nn.functional.cross_entropy(model(torch.from_numpy(valid)), torch.tensor(valid_labels, dtype=torch.long)))
        if score < best-1e-5:
            best, bad = score, 0
            saved = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        if bad >= 5:
            break
    model.load_state_dict(saved)
    return model, {'epochs': epoch+1, 'validation_logloss': best}


def optimize(scenarios, weights, exposure=1_000_000., budget=150_000.):
    # All amounts EUR. Scenario changes are normalized to decision-date exposure.
    oil, fx = np.expm1(scenarios[:, 0]), np.expm1(-scenarios[:, 1])
    physical = exposure*np.expm1(scenarios[:, 0]-scenarios[:, 1])
    candidates = []
    for hp in (0., .25, .5, .75, 1.):
        for hf in (0., .25, .5, .75, 1.):
            if hp+hf > 1.0:
                continue  # Fixed scarce total hedge-notional capacity.
            hedge_cost = exposure*.001*(hp+hf)
            residual = physical-exposure*(hp*oil+hf*fx)
            for reserve in np.linspace(0, budget, 31):
                if reserve+hedge_cost > budget+1e-8:
                    continue
                shortfall = np.maximum(residual-reserve, 0)
                objective = hedge_cost+.05*HORIZON/252*reserve+2*np.dot(weights, shortfall)
                candidates.append((objective, hp, hf, reserve, hedge_cost))
    return min(candidates)


def run(panel_path, out, seed=42):
    torch.set_num_threads(2)
    raw = pd.read_csv(panel_path, parse_dates=['date']).set_index('date').sort_index()
    # No silent fill; horizon refers to common observed sessions, not fixed calendar days.
    prices = raw[['BRENT','EURUSD']].dropna()
    if (prices <= 0).any().any() or prices.index.has_duplicates:
        raise ValueError('Positive prices and unique dates required')
    logret = np.log(prices).diff()
    features = pd.concat([logret, logret.pow(2).rolling(5).mean().add_suffix('_rv5')], axis=1)
    rows, windows, targets, ends = [], [], [], []
    # At decision close i, information stops i-1; trade prices observed at i.
    for i in range(WINDOW+6, len(prices)-HORIZON):
        x = features.iloc[i-WINDOW:i].to_numpy().T
        if np.isfinite(x).all():
            rows.append(prices.index[i]); windows.append(x)
            targets.append(np.log(prices.iloc[i+HORIZON].to_numpy()/prices.iloc[i].to_numpy()))
            ends.append(prices.index[i+HORIZON])
    dates, label_end = pd.DatetimeIndex(rows), pd.DatetimeIndex(ends)
    x, y = np.asarray(windows, dtype='float32'), np.asarray(targets)
    records, folds = [], []
    probability_rows, calibration_rows, sensitivity_rows = [], [], []
    global_test = np.flatnonzero(dates >= pd.Timestamp('2024-01-01'))[::HORIZON]
    for year in (2024, 2025, 2026):
        validation_start, test_start = pd.Timestamp(year-1,1,1), pd.Timestamp(year,1,1)
        train = np.flatnonzero((dates >= pd.Timestamp('2015-01-01')) & (label_end < validation_start))
        val = np.flatnonzero((dates >= validation_start) & (label_end < test_start))
        test = global_test[(dates[global_test] >= test_start) & (dates[global_test] < pd.Timestamp(year+1,1,1))]
        if min(len(train),len(val),len(test)) < 10:
            continue
        mu, sd = x[train].mean(axis=(0,2)), np.maximum(x[train].std(axis=(0,2)),1e-8)
        z = ((x-mu[None,:,None])/sd[None,:,None]).astype('float32')
        sy = np.maximum(y[train].std(axis=0),1e-8)
        km = KMeans(n_clusters=6, random_state=seed, n_init=10).fit(y[train]/sy)
        labels = km.predict(y/sy)
        count = np.bincount(labels[train], minlength=6)
        prior = count/count.sum()
        # Library contains realized training outcomes only, never test outcomes.
        scenario = y[train]
        models = {}
        tab = LogisticRegression(C=.01, max_iter=1500).fit(z[train].reshape(len(train),-1), labels[train])
        models['tabular'] = tab.predict_proba(z[test].reshape(len(test),-1))
        diagnostics = {}
        for name, visual in [('cnn_1d',False),('cnn_visual',True)]:
            tx, vx, xx = [images(z[ix]) if visual else z[ix] for ix in (train,val,test)]
            net, diag = fit_network(tx,labels[train],vx,labels[val],6,visual,seed)
            with torch.no_grad():
                models[name] = net(torch.from_numpy(xx)).softmax(1).numpy()
            diagnostics[name] = diag
        models['historical'] = np.tile(prior,(len(test),1))
        pr, cr, sr = evaluate_fold(year, dates[test], scenario, labels[train], prior, models, y[test], {'observed_labels': labels[test]})
        probability_rows.extend(pr); calibration_rows.extend(cr); sensitivity_rows.extend(sr)
        print(f'Finished fold {year}', flush=True)
        for j, ix in enumerate(test):
            for name, probs in models.items():
                # Fixed 20% stress/history floor, identical for each model.
                p = .8*probs[j]+.2*prior
                weights = p[labels[train]]/count[labels[train]]
                weights /= weights.sum()
                objective,hp,hf,reserve,cost = optimize(scenario,weights)
                oil, fx = np.expm1(y[ix,0]), np.expm1(-y[ix,1])
                loss = 1e6*(np.expm1(y[ix,0]-y[ix,1])-hp*oil-hf*fx)
                shortage = max(loss-reserve,0.)
                funding = .05*HORIZON/252*reserve
                records.append(dict(date=str(dates[ix].date()),label_end=str(label_end[ix].date()),
                    year=year,model=name,hedge_oil=hp,hedge_fx=hf,reserve_eur=reserve,
                    hedge_cost_eur=cost,funding_eur=funding,residual_loss_eur=loss,
                    shortfall_eur=shortage,total_cost_eur=cost+funding+2*shortage,
                    forecast_objective_eur=objective))
        folds.append(dict(year=year,train_n=len(train),validation_n=len(val),test_n=len(test),
                          train_label_end_max=str(label_end[train].max().date()),
                          validation_label_end_max=str(label_end[val].max().date()),training=diagnostics))
    df = pd.DataFrame(records)
    out.mkdir(parents=True,exist_ok=True)
    df.to_csv(out/'decisions.csv',index=False)
    save_results(out, probability_rows, calibration_rows, sensitivity_rows)
    metrics = {}
    for name,g in df.groupby('model'):
        losses = g.residual_loss_eur.to_numpy()
        tail = losses[losses >= np.quantile(losses,.95)]
        metrics[name] = dict(n=len(g),mean_total_cost_eur=float(g.total_cost_eur.mean()),
            mean_reserve_eur=float(g.reserve_eur.mean()),shortfall_rate=float((g.shortfall_eur>0).mean()),
            mean_shortfall_eur=float(g.shortfall_eur.mean()),realized_tail95_eur=float(tail.mean()),
            mean_hedge_cost_eur=float(g.hedge_cost_eur.mean()),
            action_counts={str(k):int(v) for k,v in g.groupby(['hedge_oil','hedge_fx']).size().items()})
    paired = df.pivot(index='date',columns='model',values='total_cost_eur')
    delta = paired.cnn_visual-paired.historical
    rng = np.random.default_rng(seed)
    # Nonoverlapping ten-session decisions; resample consecutive blocks of 3 decisions.
    boot = []
    for _ in range(2000):
        starts = rng.integers(0,len(delta),size=int(np.ceil(len(delta)/3)))
        indices = np.concatenate([(np.arange(s,s+3)%len(delta)) for s in starts])[:len(delta)]
        boot.append(delta.iloc[indices].mean())
    comparisons = {}
    for comparator in ('historical','tabular','cnn_1d'):
        d = (paired.cnn_visual-paired[comparator]).to_numpy()
        boots=[]
        for _ in range(2000):
            starts=rng.integers(0,len(d),size=int(np.ceil(len(d)/3)))
            ids=np.concatenate([np.arange(s,s+3)%len(d) for s in starts])[:len(d)]
            boots.append(d[ids].mean())
        comparisons[comparator]={'mean_delta_cost_eur':float(d.mean()),'block_ci95':np.quantile(boots,[.025,.975]).tolist()}
    summary = dict(status='exploratory_idealized_capital_optimizer',seed=seed,
        panel_sha256=hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        exposure_eur=1e6,budget_eur=150000,max_combined_hedge_fraction=1.0,horizon_common_observations=HORIZON,
        information_delay_observations=1,metrics=metrics,folds=folds,comparisons=comparisons,
        cnn_minus_historical_cost_eur=float(delta.mean()),
        block_ci95_cost_eur=np.quantile(boot,[.025,.975]).tolist(),
        assumptions=['Idealized spot-index hedges, not executable futures/options P&L.',
          '5% annual funding, 10bp hedge cost, shortage penalty 2, fixed before execution.',
          'Funding uses fixed ten-business-session convention 10/252, not actual calendar accrual.',
          'Budget constrains reserve plus hedge fees; margin requirements unavailable.',
          'One-observation delay is not a verified publication/vintage calendar.',
          'Common observed sessions drop missing price dates; report actual label dates.',
          '2024-2026 historical evaluation is exploratory; no prospective confirmation.',
          'No regulatory capital savings claim; no calibrated ES reserve claim.'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
    return summary


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--panel',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--seed',type=int,default=42)
    args=ap.parse_args()
    run(args.panel,args.out,args.seed)
