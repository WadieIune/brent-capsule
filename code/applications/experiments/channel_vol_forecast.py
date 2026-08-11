"""Aplicación 2 — Forecast de canal y volatilidad.

Hipótesis (contrastada, no afirmada): la geometría del canal —en particular la
compresión de la banda (`band_width_rel`)— aporta información sobre la
EXPANSIÓN futura de la volatilidad realizada, útil para pricing/gestión de
vega-gamma en el libro de opciones.

Formulación: para cada fin de ventana con canal, target binario = la vol
realizada en los próximos H días supera a la actual (expansión). Features =
[band_width_rel, r2, slope_norm, vol_now]. Split temporal sin fuga. Baseline =
tasa base (AUC 0.5). Se reporta además el *lift* de compresión: P(expansión |
banda comprimida) / P(expansión).

Se reportan resultados aunque sean negativos (coherente con el ledger del
proyecto: el patrón puede no tener poder predictivo).
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402


class ChannelVolForecastExperiment(Experiment):
    id = "channel_vol_forecast"
    title = "Forecast de canal y volatilidad (compresión → expansión de vol)"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        if int(ctx.config.get("horizon", 10)) < 2:
            issues.append("horizon debe ser >= 2")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        s, source = common.load_prices(cfg.get("prices_path"),
                                       cfg.get("synthetic", False), ctx.seed)
        prices = s.to_numpy()
        dates = pd.DatetimeIndex(s.index)
        n = len(prices)
        horizon = int(cfg.get("horizon", 10))
        vol_win = int(cfg.get("vol_window", 20))
        cutoff = cfg.get("cutoff")

        idxs, flags, featdf = common.window_features(prices)
        if featdf.empty or len(idxs) < 250:
            return ExperimentResult(metrics={"source": source},
                                    decision="review",
                                    notes="serie demasiado corta para el forecast")

        # Feature de supervivencia P(T>horizon), ajustada solo con train (sin fuga).
        episodes = common.cs.extract_episodes(prices, dates)
        featurizer = common.SurvivalFeaturizer().fit(episodes, cutoff)
        surv_pk = featurizer.predict_pk(featdf, horizon)  # alineado a idxs

        # Volatilidad realizada alineada a la posición de precio.
        logp = np.log(np.clip(prices, 1e-9, None))
        ret = np.zeros(n)
        ret[1:] = np.diff(logp)
        rvol = pd.Series(ret).rolling(vol_win, min_periods=vol_win).std().to_numpy()

        rows: List[Dict[str, float]] = []
        ys: List[int] = []
        ds: List[pd.Timestamp] = []
        for k, e0 in enumerate(idxs):
            if e0 < vol_win or e0 + horizon >= n:
                continue
            vol_now = rvol[e0]
            vol_fut = np.nanmax(rvol[e0 + 1:e0 + 1 + horizon])
            if np.isnan(vol_now) or np.isnan(vol_fut):
                continue
            row = featdf.iloc[k].to_dict()
            row["surv_pk"] = float(surv_pk[k]) if surv_pk[k] == surv_pk[k] else 0.5
            rows.append(row)
            ys.append(int(vol_fut > vol_now))
            ds.append(dates[e0])

        if len(ys) < 200:
            return ExperimentResult(metrics={"source": source, "n": len(ys)},
                                    decision="review",
                                    notes="muestras insuficientes tras alinear horizonte")

        cols_geom = list(common.FEATURES)
        cols_surv = cols_geom + ["surv_pk"]
        df = pd.DataFrame(rows)
        y = np.asarray(ys, dtype=int)
        ed = pd.DatetimeIndex(ds)

        tr = common.temporal_mask(ed, cutoff)
        te = ~tr
        metrics: Dict[str, object] = {
            "source": source, "n": int(len(y)),
            "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "horizon": horizon,
            "survival_method": featurizer.method,
            "survival_detail": featurizer.detail,
        }
        if tr.sum() < 50 or te.sum() < 30 or len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            return ExperimentResult(metrics=metrics, decision="review",
                                    notes="split temporal sin suficientes casos/clases")

        # Lift de compresión (banda por debajo de la mediana de train).
        bw = df["band_width"].to_numpy(dtype=float)
        thr = float(np.median(bw[tr]))
        compressed_te = bw[te] <= thr
        base_rate = float(np.mean(y[te]))
        p_exp_comp = float(np.mean(y[te][compressed_te])) if compressed_te.any() else float("nan")
        lift = (p_exp_comp / base_rate) if base_rate > 0 else float("nan")

        def _fit_auc(cols: List[str]) -> Dict[str, float]:
            from sklearn.linear_model import LogisticRegression

            X = df[cols].to_numpy(dtype=float)
            Xtr, Xte = common.cs._standardize(X[tr], X[te])
            clf = LogisticRegression(max_iter=4000, class_weight="balanced").fit(Xtr, y[tr])
            return common.cs._binary_metrics(y[te], clf.predict_proba(Xte)[:, 1])

        m_geom = _fit_auc(cols_geom)
        m_surv = _fit_auc(cols_surv) if featurizer.method != "none" else m_geom
        auc_geom = m_geom.get("auc", float("nan"))
        auc_surv = m_surv.get("auc", float("nan"))
        delta_auc = (auc_surv - auc_geom) if (auc_surv == auc_surv and auc_geom == auc_geom) else float("nan")

        metrics.update({
            "model_geometry": m_geom,
            "model_geometry_plus_survival": m_surv,
            "delta_auc_from_survival": round(delta_auc, 4) if delta_auc == delta_auc else None,
            "base_rate_test": round(base_rate, 4),
            "compression_threshold_bwidth": round(thr, 5),
            "p_expansion_given_compression": round(p_exp_comp, 4) if p_exp_comp == p_exp_comp else None,
            "compression_lift": round(lift, 3) if lift == lift else None,
        })
        baseline = {"method": "tasa base (AUC 0.5) y geometría sin supervivencia",
                    "auc_base_rate": 0.5, "auc_geometry": round(auc_geom, 4) if auc_geom == auc_geom else None}

        auc = auc_surv if auc_surv == auc_surv else auc_geom
        if auc == auc and auc >= 0.55:
            decision = "accept"
        elif auc == auc and auc >= 0.52:
            decision = "review"
        else:
            decision = "reject"
        notes = (f"AUC geom={auc_geom:.3f} → geom+surv={auc_surv:.3f} "
                 f"(Δ={metrics['delta_auc_from_survival']}, surv={featurizer.method}); "
                 f"lift compresión={metrics['compression_lift']}. Régimen de vol para vega/gamma.")
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)