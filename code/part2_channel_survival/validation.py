"""validation — validación robusta de la 2ª pata (supervivencia del canal).

Somete el modelo de supervivencia a la misma disciplina que la 1ª pata del
proyecto (walk-forward, baselines explícitos, corrección por sesgo de selección)
y añade la pregunta que un comité hará de inmediato: **¿la capacidad predictiva
se traduce en valor económico?**

Bloques (todos ejecutables por separado con banderas de la CLI):

  1. `--sensitivity`  Robustez de la DEFINICIÓN de episodio. La duración del
     canal depende de (band_mult, tol_atr, confirm); si las conclusiones solo
     valen para una parametrización, no son conclusiones. Se reporta la tabla
     completa para que el lector juzgue.

  2. `--walkforward` Evaluación con orígenes múltiples (expanding window) en vez
     de un único corte: C-index e IBS de Q2 y AUC de Q3 por origen, con
     **censura administrativa** en cada corte (sin fuga temporal).

  3. `--calibration` ¿La curva P(T>k) predicha coincide con la observada? Un
     C-index alto no implica probabilidades usables: se compara la supervivencia
     media predicha frente a la Kaplan-Meier observada en test y se reporta el
     error de calibración por horizonte.

  4. `--backtest`  Backtest económico de la estrategia implícita en Q3: al
     detectar el canal se toma posición en la dirección de ruptura predicha y se
     cierra en la ruptura efectiva. Se reporta Sharpe, PSR, **DSR** y **PBO**,
     además de buy&hold y costes de transacción.

Resultado central del bloque 4 (documentado en el paper): la dirección de
ruptura ES predecible en términos de clasificación, pero la estrategia NO gana
dinero. Predecir POR QUÉ BANDA sale el precio no es predecir el beneficio: el
acierto direccional convive con una asimetría de pagos que lo anula. Es la misma
conclusión que la 1ª pata (DSR≈0) y refuerza la coherencia del trabajo.

Uso:
  python validation.py                      # todos los bloques
  python validation.py --backtest           # solo el backtest económico
  python validation.py --prices ruta.csv --cutoff 2020-08-20
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

import channel_survival as cs
import metrics_min as mm

SEED = 42
TASK_ID = "part2_channel_survival"

# Orígenes del walk-forward (expanding): cada uno entrena con <= fecha y evalúa
# el bloque siguiente hasta el origen posterior.
WF_ORIGINS = ("2014-01-01", "2016-01-01", "2018-01-01",
              "2020-08-20", "2022-01-01", "2024-01-01")

# Rejilla de sensibilidad de la definición de episodio.
SENS_BAND = (2.0, 2.5, 3.0)
SENS_TOL = (0.5, 1.0, 2.0)
SENS_CONFIRM = (1, 2)


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------
# Harness ARF: manifiesto reproducible por ejecución
# --------------------------------------------------------------------------
def _manifest(config: Dict[str, object], inputs: List[str], metrics: Dict[str, object],
              decision: str, notes: str, elapsed: float, error: Optional[str] = None
              ) -> Dict[str, object]:
    """Campos mínimos del harness (Agentic Research Framework)."""
    return {
        "task_id": TASK_ID,
        "experiment_id": "channel_survival_validation",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": inputs,
        "config": config,
        "seed": SEED,
        "command": " ".join([os.path.basename(sys.executable)] + sys.argv),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "metrics": metrics,
        "error": error,
        "decision": decision,
        "notes": notes,
        "elapsed_seconds": round(elapsed, 2),
    }


# --------------------------------------------------------------------------
# 1. Sensibilidad de la definición de episodio
# --------------------------------------------------------------------------
def run_sensitivity(prices: np.ndarray, dates: pd.DatetimeIndex) -> Dict[str, object]:
    """¿Dependen las conclusiones de cómo se define la ruptura?"""
    rows: List[Dict[str, object]] = []
    for band in SENS_BAND:
        for tol in SENS_TOL:
            for conf in SENS_CONFIRM:
                ep = cs.extract_episodes(prices, dates, band_mult=band,
                                         tol_atr=tol, confirm=conf)
                if ep.empty:
                    continue
                d = ep["duration"]
                rows.append({
                    "band_mult": band, "tol_atr": tol, "confirm": conf,
                    "n_episodes": int(len(ep)),
                    "event_rate": round(float(ep["event"].mean()), 4),
                    "median_duration": float(d.median()),
                    "p90_duration": float(d.quantile(0.90)),
                    "pct_duration_le_1": round(float((d <= 1).mean()), 4),
                    "pct_up_breaks": round(float((ep["breakout_dir"] == "up").mean()), 4),
                })
    df = pd.DataFrame(rows)
    out: Dict[str, object] = {"grid": rows}
    if not df.empty:
        c1 = df[df["confirm"] == 1]["pct_duration_le_1"].mean()
        c2 = df[df["confirm"] == 2]["pct_duration_le_1"].mean()
        out["summary"] = {
            "median_duration_range": [float(df["median_duration"].min()),
                                      float(df["median_duration"].max())],
            "instant_breaks_confirm1": round(float(c1), 4),
            "instant_breaks_confirm2": round(float(c2), 4),
            "note": ("confirm=1 produce rupturas el mismo día de la detección "
                     "(ruido de microestructura); confirm=2 las elimina."),
        }
    return out


# --------------------------------------------------------------------------
# 2. Walk-forward con censura administrativa
# --------------------------------------------------------------------------
def _fit_predict_direction(tr_ep: pd.DataFrame, te_ep: pd.DataFrame) -> Optional[np.ndarray]:
    """Entrena la dirección de ruptura en train y devuelve P(up) en test."""
    from sklearn.linear_model import LogisticRegression

    tr = tr_ep[tr_ep["event"] == 1]
    if len(tr) < 30 or te_ep.empty:
        return None
    ytr = (tr["breakout_dir"] == "up").astype(int).to_numpy()
    if len(np.unique(ytr)) < 2:
        return None
    Xtr, Xte = cs._standardize(tr[cs.FEATURES].to_numpy(float),
                               te_ep[cs.FEATURES].to_numpy(float))
    clf = LogisticRegression(max_iter=4000, class_weight="balanced").fit(Xtr, ytr)
    return clf.predict_proba(Xte)[:, 1]


def _risk_cox(Xtr, ttr, etr, Xte) -> np.ndarray:
    """Riesgo relativo de Cox PH (mayor = rompe antes)."""
    from lifelines import CoxPHFitter

    df = pd.DataFrame(Xtr, columns=cs.FEATURES)
    df["duration"], df["event"] = ttr, etr
    cph = CoxPHFitter(penalizer=0.1).fit(df, "duration", "event")
    return cph.predict_partial_hazard(pd.DataFrame(Xte, columns=cs.FEATURES)).to_numpy().ravel()


def _risk_rsf(Xtr, ttr, etr, Xte) -> np.ndarray:
    """Riesgo acumulado de un Random Survival Forest."""
    from sksurv.ensemble import RandomSurvivalForest
    from sksurv.util import Surv

    rsf = RandomSurvivalForest(n_estimators=300, min_samples_leaf=8,
                               max_features="sqrt", n_jobs=-1,
                               random_state=SEED).fit(Xtr, Surv.from_arrays(etr.astype(bool), ttr))
    return rsf.predict(Xte)


def _risk_xgb_aft(Xtr, ttr, etr, Xte) -> np.ndarray:
    """Riesgo = -tiempo predicho por XGBoost-AFT (mayor riesgo = vida más corta)."""
    import xgboost as xgb

    d = xgb.DMatrix(Xtr)
    d.set_float_info("label_lower_bound", ttr)
    d.set_float_info("label_upper_bound", np.where(etr == 1, ttr, np.inf))
    bst = xgb.train(cs._xgb_aft_params(False), d, num_boost_round=200)
    return -np.clip(bst.predict(xgb.DMatrix(Xte)), 1e-3, None)


def run_walkforward(episodes_raw: pd.DataFrame,
                    origins: Sequence[str] = WF_ORIGINS) -> Dict[str, object]:
    """C-index/IBS (Q2) y AUC (Q3) por origen temporal, con censura administrativa."""
    from sklearn.metrics import roc_auc_score

    folds: List[Dict[str, object]] = []
    for i, org in enumerate(origins):
        c = pd.Timestamp(org)
        end = pd.Timestamp(origins[i + 1]) if i + 1 < len(origins) else None

        ep = cs.administrative_censoring(episodes_raw, c)
        tr = ep["start_date"] <= c
        te_mask = ~tr if end is None else ((ep["start_date"] > c) & (ep["start_date"] <= end))
        n_tr, n_te = int(tr.sum()), int(te_mask.sum())
        fold: Dict[str, object] = {
            "origin": org, "test_end": str(end.date()) if end is not None else "fin",
            "n_train": n_tr, "n_test": n_te,
            "censored_train": int((ep.loc[tr, "event"] == 0).sum()),
        }
        if n_tr < 60 or n_te < 20:
            fold["error"] = "muestras insuficientes"
            folds.append(fold)
            continue

        tr_ep, te_ep = ep[tr], ep[te_mask]
        # --- Q2: C-index de Cox / RSF / XGB-AFT frente al baseline 0.5 --------
        Xtr, Xte = cs._standardize(tr_ep[cs.FEATURES].to_numpy(float),
                                   te_ep[cs.FEATURES].to_numpy(float))
        ttr = tr_ep["duration"].to_numpy(float).clip(min=0.5)
        etr = tr_ep["event"].to_numpy(int)
        tte = te_ep["duration"].to_numpy(float).clip(min=0.5)
        ete = te_ep["event"].to_numpy(bool)
        for model_name, risk_fn in (
            ("cox", _risk_cox), ("rsf", _risk_rsf), ("xgb_aft", _risk_xgb_aft)
        ):
            try:
                from sksurv.metrics import concordance_index_censored

                risk = risk_fn(Xtr, ttr, etr, Xte)
                ci = concordance_index_censored(ete, tte, risk)[0]
                fold[f"q2_{model_name}_c_index"] = round(float(ci), 4)
            except Exception as exc:  # pragma: no cover
                fold[f"q2_{model_name}_error"] = str(exc)[:120]

        # --- Q3: AUC de la dirección de ruptura -------------------------------
        try:
            te_br = te_ep[te_ep["event"] == 1]
            p = _fit_predict_direction(tr_ep, te_br)
            if p is not None and len(te_br) >= 15:
                y = (te_br["breakout_dir"] == "up").astype(int).to_numpy()
                if len(np.unique(y)) > 1:
                    fold["q3_auc"] = round(float(roc_auc_score(y, p)), 4)
                    fold["q3_n"] = int(len(y))
        except Exception as exc:  # pragma: no cover
            fold["q3_error"] = str(exc)
        folds.append(fold)

    summary: Dict[str, object] = {"baseline_c_index": 0.5, "baseline_auc": 0.5}
    for m in ("cox", "rsf", "xgb_aft"):
        vals = [f[f"q2_{m}_c_index"] for f in folds if f"q2_{m}_c_index" in f]
        if vals:
            summary[f"q2_{m}"] = {
                "c_index_mean": round(float(np.mean(vals)), 4),
                "c_index_std": round(float(np.std(vals)), 4),
                "c_index_min": round(float(np.min(vals)), 4),
                "n_folds": len(vals),
            }
    best = max((m for m in ("cox", "rsf", "xgb_aft") if f"q2_{m}" in summary),
               key=lambda m: summary[f"q2_{m}"]["c_index_mean"], default=None)
    summary["q2_best_model"] = best
    if best:
        summary["q2_c_index_mean"] = summary[f"q2_{best}"]["c_index_mean"]
        summary["q2_c_index_std"] = summary[f"q2_{best}"]["c_index_std"]
        summary["q2_c_index_min"] = summary[f"q2_{best}"]["c_index_min"]
    au = [f["q3_auc"] for f in folds if "q3_auc" in f]
    summary["n_folds_ok"] = len(au)
    summary["q3_auc_mean"] = round(float(np.mean(au)), 4) if au else None
    summary["q3_auc_std"] = round(float(np.std(au)), 4) if au else None
    return {"folds": folds, "summary": summary}


# --------------------------------------------------------------------------
# 3. Calibración de la curva de supervivencia
# --------------------------------------------------------------------------
def run_calibration(episodes_raw: pd.DataFrame, cutoff: str,
                    horizons: Sequence[int] = cs.HORIZONS) -> Dict[str, object]:
    """Compara P(T>k) predicha (Cox) con la observada (Kaplan-Meier) en test."""
    out: Dict[str, object] = {"horizons": list(horizons)}
    try:
        from lifelines import CoxPHFitter, KaplanMeierFitter
    except Exception as exc:  # pragma: no cover
        out["error"] = f"lifelines no disponible: {exc}"
        return out

    c = pd.Timestamp(cutoff)
    ep = cs.administrative_censoring(episodes_raw, c)
    tr, te = ep["start_date"] <= c, ep["start_date"] > c
    if tr.sum() < 60 or te.sum() < 30:
        out["error"] = "muestras insuficientes"
        return out
    tr_ep, te_ep = ep[tr], ep[te]

    Xtr, Xte = cs._standardize(tr_ep[cs.FEATURES].to_numpy(float),
                               te_ep[cs.FEATURES].to_numpy(float))
    df_tr = pd.DataFrame(Xtr, columns=cs.FEATURES)
    df_tr["duration"] = tr_ep["duration"].to_numpy(float).clip(min=0.5)
    df_tr["event"] = tr_ep["event"].to_numpy(int)
    cph = CoxPHFitter(penalizer=0.1).fit(df_tr, "duration", "event")
    sf = cph.predict_survival_function(pd.DataFrame(Xte, columns=cs.FEATURES),
                                       times=list(horizons))

    kmf = KaplanMeierFitter().fit(te_ep["duration"].to_numpy(float).clip(min=0.5),
                                  te_ep["event"].to_numpy(int))
    km_tr = KaplanMeierFitter().fit(tr_ep["duration"].to_numpy(float).clip(min=0.5),
                                    tr_ep["event"].to_numpy(int))

    # XGB-AFT (el mejor por C-index) también se evalúa en calibración: ordenar
    # bien no implica que la PROBABILIDAD sea usable, y las aplicaciones de
    # riesgo (add-on del VaR) consumen P(T>k), no el ranking.
    surv_xgb = None
    try:
        import xgboost as xgb
        from scipy.stats import norm

        d = xgb.DMatrix(Xtr)
        ttr = tr_ep["duration"].to_numpy(float).clip(min=0.5)
        etr = tr_ep["event"].to_numpy(int)
        d.set_float_info("label_lower_bound", ttr)
        d.set_float_info("label_upper_bound", np.where(etr == 1, ttr, np.inf))
        bst = xgb.train(cs._xgb_aft_params(False), d, num_boost_round=200)
        mu = np.log(np.clip(bst.predict(xgb.DMatrix(Xte)), 1e-3, None))
        surv_xgb = {h: float(np.mean(1.0 - norm.cdf((np.log(h) - mu) / cs.XGB_SCALE)))
                    for h in horizons}
    except Exception as exc:  # pragma: no cover
        out["xgb_error"] = str(exc)[:150]

    rows = []
    for h in horizons:
        pred = float(sf.loc[h].mean())
        obs = float(kmf.predict(h))
        base = float(km_tr.predict(h))   # baseline: KM del train (sin covariables)
        row = {
            "horizon": int(h),
            "observed_km_test": round(obs, 4),
            "predicted_cox": round(pred, 4),
            "abs_error_cox": round(abs(pred - obs), 4),
            "baseline_km_train": round(base, 4),
            "abs_error_baseline": round(abs(base - obs), 4),
        }
        if surv_xgb is not None:
            row["predicted_xgb_aft"] = round(surv_xgb[h], 4)
            row["abs_error_xgb_aft"] = round(abs(surv_xgb[h] - obs), 4)
        rows.append(row)
    df = pd.DataFrame(rows)
    out["by_horizon"] = rows
    summary = {
        "mae_cox": round(float(df["abs_error_cox"].mean()), 4),
        "mae_baseline_km": round(float(df["abs_error_baseline"].mean()), 4),
        "n_train": int(tr.sum()), "n_test": int(te.sum()),
    }
    if "abs_error_xgb_aft" in df.columns:
        summary["mae_xgb_aft"] = round(float(df["abs_error_xgb_aft"].mean()), 4)
    maes = {k.replace("mae_", ""): v for k, v in summary.items() if k.startswith("mae_")}
    summary["best_calibrated"] = min(maes, key=maes.get)
    summary["note"] = ("El baseline Kaplan-Meier marginal es difícil de batir en "
                       "CALIBRACIÓN aunque tenga C-index 0.5: ordena mal pero acierta "
                       "el nivel medio. Las covariables aportan discriminación "
                       "(ranking), no necesariamente mejor probabilidad absoluta.")
    out["summary"] = summary
    return out


# --------------------------------------------------------------------------
# 4. Backtest económico de la estrategia de ruptura (Q3)
# --------------------------------------------------------------------------
def run_backtest(episodes_raw: pd.DataFrame, prices: pd.Series, cutoff: str,
                 fee_bps: float = 5.0) -> Dict[str, object]:
    """¿Se traduce el acierto direccional de Q3 en dinero? (DSR/PBO)

    Estrategia: al detectar el canal se abre posición en la dirección de ruptura
    predicha y se cierra en la ruptura efectiva. Episodios no solapados => la
    secuencia de operaciones es limpia (sin solape de posiciones).
    """
    out: Dict[str, object] = {"fee_bps_per_side": fee_bps}
    c = pd.Timestamp(cutoff)
    ep = cs.administrative_censoring(episodes_raw, c)
    tr_ep = ep[ep["start_date"] <= c]
    te_ep = episodes_raw[(episodes_raw["start_date"] > c) &
                         (episodes_raw["event"] == 1)].copy()
    if len(tr_ep) < 60 or len(te_ep) < 30:
        out["error"] = "muestras insuficientes para el backtest"
        return out

    p0 = np.array([prices.get(d, np.nan) for d in te_ep["start_date"]], dtype=float)
    p1 = np.array([prices.get(d, np.nan) for d in te_ep["end_date"]], dtype=float)
    ok = ~(np.isnan(p0) | np.isnan(p1))
    te_ep, p0, p1 = te_ep[ok], p0[ok], p1[ok]
    if len(te_ep) < 30:
        out["error"] = "precios insuficientes en el tramo de test"
        return out
    ret = p1 / p0 - 1.0

    prob = _fit_predict_direction(tr_ep, te_ep)
    if prob is None:
        out["error"] = "no se pudo entrenar el clasificador de dirección"
        return out
    y_true = (te_ep["breakout_dir"] == "up").astype(int).to_numpy()

    # Variantes de señal (sirven de "trials" para el DSR y de columnas del PBO).
    variants: Dict[str, np.ndarray] = {
        "modelo_q3": np.where(prob >= 0.50, 1.0, -1.0),
        "modelo_q3_conf60": np.where(prob >= 0.60, 1.0, np.where(prob <= 0.40, -1.0, 0.0)),
        "modelo_q3_conf70": np.where(prob >= 0.70, 1.0, np.where(prob <= 0.30, -1.0, 0.0)),
        "contra_tendencia": np.where(te_ep["direction"].to_numpy() == "ascending", -1.0, 1.0),
        "siempre_largo": np.ones(len(te_ep)),
    }
    fee = fee_bps / 1e4
    per_variant: Dict[str, object] = {}
    cols: List[np.ndarray] = []
    for name, pos in variants.items():
        pnl = pos * ret - 2.0 * fee * np.abs(pos)
        stats = mm.performance_stats(pnl, periods_per_year=_trades_per_year(te_ep))
        per_variant[name] = {k: round(v, 6) if isinstance(v, float) else v
                             for k, v in stats.items()}
        cols.append(pnl)

    main = variants["modelo_q3"] * ret - 2.0 * fee
    sr_trials = [mm.sharpe_ratio(c_, _trades_per_year(te_ep)) for c_ in cols]
    dsr = mm.deflated_sharpe_ratio(main, sr_trials, _trades_per_year(te_ep))
    pbo = mm.probability_of_backtest_overfitting(np.column_stack(cols), n_partitions=10)

    # Buy & hold del mismo periodo (referencia honesta).
    bh = float(prices.loc[te_ep["end_date"].max()] / prices.loc[te_ep["start_date"].min()] - 1.0)

    acc = float(np.mean((prob >= 0.5).astype(int) == y_true))
    out.update({
        "n_trades": int(len(te_ep)),
        "period": [str(te_ep["start_date"].min().date()), str(te_ep["end_date"].max().date())],
        "direction_accuracy": round(acc, 4),
        "trades_per_year": round(_trades_per_year(te_ep), 2),
        "strategies": per_variant,
        "deflated_sharpe": {k: (round(v, 6) if isinstance(v, float) else v)
                            for k, v in dsr.items()},
        "pbo": pbo,
        "buy_and_hold_return": round(bh, 4),
        "verdict": _backtest_verdict(per_variant["modelo_q3"], dsr, bh, acc),
    })
    return out


def _trades_per_year(te_ep: pd.DataFrame) -> float:
    span = (te_ep["end_date"].max() - te_ep["start_date"].min()).days / 365.25
    return float(len(te_ep) / span) if span > 0 else 252.0


def _backtest_verdict(stats: Dict[str, object], dsr: Dict[str, float],
                      bh: float, acc: float) -> str:
    sr = float(stats.get("sharpe_annual", 0.0) or 0.0)
    cum = float(stats.get("cumulative_return", 0.0) or 0.0)
    d = float(dsr.get("deflated_sharpe_ratio", 0.0) or 0.0)
    if d >= 0.95 and sr > 0 and cum > bh:
        return ("EDGE: la estrategia supera al buy&hold y sobrevive a la deflación "
                "por número de pruebas (DSR>=0.95).")
    return (f"SIN EDGE: acierto direccional {acc:.1%} pero Sharpe {sr:.2f} y retorno "
            f"acumulado {cum:.1%} frente a buy&hold {bh:.1%}; DSR={d:.3f}. "
            "Predecir POR QUÉ BANDA rompe el canal no equivale a ganar dinero: "
            "la asimetría de pagos anula el acierto direccional (coherente con el "
            "DSR≈0 de la 1ª pata).")


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------
def _write_excel(path: str, res: Dict[str, object]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        if "sensitivity" in res and res["sensitivity"].get("grid"):
            pd.DataFrame(res["sensitivity"]["grid"]).to_excel(
                xl, sheet_name="01_Sensibilidad", index=False)
        if "walkforward" in res and res["walkforward"].get("folds"):
            pd.DataFrame(res["walkforward"]["folds"]).to_excel(
                xl, sheet_name="02_WalkForward", index=False)
        if "calibration" in res and res["calibration"].get("by_horizon"):
            pd.DataFrame(res["calibration"]["by_horizon"]).to_excel(
                xl, sheet_name="03_Calibracion", index=False)
        bt = res.get("backtest", {})
        if bt.get("strategies"):
            rows = [{"estrategia": k, **v} for k, v in bt["strategies"].items()]
            pd.DataFrame(rows).to_excel(xl, sheet_name="04_Backtest", index=False)
            rob = {**{f"dsr.{k}": v for k, v in bt.get("deflated_sharpe", {}).items()},
                   **{f"pbo.{k}": v for k, v in bt.get("pbo", {}).items()},
                   "buy_and_hold_return": bt.get("buy_and_hold_return"),
                   "direction_accuracy": bt.get("direction_accuracy"),
                   "veredicto": bt.get("verdict")}
            pd.DataFrame([{"metrica": k, "valor": v} for k, v in rob.items()]).to_excel(
                xl, sheet_name="05_Backtest_Robustez", index=False)


def run(prices_path: str, cutoff: str, blocks: Dict[str, bool],
        fee_bps: float = 5.0) -> Dict[str, object]:
    t0 = time.time()
    np.random.seed(SEED)
    s = cs.load_brent(prices_path)
    prices_arr = s.to_numpy()
    dates = pd.DatetimeIndex(s.index)
    log(f"[validation] serie: {len(prices_arr)} obs ({dates.min().date()} → {dates.max().date()})")

    episodes = cs.extract_episodes(prices_arr, dates)
    log(f"[validation] episodios (confirm={cs.CONFIRM}): {len(episodes)} "
        f"| duración mediana {episodes['duration'].median():.0f} sesiones")

    res: Dict[str, object] = {
        "episodes": {
            "n": int(len(episodes)),
            "median_duration": float(episodes["duration"].median()),
            "event_rate": round(float(episodes["event"].mean()), 4),
            "confirm": cs.CONFIRM, "band_mult": cs.BAND_MULT, "tol_atr": cs.TOL_ATR,
        }
    }
    if blocks.get("sensitivity"):
        log("[validation] 1/4 sensibilidad de la definición de episodio…")
        res["sensitivity"] = run_sensitivity(prices_arr, dates)
    if blocks.get("walkforward"):
        log("[validation] 2/4 walk-forward con censura administrativa…")
        res["walkforward"] = run_walkforward(episodes)
    if blocks.get("calibration"):
        log("[validation] 3/4 calibración de P(T>k)…")
        res["calibration"] = run_calibration(episodes, cutoff)
    if blocks.get("backtest"):
        log("[validation] 4/4 backtest económico (DSR/PBO)…")
        res["backtest"] = run_backtest(episodes, s, cutoff, fee_bps=fee_bps)

    out_dir = cs._out_dir()
    os.makedirs(out_dir, exist_ok=True)
    decision, notes = _overall_decision(res)
    manifest = _manifest(
        config={"prices_path": prices_path, "cutoff": cutoff, "fee_bps": fee_bps,
                "blocks": blocks, "confirm": cs.CONFIRM, "band_mult": cs.BAND_MULT,
                "tol_atr": cs.TOL_ATR, "lookback": cs.LOOKBACK},
        inputs=[prices_path], metrics=res, decision=decision, notes=notes,
        elapsed=time.time() - t0)

    with open(os.path.join(out_dir, "validation.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, default=str)
    log(f"[validation] manifiesto -> {os.path.join(out_dir, 'validation.json')}")
    try:
        xp = os.path.join(out_dir, "channel_survival_validacion.xlsx")
        _write_excel(xp, res)
        log(f"[validation] Excel -> {xp}")
    except Exception as exc:  # pragma: no cover
        log(f"[validation] aviso: Excel no escrito ({exc})")

    _print_summary(res)
    return manifest


def _overall_decision(res: Dict[str, object]) -> tuple:
    wf = (res.get("walkforward") or {}).get("summary") or {}
    bt = res.get("backtest") or {}
    ci = wf.get("q2_c_index_mean")
    parts = []
    if ci is not None:
        parts.append(f"Q2 C-index walk-forward {ci:.3f} (baseline 0.5)")
    if bt.get("verdict"):
        parts.append(bt["verdict"].split(":")[0])
    decision = "accept" if (ci or 0) > 0.55 else "review"
    return decision, " · ".join(parts) if parts else "sin bloques ejecutados"


def _print_summary(res: Dict[str, object]) -> None:
    log("\n" + "=" * 68)
    log("RESUMEN DE VALIDACIÓN — 2ª pata (supervivencia del canal)")
    log("=" * 68)
    wf = (res.get("walkforward") or {}).get("summary")
    if wf:
        for m in ("cox", "rsf", "xgb_aft"):
            d = wf.get(f"q2_{m}")
            if d:
                mark = " <- mejor" if wf.get("q2_best_model") == m else ""
                log(f"Q2 supervivencia · C-index {m:<8}: {d['c_index_mean']:.3f} "
                    f"± {d['c_index_std']:.3f} (mín {d['c_index_min']:.3f}){mark}")
    if wf and wf.get("q3_auc_mean") is not None:
        log(f"Q3 dirección   · AUC walk-forward:      {wf['q3_auc_mean']:.3f} "
            f"± {wf['q3_auc_std']:.3f} (baseline 0.500)")
    cal = (res.get("calibration") or {}).get("summary")
    if cal:
        parts = [f"KM {cal['mae_baseline_km']:.3f}", f"Cox {cal['mae_cox']:.3f}"]
        if "mae_xgb_aft" in cal:
            parts.append(f"XGB-AFT {cal['mae_xgb_aft']:.3f}")
        log(f"Calibración P(T>k) · MAE: {' | '.join(parts)} -> mejor: {cal['best_calibrated']}")
    bt = res.get("backtest") or {}
    if bt.get("strategies"):
        m = bt["strategies"]["modelo_q3"]
        log(f"Backtest       · acierto {bt['direction_accuracy']:.1%} | Sharpe "
            f"{m['sharpe_annual']:.2f} | retorno {m['cumulative_return']:.1%} vs "
            f"buy&hold {bt['buy_and_hold_return']:.1%}")
        log(f"                 DSR={bt['deflated_sharpe']['deflated_sharpe_ratio']:.4f} "
            f"| PBO={bt['pbo'].get('pbo')}")
        log(f"  -> {bt['verdict']}")
    log("=" * 68 + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prices", default=None)
    ap.add_argument("--cutoff", default="2020-08-20")
    ap.add_argument("--fee-bps", type=float, default=5.0)
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--calibration", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    a = ap.parse_args()
    sel = {"sensitivity": a.sensitivity, "walkforward": a.walkforward,
           "calibration": a.calibration, "backtest": a.backtest}
    if not any(sel.values()):
        sel = {k: True for k in sel}
    run(a.prices or cs._default_prices_path(), a.cutoff, sel, fee_bps=a.fee_bps)
