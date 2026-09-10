"""Three-stage causal CNN extraction using separate existing Python environments.

prepare: statistical environment; extract: torch environment; heads: statistical.
No network, fallback weights, pre-existing heads, or full-series normalization.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

PATTERNS = ['ascending_channel', 'descending_channel']


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(args):
    import pandas as pd
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from brent_pattern_system.image_encoding import build_multichannel_image
    from brent_pattern_system.patterns import label_price_window
    raw = pd.read_csv(args.prices, parse_dates=['date']).sort_values('date')
    raw = raw.dropna(subset=['BRENT'])
    if raw.date.duplicated().any() or not np.isfinite(raw.BRENT).all() or (raw.BRENT <= 0).any():
        raise ValueError('Invalid observed-price series')
    # Keep pre-2000 windows for initialization; train labels start in 2000.
    starts = [i for i in range(31, len(raw)) if raw.date.iloc[i] >= pd.Timestamp('2000-01-01')]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    images = np.lib.format.open_memmap(out/'images.npy', mode='w+', dtype='uint8', shape=(len(starts),160,160,3))
    rows = []
    for k, i in enumerate(starts):
        window = raw.iloc[i-31:i+1]
        images[k] = build_multichannel_image(window, 'BRENT', ['BRENT'], 160, output_dtype=np.uint8)
        label = label_price_window(window.BRENT.to_numpy(), threshold=.30)[0]
        rows.append({'date': raw.date.iloc[i], 'window_start': raw.date.iloc[i-31], 'label': label})
    images.flush()
    pd.DataFrame(rows).to_csv(out/'windows.csv', index=False)
    code = Path(__file__).resolve().parents[2]/'brent_pattern_system'
    manifest = {'source_sha256': digest(args.prices), 'window_length': 32, 'image_size': 160,
                'calendar': 'observed_no_fill', 'n': len(rows), 'threshold': .30,
                'images_sha256': digest(out/'images.npy'), 'windows_sha256': digest(out/'windows.csv'),
                'transform_sha256': {name: digest(code/name) for name in ['image_encoding.py','feature_engineering.py','patterns.py']}}
    (out/'prepare.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Prepared {len(rows)} causal images', flush=True)


def extract(args):
    import torch
    import torchvision
    from torchvision.models import efficientnet_b1
    out = Path(args.out)
    manifest = json.loads((out/'prepare.json').read_text())
    if digest(out/'images.npy') != manifest['images_sha256']:
        raise ValueError('Image hash mismatch')
    torch.manual_seed(1729)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(4)
    model = efficientnet_b1(weights=None)
    model.load_state_dict(torch.load(args.weights, map_location='cpu', weights_only=True), strict=True)
    model.classifier = torch.nn.Identity()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device).eval().requires_grad_(False)
    images = np.load(out/'images.npy', mmap_mode='r')
    feature = np.lib.format.open_memmap(out/'embeddings.npy', mode='w+', dtype='float32', shape=(len(images),1280))
    mean = torch.tensor([.485,.456,.406], device=device).view(1,3,1,1)
    std = torch.tensor([.229,.224,.225], device=device).view(1,3,1,1)
    with torch.inference_mode():
        for start in range(0, len(images), 32):
            batch = torch.from_numpy(np.array(images[start:start+32])).permute(0,3,1,2).to(device).float()/255
            feature[start:start+32] = model((batch-mean)/std).cpu().numpy()
            if start % 1024 == 0:
                print(f'CNN {start}/{len(images)}', flush=True)
    feature.flush()
    manifest.update({'weights_sha256': digest(args.weights), 'weights_file': Path(args.weights).name,
                     'architecture': 'torchvision.efficientnet_b1', 'backbone_frozen': True,
                     'weight_origin': 'local ImageNet checkpoint; retrospective fixed representation',
                     'torch': torch.__version__, 'torchvision': torchvision.__version__,
                     'device': str(device), 'embeddings_sha256': digest(out/'embeddings.npy')})
    (out/'extract.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Extraction complete', flush=True)


def heads(args):
    import pandas as pd
    import sklearn
    import joblib
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    out = Path(args.out)
    manifest = json.loads((out/'extract.json').read_text())
    for name, key in [('windows.csv','windows_sha256'),('embeddings.npy','embeddings_sha256')]:
        if digest(out/name) != manifest[key]:
            raise ValueError(f'{name} hash mismatch')
    windows = pd.read_csv(out/'windows.csv', parse_dates=['date','window_start'])
    features = np.load(out/'embeddings.npy')
    predictions, folds = [], []
    for year in range(2005, windows.date.max().year+1):
        te = windows.date.dt.year == year
        if not te.any():
            continue
        # Disjoint CNN label/image windows at annual fold boundary.
        boundary = windows.loc[te, 'window_start'].min()
        tr = windows.date < boundary
        if tr.sum() < 500:
            raise ValueError('Insufficient training history')
        row = windows.loc[te, ['date','window_start']].copy()
        row['head_train_end'] = windows.loc[tr, 'date'].max()
        row['fold_start'] = windows.loc[te, 'date'].min()
        models = {}
        for pat in PATTERNS:
            y = (windows.label == pat).astype(int)
            if y[tr].nunique() != 2:
                raise ValueError('Head training requires both classes')
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                clf = LogisticRegression(C=1, max_iter=4000, class_weight='balanced', random_state=1729).fit(features[tr], y[tr])
            row['prob_'+pat] = clf.predict_proba(features[te])[:,1]
            models[pat] = clf
        model_path = out/f'heads_{year}.joblib'
        joblib.dump(models, model_path)
        row['head_sha256'] = digest(model_path)
        predictions.append(row)
        folds.append({'year': year, 'train_n': int(tr.sum()), 'predict_n': int(te.sum()),
                      'train_end': str(windows.loc[tr,'date'].max()), 'head_sha256': digest(model_path)})
        print(f'Heads {year}: train={tr.sum()} predict={te.sum()}', flush=True)
    pd.concat(predictions).to_csv(out/'causal_predictions.csv', index=False)
    manifest.update({'prediction_sha256': digest(out/'causal_predictions.csv'), 'head_folds': folds,
                     'sklearn': sklearn.__version__, 'crossfit': 'annual_expanding_disjoint_windows',
                     'code_sha256': digest(__file__),
                     'historical_deployability': False,
                     'limitations': ['Historical representation chosen retrospectively.',
                                     'Weak geometric labels; scores are not calibrated event probabilities.']})
    (out/'provenance.json').write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['prepare','extract','heads'])
    p.add_argument('--prices')
    p.add_argument('--weights')
    p.add_argument('--out', required=True)
    args = p.parse_args()
    globals()[args.stage](args)
