"""Aplicación 9 — La RUPTURA del canal como tarea propia (nunca se midió).

Hasta ahora la ruptura solo se usaba de forma indirecta: la propensión
`1 − P(T>k)` alimentaba un overlay de VaR, y allí no aportó nada. Pero eso mide
el uso, no la capacidad: nunca se evaluó **cómo de bien se detecta la ruptura en
sí**, ni con cuánta antelación. Este experimento lo hace.

Formulación
-----------
En la serie, prácticamente todos los episodios de canal terminan rompiendo
(589 de 590), así que la pregunta no es *si* rompe sino **cuándo**. Para cada
sesión dentro de un episodio se predice `ruptura en las próximas h sesiones`
—un problema de *hazard* en tiempo discreto— y se mide además el **lead time**:
cuántas sesiones de antelación da el aviso.

Escalera de baselines (cada uno responde a una objeción distinta)
-----------------------------------------------------------------
  - `base_rate`   : hazard incondicional. Si no se supera, no hay nada.
  - `actuarial`   : solo el tiempo transcurrido en el episodio. Es el baseline
    honesto: una tabla de vida no necesita ni geometría ni CNN.
  - `volatility`  : solo variables de dispersión (vol20, atr, band_width).
  - `shape`       : solo forma del canal (pendiente, r2, giros, posición).
  - `full`        : todo junto.
La pregunta que importa es si `shape` y `full` superan a `actuarial` y
`volatility`: es decir, si la geometría aporta algo por encima de saber cuánto
lleva vivo el canal y cuánta volatilidad hay.

Segunda pregunta: **¿anticipa la ruptura una expansión de volatilidad?** Se mide
con un objetivo bien especificado —la razón entre la volatilidad realizada
posterior y la anterior— en vez del target casi degenerado (base rate 0.795) que
usaba `channel_vol_forecast`.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler  # noqa: E402

SHAPE = ["dir_asc", "slope_norm", "r2", "n_turn", "pos_in_channel", "accel", "last_ret"]
# Distancia al centro de la banda. La tasa de ruptura en función de la posición
# dentro del canal es una U: alta en ambos bordes y mínima en el centro. Al ser
# NO MONÓTONA, ningún modelo lineal sobre `pos_in_channel` puede capturarla, que
# es la razón por la que los overlays lineales previos no veían nada.
EDGE = ["edge_distance"]
VOL = ["vol20", "atr_norm", "band_width", "resid_norm"]


def build_hazard_dataset(prices: np.ndarray, dates: pd.DatetimeIndex, horizon: int
                         ) -> Tuple[pd.DataFrame, np.ndarray, pd.DatetimeIndex, np.ndarray]:
    """Panel día-a-día dentro de episodios: features + `rompe en <= h sesiones`.

    Devuelve (features, y, fechas, episode_id).
    """
    episodes = common.cs.extract_episodes(prices, dates)
    idxs, _flags, featdf = common.window_features(prices)
    if not len(episodes) or featdf.empty:
        return pd.DataFrame(), np.array([]), pd.DatetimeIndex([]), np.array([])

    pos_of = {d: i for i, d in enumerate(dates)}
    spans: List[Tuple[int, int, int]] = []
    for ep_id, r in episodes.iterrows():
        p0 = pos_of.get(pd.Timestamp(r["start_date"]))
        p1 = pos_of.get(pd.Timestamp(r["end_date"]))
        if p0 is not None and p1 is not None and p1 > p0:
            spans.append((p0, p1, int(ep_id)))
    spans.sort()

    starts = np.array([s[0] for s in spans])
    rows, ys, ds, eps, elapsed = [], [], [], [], []
    for k, e0 in enumerate(idxs):
        j = int(np.searchsorted(starts, e0, side="right") - 1)
        if j < 0:
            continue
        p0, p1, ep_id = spans[j]
        if not (p0 <= e0 < p1):
            continue
        rows.append(featdf.iloc[k].to_dict())
        ys.append(int((p1 - e0) <= horizon))
        ds.append(dates[e0])
        eps.append(ep_id)
        elapsed.append(e0 - p0)
    if not rows:
        return pd.DataFrame(), np.array([]), pd.DatetimeIndex([]), np.array([])
    df = pd.DataFrame(rows)
    df["time_in_episode"] = elapsed
    df["edge_distance"] = (df["pos_in_channel"] - 0.5).abs()
    return df, np.asarray(ys, int), pd.DatetimeIndex(ds), np.asarray(eps, int)


def _fit_eval(df: pd.DataFrame, y: np.ndarray, tr: np.ndarray, te: np.ndarray,
              cols: List[str], model: str = "logit") -> Dict[str, object]:
    cols = [c for c in cols if c in df.columns]
    if not cols or len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
        return {}
    X = df[cols].to_numpy(float)
    if model == "gb":
        clf = HistGradientBoostingClassifier(max_depth=3, max_iter=200,
                                             learning_rate=0.06, random_state=42)
        clf.fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        p_tr = clf.predict_proba(X[tr])[:, 1]
    else:
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=5000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
        p = clf.predict_proba(sc.transform(X[te]))[:, 1]
        p_tr = clf.predict_proba(sc.transform(X[tr]))[:, 1]
    thr = float(np.quantile(p_tr, 1.0 - float(y[tr].mean())))  # umbral por tasa base de train
    yh = (p >= thr).astype(int)
    return {"features": cols, "n_features": len(cols), "model": model,
            "auc": round(float(roc_auc_score(y[te], p)), 4),
            "average_precision": round(float(average_precision_score(y[te], p)), 4),
            "precision": round(float(precision_score(y[te], yh, zero_division=0)), 4),
            "recall": round(float(recall_score(y[te], yh, zero_division=0)), 4),
            "threshold": round(thr, 4), "_scores": p, "_thr": thr}


def lead_time(p: np.ndarray, thr: float, ep: np.ndarray, dates: pd.DatetimeIndex,
              y: np.ndarray, horizon: int) -> Dict[str, object]:
    """Antelación del primer aviso dentro de cada episodio, en sesiones."""
    leads: List[int] = []
    fired = 0
    for e in np.unique(ep):
        m = ep == e
        if not m.any():
            continue
        pm, ym = p[m], y[m]
        hit = np.where(pm >= thr)[0]
        if hit.size:
            fired += 1
            # posiciones dentro del episodio: la ruptura ocurre al final del tramo
            leads.append(int(len(pm) - hit[0]))
    if not leads:
        return {"episodes_with_alert": 0}
    return {"episodes_evaluated": int(len(np.unique(ep))),
            "episodes_with_alert": int(fired),
            "alert_coverage_pct": round(100.0 * fired / len(np.unique(ep)), 1),
            "lead_sessions_median": float(np.median(leads)),
            "lead_sessions_p25": float(np.percentile(leads, 25)),
            "lead_sessions_p75": float(np.percentile(leads, 75)),
            "horizon": horizon}


def breakout_vol_expansion(prices: np.ndarray, dates: pd.DatetimeIndex,
                           horizon: int, vol_win: int) -> Dict[str, object]:
    """¿Se expande la volatilidad tras la ruptura? Objetivo bien especificado.

    Se compara la vol realizada en las `horizon` sesiones POSTERIORES a la
    ruptura con la de las `vol_win` anteriores, mediante la razón (log). Frente
    al target binario `max(vol futura) > vol actual` —cuya tasa base 0.795 lo
    hace casi degenerado— la razón es continua y comparable entre episodios.
    """
    episodes = common.cs.extract_episodes(prices, dates)
    pos_of = {d: i for i, d in enumerate(dates)}
    r = np.zeros(len(prices))
    r[1:] = np.diff(np.log(np.clip(prices, 1e-9, None)))
    ratios, base = [], []
    for _, e in episodes.iterrows():
        p1 = pos_of.get(pd.Timestamp(e["end_date"]))
        if p1 is None or p1 - vol_win < 0 or p1 + horizon >= len(prices):
            continue
        pre = float(np.std(r[p1 - vol_win:p1]))
        post = float(np.std(r[p1:p1 + horizon]))
        if pre > 1e-12:
            ratios.append(np.log(max(post, 1e-12) / pre))
        # control: mismo cálculo en una fecha aleatoria (no ruptura)
    rng = np.random.default_rng(42)
    for _ in range(len(ratios)):
        t = int(rng.integers(vol_win, len(prices) - horizon))
        pre = float(np.std(r[t - vol_win:t]))
        post = float(np.std(r[t:t + horizon]))
        if pre > 1e-12:
            base.append(np.log(max(post, 1e-12) / pre))
    if not ratios or not base:
        return {}
    a, b = np.asarray(ratios), np.asarray(base)
    # test de medias (Welch) sin depender de scipy
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    tstat = float((a.mean() - b.mean()) / se) if se > 0 else float("nan")
    return {"n_breakouts": int(len(a)),
            "mean_log_vol_ratio_after_breakout": round(float(a.mean()), 4),
            "mean_log_vol_ratio_random": round(float(b.mean()), 4),
            "median_after_breakout": round(float(np.median(a)), 4),
            "welch_t": round(tstat, 3),
            "expansion_after_breakout": bool(a.mean() > b.mean()),
            "interpretation": ("t>2 indicaría expansión de volatilidad tras la ruptura "
                               "significativamente mayor que en una fecha cualquiera")}


class BreakoutDetectionExperiment(Experiment):
    id = "breakout_detection"
    title = "Detección de ruptura de canal: hazard, lead time y expansión de volatilidad"

    def preflight(self, ctx: RunContext) -> List[str]:
        return ["horizon debe ser >= 1"] if int(ctx.config.get("breakout_horizon", 5)) < 1 else []

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        horizon = int(cfg.get("breakout_horizon", 5))
        vol_win = int(cfg.get("vol_window", 20))
        cutoff = cfg.get("cutoff")
        s, source = common.load_prices(cfg.get("prices_path"),
                                       cfg.get("synthetic", False), ctx.seed)
        prices = s.to_numpy()
        dates = pd.DatetimeIndex(s.index)

        df, y, ds, ep = build_hazard_dataset(prices, dates, horizon)
        if len(y) < 500:
            return ExperimentResult(metrics={"source": source, "n": int(len(y))},
                                    decision="review", notes="muestra insuficiente")
        tr = common.temporal_mask(ds, cutoff)
        te = ~tr
        ctx.log(f"panel de hazard: {len(y)} filas · train {tr.sum()} / test {te.sum()} · "
                f"tasa base ruptura<= {horizon}d = {y[te].mean():.3f}")

        sets = {
            "actuarial (solo tiempo en episodio)": ["time_in_episode"],
            "volatilidad": VOL,
            "forma del canal": SHAPE,
            "forma + volatilidad": SHAPE + VOL,
            "completo + tiempo": SHAPE + VOL + ["time_in_episode"],
            "SOLO distancia al borde": EDGE,
            "completo + borde": SHAPE + VOL + ["time_in_episode"] + EDGE,
        }
        res: Dict[str, object] = {}
        best_scores: Optional[np.ndarray] = None
        best_thr = 0.5
        best_name, best_auc = None, -1.0
        for name, cols in sets.items():
            r = _fit_eval(df, y, tr, te, cols, model="logit")
            if not r:
                continue
            sc, th = r.pop("_scores"), r.pop("_thr")
            res[name] = r
            ctx.log(f"  {name:<38} AUC={r['auc']:.4f} AP={r['average_precision']:.4f} "
                    f"prec={r['precision']:.3f} rec={r['recall']:.3f}")
            if r["auc"] > best_auc:
                best_auc, best_name, best_scores, best_thr = r["auc"], name, sc, th
        # no lineal sobre el conjunto completo
        rg = _fit_eval(df, y, tr, te, SHAPE + VOL + ["time_in_episode"] + EDGE, model="gb")
        if rg:
            sc, th = rg.pop("_scores"), rg.pop("_thr")
            res["completo + tiempo (gradient boosting)"] = rg
            ctx.log(f"  {'completo + tiempo (GB)':<38} AUC={rg['auc']:.4f} "
                    f"AP={rg['average_precision']:.4f}")
            if rg["auc"] > best_auc:
                best_auc, best_name, best_scores, best_thr = rg["auc"], "completo + tiempo (GB)", sc, th

        base_rate = float(y[te].mean())
        lt = (lead_time(best_scores, best_thr, ep[te], ds[te], y[te], horizon)
              if best_scores is not None else {})
        # Curva en U: tasa de ruptura por decil de posición en la banda.
        dec = pd.qcut(df.loc[te, "pos_in_channel"], 10, duplicates="drop")
        u_curve = (pd.DataFrame({"y": y[te]}).groupby(dec.values, observed=True)["y"]
                   .agg(["mean", "size"]))
        u_shape = [{"bucket": str(k), "breakout_rate": round(float(v["mean"]), 4),
                    "n": int(v["size"])} for k, v in u_curve.iterrows()]
        vol_exp = breakout_vol_expansion(prices, dates, horizon, vol_win)
        ctx.log(f"  lead time (mejor modelo: {best_name}): "
                f"mediana {lt.get('lead_sessions_median')} sesiones")
        ctx.log(f"  expansión de vol tras ruptura: t={vol_exp.get('welch_t')} "
                f"(media {vol_exp.get('mean_log_vol_ratio_after_breakout')} vs "
                f"aleatoria {vol_exp.get('mean_log_vol_ratio_random')})")

        act = res.get("actuarial (solo tiempo en episodio)", {}).get("auc", 0.5)
        vol_auc = res.get("volatilidad", {}).get("auc", 0.5)
        shape_auc = res.get("forma del canal", {}).get("auc", 0.5)
        gain_shape = round(float(best_auc - max(act, vol_auc)), 4)

        metrics = {
            "source": source, "horizon": horizon, "n_rows": int(len(y)),
            "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "base_rate_test": round(base_rate, 4),
            "models": res, "best_model": best_name, "best_auc": round(float(best_auc), 4),
            "auc_actuarial": act, "auc_volatility": vol_auc, "auc_shape": shape_auc,
            "gain_over_best_baseline": gain_shape,
            "lead_time": lt, "breakout_vol_expansion": vol_exp,
            "u_shape_by_band_position": u_shape,
        }
        baseline = {"unconditional": round(base_rate, 4), "auc_random": 0.5,
                    "actuarial_auc": act, "volatility_auc": vol_auc,
                    "note": "la geometría debe superar a tiempo-en-episodio y a volatilidad"}
        beats = gain_shape > 0.02
        decision = "accept" if (best_auc > 0.6 and beats) else ("review" if best_auc > 0.55 else "reject")
        notes = (
            f"Ruptura en <= {horizon} sesiones; tasa base {base_rate:.3f}. "
            f"AUC: actuarial (solo tiempo) {act} · volatilidad {vol_auc} · forma {shape_auc} "
            f"-> mejor {best_name} {best_auc:.4f} (ganancia sobre el mejor baseline "
            f"{gain_shape:+.4f}). Lead time mediano {lt.get('lead_sessions_median')} sesiones "
            f"con cobertura del {lt.get('alert_coverage_pct')}% de los episodios. "
            f"Expansión de volatilidad tras la ruptura: media log-ratio "
            f"{vol_exp.get('mean_log_vol_ratio_after_breakout')} frente a "
            f"{vol_exp.get('mean_log_vol_ratio_random')} en fecha aleatoria "
            f"(Welch t={vol_exp.get('welch_t')})."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)
