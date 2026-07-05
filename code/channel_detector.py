"""Detector de canal (solo-precio) — entrenamiento, evaluación out-of-time e inferencia.

Empaqueta el mejor modelo validado del proyecto: imagen 3-canal SOLO-PRECIO
(ch0 GASF del nivel, ch1 GADF de retornos, ch2 mapa del propio Brent)
-> EfficientNet-B1 (pesos ImageNet, congelado como extractor de features)
-> una cabeza de regresión logística por patrón (canal ascendente / descendente).

Las etiquetas provienen del etiquetador débil geométrico del paquete
(`brent_pattern_system.patterns.label_price_window`), de modo que el detector es
autocontenido: solo necesita la serie de precios del Brent.

Uso:
  # entrenar las cabezas sobre el bundle de /data y guardar el artefacto:
  python channel_detector.py train --config config_codeocean.yaml

  # entrenar con evaluación out-of-time (train <= cutoff, test > cutoff);
  # reproduce las métricas de results/reports/detector_solo_precio.json:
  python channel_detector.py train --config config_codeocean.yaml --cutoff 2020-08-20

  # predecir sobre una serie de precios Brent (CSV con columnas date,BRENT):
  python channel_detector.py predict --prices /ruta/brent.csv --out preds.csv

Artefacto entregado: results/models/detector_canal_heads.joblib (`predict` lo
usa directamente; se puede regenerar con `train`).

Requiere scikit-learn y joblib además de las dependencias del paquete
(ver environment/requirements.txt).
"""
from __future__ import annotations

import argparse
import json
import os

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression

from brent_pattern_system.image_encoding import build_multichannel_image
from brent_pattern_system.patterns import label_price_window
from brent_pattern_system.torch_model import BrentTorchModel, _normalize_image

LOOKBACK, IMG, MIN_CONF = 32, 160, 0.30
PATTERNS = ["ascending_channel", "descending_channel"]


def _results_dir() -> str:
    """Directorio de resultados: /results en Code Ocean, results/ del repo en local.

    Sobreescribible con la variable de entorno RESULTS_DIR.
    """
    env = os.environ.get("RESULTS_DIR")
    if env:
        return env
    if os.path.isdir("/results"):
        return "/results"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "results")


def heads_path() -> str:
    art = os.path.join(_results_dir(), "models")
    os.makedirs(art, exist_ok=True)
    return os.path.join(art, "detector_canal_heads.joblib")


def log(*a):
    print(*a, flush=True)


_backbone = None


def backbone():
    global _backbone
    if _backbone is None:
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _backbone = (BrentTorchModel(pretrained=True).to(dev).eval(), dev)
    return _backbone


