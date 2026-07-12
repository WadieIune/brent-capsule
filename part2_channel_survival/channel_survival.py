"""part2_channel_survival — Supervivencia del canal (2ª pata), módulo independiente.

Extiende el detector de canal validado (`code/channel_detector.py`) hacia el
modelado DINÁMICO del canal ("túnel"): una vez detectada de forma robusta una
geometría de canal (ascendente / descendente) sobre una ventana de 32 días, este
módulo responde a tres preguntas que el detector estático no aborda:

  Q2 (núcleo) — ¿cuánto vivirá el canal?  Análisis de supervivencia del episodio:
      curva P(T > k) con Kaplan-Meier (baseline), Cox PH, Random Survival Forest
      y XGBoost-AFT. Métricas: C-index (Harrell), Integrated Brier Score.
  Q1 — ¿se formará un canal en los próximos N días?  Clasificación binaria sobre
      días SIN canal activo (target = aparece un canal en t+1..t+N).
  Q3 — ¿por dónde romperá?  Clasificación de la dirección de ruptura (arriba/abajo)
      sobre los episodios que efectivamente rompen.

Este módulo es AUTOCONTENIDO: no importa el paquete `brent_pattern_system`; el
etiquetador débil se vendoriza en `patterns_min.py`. Solo necesita la serie de
precios del Brent, por lo que puede entrenarse en cualquier máquina (incluida GPU)
sin arrastrar torch ni el resto del pipeline. Las covariables son features
geométricas y estadísticas (pendiente, R², anchura, ATR, posición en el canal…).

DEFINICIÓN DE RUPTURA: se congela la geometría del canal en la detección (línea
central por regresión de la ventana + bandas a ±m·σ_resid) y se proyecta hacia
delante; hay ruptura cuando el cierre supera la banda proyectada más una
tolerancia proporcional al ATR (proxy close-only), evitando falsas rupturas por
ruido. La duración es el nº de sesiones hasta la ruptura; los episodios aún vivos
al final de la muestra quedan censurados por la derecha.

Uso:
  # dataset por defecto = ../data/brent_fred_daily.csv (fuente FRED del proyecto)
  python channel_survival.py --cutoff 2020-08-20

  # entrenar XGBoost en GPU (RSF/Cox son CPU):
  python channel_survival.py --cutoff 2020-08-20 --gpu

  # con otra serie de precios (CSV con columnas date,BRENT):
  python channel_survival.py --prices /ruta/brent.csv --cutoff 2020-08-20

Salidas (en outputs/ del módulo salvo OUT_DIR):
  - channel_survival.json               (métricas de Q1/Q2/Q3 + parámetros)
  - channel_survival_resultados.xlsx    (Excel multi-hoja)
  - channel_survival_episodes.csv       (tabla de episodios con features)

Dependencias (ver requirements.txt): scikit-learn, scipy, lifelines,
scikit-survival, xgboost, pandas, numpy, openpyxl.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from patterns_min import find_turning_points, label_price_window, smooth_series

# --- Parámetros por defecto ---------------------------------------------------
LOOKBACK = 32           # ventana de detección (días de negociación)
MIN_CONF = 0.30         # umbral del etiquetador débil para confirmar canal
BAND_MULT = 2.0         # semi-anchura de banda = BAND_MULT * desviación de residuos
ATR_WIN = 14            # ventana del ATR (proxy close-only)
TOL_ATR = 1.0           # tolerancia de ruptura = TOL_ATR * ATR (evita falsas rupturas)
CONFIRM = 1             # sesiones consecutivas fuera de banda para confirmar ruptura
MIN_LIFE = 1            # descarta episodios censurados de vida < MIN_LIFE
HORIZONS = (5, 10, 20)  # horizontes P(T > k) reportados
FORM_HORIZON = 10       # N para Q1 (¿se formará un canal en los próximos N días?)

CHANNEL_LABELS = ("ascending_channel", "descending_channel")

FEATURES: List[str] = [
    "dir_asc",          # 1 canal ascendente, 0 descendente
    "slope_norm",       # pendiente de la línea central / nivel medio
    "r2",               # bondad de ajuste de la línea central
    "resid_norm",       # desviación de residuos / nivel medio
    "band_width",       # anchura relativa del canal (2·m·σ / nivel medio)
    "atr_norm",         # ATR / precio en la detección
    "vol20",            # desviación de los últimos 20 retornos
    "last_ret",         # último retorno diario
    "accel",            # aceleración (pendiente de los últimos 10 retornos)
    "n_turn",           # nº de pivotes (min+max) en la ventana
    "pos_in_channel",   # posición del precio dentro del canal en [0,1]
]

XGB_SCALE = 1.20  # escala de la distribución AFT (log-normal)


def log(*a):
    print(*a, flush=True)


def _module_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _out_dir() -> str:
    """Directorio de salidas: OUT_DIR si se define, si no outputs/ del módulo."""
    env = os.environ.get("OUT_DIR")
    return env if env else os.path.join(_module_dir(), "outputs")


def _default_prices_path() -> str:
    repo_root = os.path.dirname(_module_dir())
    return os.path.join(repo_root, "data", "brent_fred_daily.csv")


def load_brent(path: str) -> pd.Series:
    """Carga la serie Brent desde un CSV (columnas fecha + precio) a días hábiles (B)."""
    df = pd.read_csv(path)
    dcol = [c for c in df.columns if c.lower() in ("date", "fecha", "observation_date")][0]
    bcol = [c for c in df.columns if c.upper() in ("BRENT", "DCOILBRENTEU", "VALUE", "CLOSE")][0]
    df[dcol] = pd.to_datetime(df[dcol])
    df = df[[dcol, bcol]].dropna().sort_values(dcol)
    s = df.set_index(dcol)[bcol].astype(float)
    s = s.reindex(pd.bdate_range(s.index.min(), s.index.max())).ffill()
    return s


# --- Geometría del canal ------------------------------------------------------
def _fit_line(y: np.ndarray) -> Tuple[float, float, float, float]:
    """Ajuste lineal: devuelve (slope, intercept, resid_std, r2) en coordenadas locales."""
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    resid = y - fitted
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(slope), float(intercept), float(np.std(resid)), float(r2)


def _atr_like(prices: np.ndarray, win: int = ATR_WIN) -> np.ndarray:
    """ATR aproximado con solo cierres: media móvil de |Δcierre| (en unidades de precio)."""
    tr = np.abs(np.diff(prices, prepend=prices[0]))
    return pd.Series(tr).rolling(win, min_periods=1).mean().to_numpy()


def _episode_features(
    prices: np.ndarray,
    e0: int,
    slope: float,
    intercept: float,
    resid_std: float,
    r2: float,
    atr: np.ndarray,
    direction: str,
) -> Dict[str, float]:
    """Features geométricas/estadísticas en el instante de detección (índice e0)."""
    window = prices[e0 - LOOKBACK + 1 : e0 + 1]
    level = float(np.mean(window)) or 1.0
    rets = np.diff(window) / window[:-1]
    vol20 = float(np.std(rets[-20:])) if len(rets) >= 2 else 0.0
    last_ret = float(rets[-1]) if len(rets) else 0.0
    accel = float(np.polyfit(np.arange(len(rets[-10:])), rets[-10:], 1)[0]) if len(rets) >= 3 else 0.0
    maxima, minima = find_turning_points(smooth_series(window))
    n_turn = int(len(maxima) + len(minima))
    local_x = LOOKBACK - 1
    center = intercept + slope * local_x
    upper = center + BAND_MULT * resid_std
    lower = center - BAND_MULT * resid_std
    span = (upper - lower) or 1e-8
    pos = float(np.clip((prices[e0] - lower) / span, 0.0, 1.0))
    return {
        "dir_asc": 1.0 if direction == "ascending_channel" else 0.0,
        "slope_norm": slope / level,
        "r2": r2,
        "resid_norm": resid_std / level,
        "band_width": (2.0 * BAND_MULT * resid_std) / level,
        "atr_norm": float(atr[e0] / prices[e0]) if prices[e0] else 0.0,
        "vol20": vol20,
        "last_ret": last_ret,
        "accel": accel,
        "n_turn": float(n_turn),
        "pos_in_channel": pos,
    }


def extract_episodes(
    prices: np.ndarray,
    dates: pd.DatetimeIndex,
    lookback: int = LOOKBACK,
    min_conf: float = MIN_CONF,
    band_mult: float = BAND_MULT,
    tol_atr: float = TOL_ATR,
    confirm: int = CONFIRM,
    min_life: int = MIN_LIFE,
) -> pd.DataFrame:
    """Extrae episodios de canal NO solapados con su duración hasta la ruptura."""
    n = len(prices)
    atr = _atr_like(prices)
    episodes: List[Dict[str, object]] = []

    t = lookback  # fin de ventana exclusivo -> última obs en el índice t-1
    while t <= n:
        window = prices[t - lookback : t]
        if np.isnan(window).any():
            t += 1
            continue
        label, conf, _ = label_price_window(window, threshold=min_conf)
        if label not in CHANNEL_LABELS:
            t += 1
            continue

        sm = smooth_series(window)
        slope, intercept, resid_std, r2 = _fit_line(sm)
        e0 = t - 1  # índice absoluto de la última observación de la ventana

        broke, bdir, confirmed, last_j = False, None, 0, e0
        j = t
        while j < n:
            if np.isnan(prices[j]):
                break
            local_x = (lookback - 1) + (j - e0)
            center = intercept + slope * local_x
            upper = center + band_mult * resid_std
            lower = center - band_mult * resid_std
            tol = tol_atr * (atr[j] if not np.isnan(atr[j]) else resid_std)
            up_break = prices[j] > upper + tol
            dn_break = prices[j] < lower - tol
            if up_break or dn_break:
                confirmed += 1
                if confirmed >= confirm:
                    broke, bdir, last_j = True, ("up" if up_break else "down"), j
                    break
            else:
                confirmed = 0
            last_j = j
            j += 1

        duration = int(last_j - e0)
        event = 1 if broke else 0
        if event == 1 or duration >= min_life:
            feats = _episode_features(prices, e0, slope, intercept, resid_std, r2, atr, label)
            episodes.append({
                "start_date": dates[e0],
                "end_date": dates[last_j],
                "direction": "ascending" if label == "ascending_channel" else "descending",
                "conf_detection": float(conf),
                "duration": max(duration, 0),
                "event": event,
                "breakout_dir": bdir if bdir else "",
                **feats,
            })
        t = last_j + 2  # reanuda el escaneo tras la ruptura (episodios no solapados)

    df = pd.DataFrame(episodes)
    if not df.empty:
        df = df.sort_values("start_date").reset_index(drop=True)
    return df


def is_channel_flags(
    prices: np.ndarray, lookback: int = LOOKBACK, min_conf: float = MIN_CONF
) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, float]]]:
    """Para cada fin de ventana válido devuelve (idxs, is_channel, features por ventana)."""
    n = len(prices)
    atr = _atr_like(prices)
    idxs: List[int] = []
    flags: List[int] = []
    feats: List[Dict[str, float]] = []
    for t in range(lookback, n + 1):
        window = prices[t - lookback : t]
        if np.isnan(window).any():
            continue
        e0 = t - 1
        label, _, _ = label_price_window(window, threshold=min_conf)
        sm = smooth_series(window)
        slope, intercept, resid_std, r2 = _fit_line(sm)
        direction = label if label in CHANNEL_LABELS else "ascending_channel"
        idxs.append(e0)
        flags.append(1 if label in CHANNEL_LABELS else 0)
        feats.append(_episode_features(prices, e0, slope, intercept, resid_std, r2, atr, direction))
    return np.asarray(idxs, dtype=int), np.asarray(flags, dtype=int), feats


# --- Utilidades de escalado y métricas ---------------------------------------
def _standardize(train: np.ndarray, test: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mu = train.mean(axis=0)
    sd = train.std(axis=0)
    sd[sd == 0] = 1.0
    return (train - mu) / sd, (test - mu) / sd


def _binary_metrics(y: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> Dict[str, float]:
    from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

    pred = (prob >= threshold).astype(int)
    return {
        "auc": float(roc_auc_score(y, prob)) if len(np.unique(y)) > 1 else float("nan"),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "accuracy": float(np.mean(pred == y)),
        "base_rate": float(np.mean(y)),
        "n": int(len(y)),
    }


def _xgb_aft_params(gpu: bool) -> dict:
    params = {
        "objective": "survival:aft", "eval_metric": "aft-nloglik",
        "aft_loss_distribution": "normal", "aft_loss_distribution_scale": XGB_SCALE,
        "tree_method": "hist", "max_depth": 3, "eta": 0.05,
        "subsample": 0.8, "colsample_bynode": 0.8, "seed": 42,
    }
    if gpu:
        params["device"] = "cuda"
    return params


# --- Q2: supervivencia del canal ---------------------------------------------
def run_survival(episodes: pd.DataFrame, cutoff: Optional[str], gpu: bool = False) -> Dict[str, object]:
    """Ajusta KM (baseline) + Cox + RSF + XGB-AFT y evalúa C-index, IBS y P(T>k)."""
    from scipy.stats import norm

    out: Dict[str, object] = {"horizons": list(HORIZONS)}
    if episodes.empty or len(episodes) < 20:
        out["error"] = f"muestras insuficientes de episodios ({len(episodes)})"
        return out

    if cutoff:
        c = pd.Timestamp(cutoff)
        tr = episodes["start_date"] <= c
    else:  # 70% temporal si no se da cutoff
        k = int(len(episodes) * 0.70)
        tr = pd.Series(np.arange(len(episodes)) < k, index=episodes.index)
    te = ~tr

    Xtr = episodes.loc[tr, FEATURES].to_numpy(dtype=float)
    Xte = episodes.loc[te, FEATURES].to_numpy(dtype=float)
    ttr = episodes.loc[tr, "duration"].to_numpy(dtype=float).clip(min=0.5)
    tte = episodes.loc[te, "duration"].to_numpy(dtype=float).clip(min=0.5)
    etr = episodes.loc[tr, "event"].to_numpy(dtype=int)
    ete = episodes.loc[te, "event"].to_numpy(dtype=int)

    out["n_train"], out["n_test"] = int(tr.sum()), int(te.sum())
    out["events_train"], out["events_test"] = int(etr.sum()), int(ete.sum())
    if tr.sum() < 15 or te.sum() < 8 or etr.sum() < 8 or ete.sum() < 4:
        out["error"] = "muestras/eventos insuficientes tras el split temporal"
        return out

    Xtr_s, Xte_s = _standardize(Xtr, Xte)
    models: Dict[str, Dict[str, object]] = {}
    surv_curves: Dict[str, List[float]] = {}

    # Baseline Kaplan-Meier (marginal, sin covariables) sobre el train.
    try:
        from lifelines import KaplanMeierFitter

        kmf = KaplanMeierFitter().fit(ttr, etr)
        surv_curves["kaplan_meier"] = [float(kmf.predict(h)) for h in HORIZONS]
        kmf_te = KaplanMeierFitter().fit(tte, ete)
        surv_curves["kaplan_meier_test_obs"] = [float(kmf_te.predict(h)) for h in HORIZONS]
        models["kaplan_meier"] = {"note": "baseline marginal (C-index no aplica)"}
    except Exception as exc:  # pragma: no cover
        models["kaplan_meier"] = {"error": str(exc)}

    def _cindex(risk: np.ndarray) -> float:
        from sksurv.metrics import concordance_index_censored

        return float(concordance_index_censored(ete.astype(bool), tte, risk)[0])

    # Cox Proportional Hazards (lifelines, CPU).
    try:
        from lifelines import CoxPHFitter

        df_tr = pd.DataFrame(Xtr_s, columns=FEATURES)
        df_tr["duration"], df_tr["event"] = ttr, etr
        cph = CoxPHFitter(penalizer=0.1).fit(df_tr, "duration", "event")
        df_te = pd.DataFrame(Xte_s, columns=FEATURES)
        risk = cph.predict_partial_hazard(df_te).to_numpy().ravel()
        sf = cph.predict_survival_function(df_te, times=list(HORIZONS))
        surv_curves["cox"] = [float(sf.loc[h].mean()) for h in HORIZONS]
        models["cox"] = {"c_index": _cindex(risk)}
    except Exception as exc:  # pragma: no cover
        models["cox"] = {"error": str(exc)}

    # Random Survival Forest (scikit-survival, CPU).
    try:
        from sksurv.ensemble import RandomSurvivalForest
        from sksurv.util import Surv

        y_tr = Surv.from_arrays(etr.astype(bool), ttr)
        rsf = RandomSurvivalForest(
            n_estimators=300, min_samples_leaf=8, max_features="sqrt",
            n_jobs=-1, random_state=42,
        ).fit(Xtr_s, y_tr)
        risk = rsf.predict(Xte_s)
        fns = rsf.predict_survival_function(Xte_s, return_array=False)
        surv_curves["rsf"] = [float(np.mean([fn(h) for fn in fns])) for h in HORIZONS]
        models["rsf"] = {"c_index": _cindex(risk)}
    except Exception as exc:  # pragma: no cover
        models["rsf"] = {"error": str(exc)}

    # XGBoost Accelerated Failure Time (GPU si --gpu).
    try:
        import xgboost as xgb

        lower = ttr.copy()
        upper = np.where(etr == 1, ttr, np.inf)
        dtr = xgb.DMatrix(Xtr_s)
        dtr.set_float_info("label_lower_bound", lower)
        dtr.set_float_info("label_upper_bound", upper)
        bst = xgb.train(_xgb_aft_params(gpu), dtr, num_boost_round=200)
        pred_time = np.clip(bst.predict(xgb.DMatrix(Xte_s)), 1e-3, None)
        mu = np.log(pred_time)
        surv_curves["xgb_aft"] = [
            float(np.mean(1.0 - norm.cdf((np.log(h) - mu) / XGB_SCALE))) for h in HORIZONS
        ]
        models["xgb_aft"] = {"c_index": _cindex(-pred_time), "device": "cuda" if gpu else "cpu"}
    except Exception as exc:  # pragma: no cover
        models["xgb_aft"] = {"error": str(exc)}

    # Integrated Brier Score (sksurv) para los modelos con curva de supervivencia.
    try:
        from sksurv.metrics import integrated_brier_score
        from sksurv.util import Surv

        y_tr = Surv.from_arrays(etr.astype(bool), ttr)
        y_te = Surv.from_arrays(ete.astype(bool), tte)
        lo, hi = float(tte.min()), float(tte.max())
        grid = np.array([h for h in HORIZONS if lo < h < hi], dtype=float)
        if grid.size >= 2:
            for name in ("cox", "rsf", "xgb_aft"):
                if name in models and "error" not in models[name]:
                    try:
                        probs = _survival_matrix(name, Xtr_s, Xte_s, ttr, etr, grid, gpu)
                        if probs is not None:
                            models[name]["integrated_brier_score"] = float(
                                integrated_brier_score(y_tr, y_te, probs, grid)
                            )
                    except Exception as exc:  # pragma: no cover
                        models[name]["ibs_error"] = str(exc)
    except Exception as exc:  # pragma: no cover
        out["ibs_error"] = str(exc)

    out["models"] = models
    out["survival_curves"] = surv_curves
    return out


def _survival_matrix(name, Xtr_s, Xte_s, ttr, etr, grid, gpu) -> Optional[np.ndarray]:
    """Matriz (n_test, len(grid)) de S(t) para el IBS, recalculada por modelo."""
    from scipy.stats import norm

    if name == "cox":
        from lifelines import CoxPHFitter

        df_tr = pd.DataFrame(Xtr_s, columns=FEATURES)
        df_tr["duration"], df_tr["event"] = ttr, etr
        cph = CoxPHFitter(penalizer=0.1).fit(df_tr, "duration", "event")
        sf = cph.predict_survival_function(pd.DataFrame(Xte_s, columns=FEATURES), times=list(grid))
        return sf.to_numpy().T
    if name == "rsf":
        from sksurv.ensemble import RandomSurvivalForest
        from sksurv.util import Surv

        rsf = RandomSurvivalForest(
            n_estimators=300, min_samples_leaf=8, max_features="sqrt",
            n_jobs=-1, random_state=42,
        ).fit(Xtr_s, Surv.from_arrays(etr.astype(bool), ttr))
        fns = rsf.predict_survival_function(Xte_s, return_array=False)
        return np.array([[fn(t) for t in grid] for fn in fns])
    if name == "xgb_aft":
        import xgboost as xgb

        lower = ttr.copy()
        upper = np.where(etr == 1, ttr, np.inf)
        dtr = xgb.DMatrix(Xtr_s)
        dtr.set_float_info("label_lower_bound", lower)
        dtr.set_float_info("label_upper_bound", upper)
        bst = xgb.train(_xgb_aft_params(gpu), dtr, num_boost_round=200)
        mu = np.log(np.clip(bst.predict(xgb.DMatrix(Xte_s)), 1e-3, None))
        return np.column_stack([1.0 - norm.cdf((np.log(t) - mu) / XGB_SCALE) for t in grid])
    return None


# --- Q1: formación futura de un canal -----------------------------------------
def run_formation(
    prices: np.ndarray, dates: pd.DatetimeIndex, cutoff: Optional[str],
    horizon: int = FORM_HORIZON, gpu: bool = False,
) -> Dict[str, object]:
    """¿Aparecerá un canal en los próximos `horizon` días desde una ventana sin canal?"""
    idxs, flags, feats = is_channel_flags(prices)
    out: Dict[str, object] = {"horizon": horizon}
    if len(idxs) < 200:
        out["error"] = "muestras insuficientes"
        return out

    y = np.zeros(len(idxs), dtype=int)
    for k in range(len(idxs)):
        fut = flags[k + 1 : k + 1 + horizon]
        y[k] = int(fut.max()) if fut.size else 0
    keep = flags == 0  # solo días SIN canal activo hoy
    X = pd.DataFrame(feats)[FEATURES].to_numpy(dtype=float)[keep]
    y = y[keep]
    ed = pd.DatetimeIndex([dates[i] for i in idxs])[keep]

    return _classify_temporal(X, y, ed, cutoff, gpu)


# --- Q3: dirección de ruptura -------------------------------------------------
def run_direction(episodes: pd.DataFrame, cutoff: Optional[str], gpu: bool = False) -> Dict[str, object]:
    """Entre los episodios que ROMPEN, ¿la ruptura es alcista (1) o bajista (0)?"""
    br = episodes[episodes["event"] == 1].copy()
    out: Dict[str, object] = {}
    if len(br) < 30:
        out["error"] = f"pocos episodios con ruptura ({len(br)})"
        return out
    X = br[FEATURES].to_numpy(dtype=float)
    y = (br["breakout_dir"] == "up").astype(int).to_numpy()
    ed = pd.DatetimeIndex(br["start_date"].to_numpy())
    return _classify_temporal(X, y, ed, cutoff, gpu)


def _classify_temporal(
    X: np.ndarray, y: np.ndarray, dates: pd.DatetimeIndex, cutoff: Optional[str], gpu: bool = False
) -> Dict[str, object]:
    """Logistic + XGBoost con split temporal; baseline = tasa base (clase mayoritaria)."""
    if cutoff:
        tr = dates <= pd.Timestamp(cutoff)
    else:
        k = int(len(X) * 0.70)
        tr = np.arange(len(X)) < k
    te = ~tr
    out: Dict[str, object] = {"n_train": int(tr.sum()), "n_test": int(te.sum())}
    if tr.sum() < 30 or te.sum() < 15 or len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
        out["error"] = "split temporal sin suficientes casos/clases"
        return out

    Xtr, Xte = _standardize(X[tr], X[te])
    models: Dict[str, object] = {}
    maj = float(np.mean(y[tr]))
    models["baseline_base_rate"] = _binary_metrics(y[te], np.full(te.sum(), maj))

    try:
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(max_iter=4000, class_weight="balanced").fit(Xtr, y[tr])
        models["logistic"] = _binary_metrics(y[te], clf.predict_proba(Xte)[:, 1])
    except Exception as exc:  # pragma: no cover
        models["logistic"] = {"error": str(exc)}

    try:
        from xgboost import XGBClassifier

        spw = float((y[tr] == 0).sum()) / max(1.0, float((y[tr] == 1).sum()))
        clf = XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, eval_metric="logloss", scale_pos_weight=spw,
            random_state=42, tree_method="hist", device=("cuda" if gpu else "cpu"),
        ).fit(Xtr, y[tr])
        models["xgboost"] = _binary_metrics(y[te], clf.predict_proba(Xte)[:, 1])
    except Exception as exc:  # pragma: no cover
        models["xgboost"] = {"error": str(exc)}

    out["models"] = models
    return out


# --- Orquestación y salidas ---------------------------------------------------
def _write_excel(path: str, params: dict, episodes: pd.DataFrame, res: dict) -> None:
    def _flat(d: dict) -> pd.DataFrame:
        rows = []
        for model, m in (d.get("models", {}) or {}).items():
            row = {"modelo": model}
            if isinstance(m, dict):
                row.update({k: v for k, v in m.items()})
            rows.append(row)
        return pd.DataFrame(rows)

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        pd.DataFrame([params]).T.reset_index().rename(
            columns={"index": "parametro", 0: "valor"}
        ).to_excel(xl, sheet_name="00_Resumen", index=False)
        (episodes if not episodes.empty else pd.DataFrame({"info": ["sin episodios"]})).to_excel(
            xl, sheet_name="01_Episodios", index=False
        )
        _flat(res.get("q2", {})).to_excel(xl, sheet_name="02_Q2_Supervivencia", index=False)
        curves = res.get("q2", {}).get("survival_curves", {})
        if curves:
            cdf = pd.DataFrame(curves, index=[f"P(T>{h})" for h in HORIZONS])
            cdf.reset_index().rename(columns={"index": "horizonte"}).to_excel(
                xl, sheet_name="03_Q2_Curvas", index=False
            )
        _flat(res.get("q1", {})).to_excel(xl, sheet_name="04_Q1_Formacion", index=False)
        _flat(res.get("q3", {})).to_excel(xl, sheet_name="05_Q3_Direccion", index=False)


def run(prices_path: str, cutoff: Optional[str], gpu: bool = False) -> Dict[str, object]:
    s = load_brent(prices_path)
    prices = s.to_numpy()
    dates = pd.DatetimeIndex(s.index)
    log(f"[survival] serie Brent: {len(prices)} obs ({dates.min().date()} → {dates.max().date()})")
    log(f"[survival] XGBoost device: {'cuda' if gpu else 'cpu'} (Cox/RSF siempre CPU)")

    episodes = extract_episodes(prices, dates)
    n_ep = len(episodes)
    n_ev = int(episodes["event"].sum()) if n_ep else 0
    log(f"[survival] episodios de canal: {n_ep} (rupturas={n_ev}, censurados={n_ep - n_ev})")
    if n_ep and n_ev:
        med = float(episodes.loc[episodes["event"] == 1, "duration"].median())
        log(f"[survival] duración mediana hasta ruptura: {med:.1f} sesiones")

    res: Dict[str, object] = {}
    log("[survival] Q2 — supervivencia (KM/Cox/RSF/XGB-AFT)…")
    res["q2"] = run_survival(episodes, cutoff, gpu)
    log("[survival] Q1 — formación futura…")
    res["q1"] = run_formation(prices, dates, cutoff, gpu=gpu)
    log("[survival] Q3 — dirección de ruptura…")
    res["q3"] = run_direction(episodes, cutoff, gpu)

    params = {
        "prices_path": prices_path,
        "cutoff": cutoff or "(70% temporal)",
        "gpu": gpu,
        "lookback": LOOKBACK, "min_conf": MIN_CONF, "band_mult": BAND_MULT,
        "atr_win": ATR_WIN, "tol_atr": TOL_ATR, "confirm": CONFIRM,
        "form_horizon": FORM_HORIZON, "horizons": str(list(HORIZONS)),
        "n_episodes": n_ep, "n_breakouts": n_ev,
        "date_min": str(dates.min().date()), "date_max": str(dates.max().date()),
    }

    rep_dir = _out_dir()
    os.makedirs(rep_dir, exist_ok=True)
    json_path = os.path.join(rep_dir, "channel_survival.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"params": params, "results": res}, fh, indent=2, ensure_ascii=False, default=str)
    log(f"[survival] métricas -> {json_path}")

    if n_ep:
        csv_path = os.path.join(rep_dir, "channel_survival_episodes.csv")
        episodes.to_csv(csv_path, index=False)
        log(f"[survival] episodios -> {csv_path}")
    try:
        xlsx_path = os.path.join(rep_dir, "channel_survival_resultados.xlsx")
        _write_excel(xlsx_path, params, episodes, res)
        log(f"[survival] Excel -> {xlsx_path}")
    except Exception as exc:  # pragma: no cover
        log(f"[survival] aviso: no se pudo escribir el Excel ({exc}); JSON/CSV disponibles.")

    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prices", default=None, help="CSV de precios Brent (por defecto ../data/brent_fred_daily.csv)")
    ap.add_argument("--cutoff", default=None, help="fecha de corte del split temporal (YYYY-MM-DD)")
    ap.add_argument("--gpu", action="store_true", help="usa GPU (CUDA) para XGBoost")
    args = ap.parse_args()
    run(args.prices or _default_prices_path(), args.cutoff, args.gpu)