def price_features(prices: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Features del backbone (imagen solo-precio) para cada ventana de la serie.

    Devuelve (F, idxs) donde F[k] corresponde a la ventana que TERMINA en el
    índice idxs[k] (exclusivo), es decir prices[idxs[k]-LOOKBACK : idxs[k]].
    """
    model, dev = backbone()
    idxs = [e for e in range(LOOKBACK, len(prices) + 1) if not np.isnan(prices[e - LOOKBACK : e]).any()]
    imgs = np.empty((len(idxs), IMG, IMG, 3), np.uint8)
    for k, e in enumerate(idxs):
        wdf = pd.DataFrame({"date": range(LOOKBACK), "BRENT": prices[e - LOOKBACK : e]})
        imgs[k] = np.clip(build_multichannel_image(wdf, "BRENT", ["BRENT"], IMG), 0, 255).astype(np.uint8)
    outs = []
    with torch.no_grad():
        for i in range(0, len(imgs), 128):
            b = torch.stack([_normalize_image(imgs[j]) for j in range(i, min(i + 128, len(imgs)))]).to(dev)
            outs.append(model.backbone(b).float().cpu().numpy())
    return np.concatenate(outs) if outs else np.empty((0, 0)), idxs


def load_brent(path: str) -> pd.Series:
    """Carga una serie de precios Brent desde CSV (columnas fecha + precio).

    Reindexa a frecuencia de días hábiles (B) con forward-fill, coherente con
    la frecuencia del bundle de entrenamiento.
    """
    df = pd.read_csv(path)
    dcol = [c for c in df.columns if c.lower() in ("date", "fecha", "observation_date")][0]
    bcol = [c for c in df.columns if c.upper() in ("BRENT", "DCOILBRENTEU", "VALUE", "CLOSE")][0]
    df[dcol] = pd.to_datetime(df[dcol])
    df = df[[dcol, bcol]].dropna().sort_values(dcol)
    s = df.set_index(dcol)[bcol].astype(float)
    s = s.reindex(pd.bdate_range(s.index.min(), s.index.max())).ffill()
    return s


def _binary_metrics(y: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> dict:
    from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

    pred = (prob >= threshold).astype(int)
    out = {
        "auc": float(roc_auc_score(y, prob)) if len(np.unique(y)) > 1 else float("nan"),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "n": int(len(y)),
        "base_rate": float(np.mean(y)),
    }
    return out


def cmd_train(args):
    from brent_pattern_system.config import load_config
    from brent_pattern_system.series_bundle import load_series_bundle

    cfg = load_config(args.config)
    bundle = load_series_bundle(cfg)
    prices_s = bundle.raw_wide[bundle.price_col].astype(float)
    prices = prices_s.to_numpy()
    dates = prices_s.index

    log(f"[train] serie {bundle.price_col}: {len(prices)} observaciones "
        f"({dates.min().date()} → {dates.max().date()})")

    F, idxs = price_features(prices)
    log(f"[train] {len(idxs)} ventanas de {LOOKBACK} días; features backbone {F.shape}")

    # Etiquetado débil geométrico sobre la MISMA ventana usada para la imagen.
    labels = np.array([
        label_price_window(prices[e - LOOKBACK : e], threshold=MIN_CONF)[0] for e in idxs
    ])
    end_dates = pd.DatetimeIndex([dates[e - 1] for e in idxs])

    if args.cutoff:
        cutoff = pd.Timestamp(args.cutoff)
        tr = end_dates <= cutoff
        te = ~tr
        log(f"[train] out-of-time cutoff={cutoff.date()}: n_train={int(tr.sum())}, n_test={int(te.sum())}")
    else:
        tr = np.ones(len(idxs), dtype=bool)
        te = np.zeros(len(idxs), dtype=bool)

    heads, report = {}, {}
    for pat in PATTERNS:
        y = (labels == pat).astype(int)
        clf = LogisticRegression(max_iter=4000, class_weight="balanced").fit(F[tr], y[tr])
        heads[pat] = clf
        log(f"  cabeza '{pat}': positivos train={int(y[tr].sum())}/{int(tr.sum())}")
        if te.any():
            m = _binary_metrics(y[te], clf.predict_proba(F[te])[:, 1])
            m["cutoff"] = str(pd.Timestamp(args.cutoff).date())
            report[pat] = m
            log(f"    out-of-time: AUC={m['auc']:.4f} F1={m['f1']:.4f} "
                f"prec={m['precision']:.4f} rec={m['recall']:.4f} (n={m['n']})")

    out_path = args.out or heads_path()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    joblib.dump({"heads": heads, "lookback": LOOKBACK, "img": IMG,
                 "patterns": PATTERNS, "min_conf": MIN_CONF}, out_path)
    log(f"[train] artefacto guardado -> {out_path}")

    if report:
        rep_path = os.path.join(_results_dir(), "reports", "detector_solo_precio.json")
        os.makedirs(os.path.dirname(rep_path), exist_ok=True)
        with open(rep_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        log(f"[train] métricas out-of-time -> {rep_path}")


def cmd_predict(args):
    bundle = joblib.load(args.model or heads_path())
    heads = bundle["heads"]
    s = load_brent(args.prices)
    F, idxs = price_features(s.to_numpy())
    dates = [s.index[e - 1] for e in idxs]
    out = pd.DataFrame({"date": [d.date() for d in dates]})
    for pat in bundle["patterns"]:
        out[f"prob_{pat}"] = np.round(heads[pat].predict_proba(F)[:, 1], 4)
    out["pred_canal"] = np.where(out["prob_ascending_channel"] > out["prob_descending_channel"],
                                 "ascendente", "descendente")
    out["confianza"] = out[[f"prob_{p}" for p in bundle["patterns"]]].max(axis=1)
    out.to_csv(args.out, index=False)
    log(f"[predict] {len(out)} ventanas -> {args.out}")
    log(out.tail(8).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="entrena las cabezas logísticas (opcional: eval out-of-time)")
    t.add_argument("--config", default="config_codeocean.yaml")
    t.add_argument("--cutoff", default=None, help="fecha de corte out-of-time (YYYY-MM-DD)")
    t.add_argument("--out", default=None, help="ruta del artefacto .joblib (por defecto results/models/)")
    p = sub.add_parser("predict", help="inferencia sobre un CSV de precios Brent")
    p.add_argument("--prices", required=True)
    p.add_argument("--model", default=None, help="ruta del artefacto .joblib")
    p.add_argument("--out", default="channel_predictions.csv")
    args = ap.parse_args()
    (cmd_train if args.cmd == "train" else cmd_predict)(args)
