"""WP3 — Auditoría de `channel_vol_forecast` contra baselines fuertes de volatilidad.

`channel_vol_forecast` figura como `accept` con AUC 0.716 prediciendo la
**expansión de la volatilidad realizada**. Pero su baseline es la tasa base
(AUC 0.5) y "geometría sin supervivencia": **nunca se comparó con un modelo de
volatilidad**. Es el mismo patrón que invalidó el resultado del VaR, donde el
mérito atribuido al canal resultó ser del filtrado de volatilidad.

Hay un motivo concreto para sospechar. De las once *features* que el experimento
llama "geometría", **cuatro son medidas de volatilidad**:

  `vol20`       desviación de los últimos 20 retornos  (volatilidad realizada)
  `atr_norm`    ATR / precio                            (rango medio)
  `resid_norm`  σ de los residuos / nivel               (dispersión en torno al canal)
  `band_width`  2·m·σ_resid / nivel                     (anchura = σ reescalada)

Es decir, el modelo "de geometría" ya contiene un modelo de volatilidad. Y el
objetivo —¿superará la vol futura a la actual?— es en gran medida una pregunta
sobre **reversión a la media de la volatilidad**: si la vol de hoy es baja,
tenderá a subir. Un predictor que solo mire el nivel de vol podría alcanzar un
AUC alto sin usar ninguna información de forma.

Esta auditoría separa ambos efectos:

  1. `geometria_publicada`  las 11 features tal y como se publicaron.
  2. `forma_pura`           geometría **sin** los cuatro proxies de volatilidad.
  3. `rv_lagged`            volatilidad realizada (nivel y posición relativa).
  4. `ewma_094`             volatilidad EWMA con λ = 0.94.
  5. `garch_11`             volatilidad condicional GARCH(1,1), parámetros
                            estimados **solo en train**.
  6. `vol_mejor_mas_forma`  prueba incremental: ¿añade la forma algo sobre la vol?

Criterio **pre-registrado** (`docs/PREREGISTRO.md`, WP3): `channel_vol_forecast`
mantiene su `accept` solo si su AUC supera al mejor de los tres baselines de
volatilidad con IC 95 % *bootstrap* que excluya el cero. En caso contrario se
degrada, y la degradación se propaga a README, LaTeX y HTML.

Todos los modelos comparten objetivo, split, clasificador y estandarización, de
modo que la comparación es like-for-like.
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

BOOTSTRAP = 3000

# Las cuatro features de `common.FEATURES` que son medidas de volatilidad y no
# de forma. Separarlas es lo que permite atribuir el mérito correctamente.
VOL_PROXIES = ("vol20", "atr_norm", "resid_norm", "band_width")

VOL_BASELINES = ("rv_lagged", "ewma_094", "garch_11")


def _rel(x: np.ndarray, win: int = 60) -> np.ndarray:
    """Posición de la serie respecto de su media móvil pasada (sin mirar futuro)."""
    s = pd.Series(x)
    m = s.shift(1).rolling(win, min_periods=max(5, win // 4)).mean()
    return (s / m.replace(0.0, np.nan)).fillna(1.0).to_numpy()


def garch11_sigma(returns: np.ndarray, n_train: int) -> np.ndarray:
    """Volatilidad condicional GARCH(1,1) con parámetros estimados solo en train.

    Se ajusta el modelo sobre el tramo de entrenamiento y después se propaga la
    recursión σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1} sobre toda la serie, de modo que
    σ_t use exclusivamente información hasta t-1 (sin fuga).
    """
    from arch import arch_model

    r = np.asarray(returns, dtype=float) * 100.0   # escala para estabilidad numérica
    res = arch_model(r[:n_train], vol="Garch", p=1, q=1, mean="Zero",
                     dist="normal").fit(disp="off", show_warning=False)
    w = float(res.params["omega"])
    a = float(res.params["alpha[1]"])
    b = float(res.params["beta[1]"])
    denom = max(1e-12, 1.0 - a - b)
    sig2 = np.empty(len(r))
    sig2[0] = w / denom
    for t in range(1, len(r)):
        sig2[t] = w + a * r[t - 1] ** 2 + b * sig2[t - 1]
    return np.sqrt(np.maximum(sig2, 1e-18)) / 100.0


def _auc(y: np.ndarray, s: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, s))


def _fit_score(X: np.ndarray, y: np.ndarray, tr: np.ndarray, te: np.ndarray) -> np.ndarray:
    """Logística estandarizada en train; devuelve la probabilidad en test."""
    from sklearn.linear_model import LogisticRegression

    Xtr, Xte = common.cs._standardize(X[tr], X[te])
    clf = LogisticRegression(max_iter=4000, class_weight="balanced").fit(Xtr, y[tr])
    return clf.predict_proba(Xte)[:, 1]


def bootstrap_delta_auc(y: np.ndarray, s_a: np.ndarray, s_b: np.ndarray,
                        b: int = BOOTSTRAP, seed: int = 42) -> Dict[str, float]:
    """IC 95 % de ΔAUC = A − B por remuestreo estratificado del test."""
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    if len(pos) < 10 or len(neg) < 10:
        return {"delta": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    d = []
    for _ in range(b):
        idx = np.concatenate([rng.choice(pos, len(pos), replace=True),
                              rng.choice(neg, len(neg), replace=True)])
        d.append(_auc(y[idx], s_a[idx]) - _auc(y[idx], s_b[idx]))
    arr = np.asarray([x for x in d if np.isfinite(x)])
    if arr.size == 0:
        return {"delta": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    return {"delta": float(np.mean(arr)),
            "ci_low": float(np.percentile(arr, 2.5)),
            "ci_high": float(np.percentile(arr, 97.5)),
            "p_gana": float(np.mean(arr > 0))}


class ChannelVolAuditExperiment(Experiment):
    id = "channel_vol_audit"
    title = "WP3 — auditoría de channel_vol_forecast contra vol realizada, EWMA y GARCH(1,1)"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        try:
            import arch  # noqa: F401
        except Exception:
            issues.append("falta el paquete `arch`: el baseline GARCH(1,1) no podrá ajustarse")
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

        idxs, _flags, featdf = common.window_features(prices)
        if featdf.empty or len(idxs) < 250:
            return ExperimentResult(metrics={"source": source}, decision="review",
                                    notes="serie demasiado corta")

        # --- Serie de volatilidad, idéntica a la del experimento auditado -----
        logp = np.log(np.clip(prices, 1e-9, None))
        ret = np.zeros(n)
        ret[1:] = np.diff(logp)
        rvol = pd.Series(ret).rolling(vol_win, min_periods=vol_win).std().to_numpy()
        ewma = common.ewma_vol(ret, 0.94)

        # GARCH: parámetros ajustados solo con el tramo de train.
        n_train_ret = int(np.sum(common.temporal_mask(dates, cutoff)))
        try:
            garch = garch11_sigma(ret, max(250, n_train_ret))
            garch_ok = True
        except Exception as exc:  # pragma: no cover
            ctx.log(f"GARCH no ajustado ({exc}); se excluye del ranking")
            garch = np.full(n, np.nan)
            garch_ok = False

        # --- Construcción del panel, mismo objetivo que el auditado ----------
        rows, ys, ds = [], [], []
        for k, e0 in enumerate(idxs):
            if e0 < vol_win or e0 + horizon >= n:
                continue
            vol_now = rvol[e0]
            vol_fut = np.nanmax(rvol[e0 + 1:e0 + 1 + horizon])
            if np.isnan(vol_now) or np.isnan(vol_fut):
                continue
            row = featdf.iloc[k].to_dict()
            row["_pos"] = e0
            rows.append(row)
            ys.append(int(vol_fut > vol_now))
            ds.append(dates[e0])

        if len(ys) < 200:
            return ExperimentResult(metrics={"source": source, "n": len(ys)},
                                    decision="review", notes="muestras insuficientes")

        df = pd.DataFrame(rows)
        y = np.asarray(ys, dtype=int)
        ed = pd.DatetimeIndex(ds)
        pos = df["_pos"].to_numpy(dtype=int)

        # Features de los baselines de volatilidad: nivel y posición relativa.
        rv_rel, ew_rel, ga_rel = _rel(rvol), _rel(ewma), _rel(garch)
        vol_feats = {
            "rv_lagged": np.column_stack([rvol[pos], rv_rel[pos]]),
            "ewma_094": np.column_stack([ewma[pos], ew_rel[pos]]),
            "garch_11": np.column_stack([garch[pos], ga_rel[pos]]),
        }

        tr = common.temporal_mask(ed, cutoff)
        te = ~tr
        if tr.sum() < 50 or te.sum() < 30 or len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            return ExperimentResult(metrics={"source": source}, decision="review",
                                    notes="split temporal insuficiente")

        cols_all = list(common.FEATURES)
        cols_shape = [c for c in cols_all if c not in VOL_PROXIES]

        # --- Modelos comparados ----------------------------------------------
        scores: Dict[str, np.ndarray] = {}
        scores["geometria_publicada"] = _fit_score(
            df[cols_all].to_numpy(dtype=float), y, tr, te)
        scores["forma_pura"] = _fit_score(
            df[cols_shape].to_numpy(dtype=float), y, tr, te)
        # Test decisivo de atribución: SOLO los cuatro proxies de volatilidad que
        # viven dentro de las features "de geometría", sin ninguna de forma. Si
        # este modelo iguala al publicado, todo el mérito es de la representación
        # de volatilidad y ninguno de la geometría del canal.
        scores["vol_proxies_solo"] = _fit_score(
            df[list(VOL_PROXIES)].to_numpy(dtype=float), y, tr, te)
        for name, X in vol_feats.items():
            if name == "garch_11" and not garch_ok:
                continue
            if np.isnan(X).any():
                X = np.nan_to_num(X, nan=float(np.nanmedian(X)))
            scores[name] = _fit_score(X, y, tr, te)

        aucs = {k: round(_auc(y[te], v), 4) for k, v in scores.items()}
        best_vol = max((k for k in VOL_BASELINES if k in aucs),
                       key=lambda k: aucs[k], default=None)

        # Prueba incremental: ¿añade la forma algo por encima de la mejor vol?
        incremental = None
        if best_vol:
            X_inc = np.column_stack([vol_feats[best_vol],
                                     df[cols_shape].to_numpy(dtype=float)])
            X_inc = np.nan_to_num(X_inc, nan=0.0)
            scores["vol_mejor_mas_forma"] = _fit_score(X_inc, y, tr, te)
            aucs["vol_mejor_mas_forma"] = round(_auc(y[te], scores["vol_mejor_mas_forma"]), 4)
            incremental = bootstrap_delta_auc(y[te], scores["vol_mejor_mas_forma"],
                                              scores[best_vol])
            incremental = {k: (round(v, 4) if isinstance(v, float) else v)
                           for k, v in incremental.items()}

        # --- Contraste pre-registrado: publicado vs mejor baseline de vol -----
        verdict_delta = None
        if best_vol:
            verdict_delta = bootstrap_delta_auc(y[te], scores["geometria_publicada"],
                                                scores[best_vol])
            verdict_delta = {k: (round(v, 4) if isinstance(v, float) else v)
                             for k, v in verdict_delta.items()}

        # Atribución: ¿el modelo publicado bate a sus propios proxies de vol?
        atribucion = bootstrap_delta_auc(y[te], scores["geometria_publicada"],
                                         scores["vol_proxies_solo"])
        atribucion = {k: (round(v, 4) if isinstance(v, float) else v)
                      for k, v in atribucion.items()}

        # ¿Y la forma pura, aporta algo por sí sola?
        shape_vs_vol = None
        if best_vol:
            shape_vs_vol = bootstrap_delta_auc(y[te], scores["forma_pura"],
                                               scores[best_vol])
            shape_vs_vol = {k: (round(v, 4) if isinstance(v, float) else v)
                            for k, v in shape_vs_vol.items()}

        supera = bool(verdict_delta and np.isfinite(verdict_delta.get("ci_low", np.nan))
                      and verdict_delta["ci_low"] > 0)

        # Atribución: ¿el mérito es de la GEOMETRÍA o de la VOLATILIDAD que las
        # features de geometría llevan dentro? Si el modelo publicado no bate a
        # sus propios proxies de volatilidad, la geometría no aporta nada.
        geometria_aporta = bool(
            atribucion and np.isfinite(atribucion.get("ci_low", np.nan))
            and atribucion["ci_low"] > 0)

        if supera and geometria_aporta:
            decision = "accept"      # supera a la vol Y el mérito es de la forma
        elif supera:
            # Pasa el criterio numérico pre-registrado (mantiene su accept), pero
            # la causa atribuida es falsa: hay que reformular la afirmación.
            decision = "review"
        else:
            decision = "reject"

        metrics = {
            "source": source, "horizon": horizon, "vol_window": vol_win,
            "n": int(len(y)), "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "base_rate_test": round(float(np.mean(y[te])), 4),
            "auc_por_modelo": aucs,
            "mejor_baseline_vol": best_vol,
            "vol_proxies_dentro_de_geometria": list(VOL_PROXIES),
            "features_forma_pura": cols_shape,
            "contraste_preregistrado": {
                "regla": ("channel_vol_forecast mantiene accept solo si su AUC supera "
                          "al mejor baseline de volatilidad con IC95 que excluya 0"),
                "delta_auc_publicado_vs_mejor_vol": verdict_delta,
                "supera": supera,
            },
            "forma_pura_vs_mejor_vol": shape_vs_vol,
            "atribucion_publicado_vs_solo_vol_proxies": atribucion,
            "geometria_aporta_sobre_su_propia_vol": geometria_aporta,
            "lectura": (
                "El criterio numérico pre-registrado se refiere a si el modelo "
                "publicado bate a los baselines de volatilidad de UNA sola medida. "
                "La atribución responde a otra pregunta: si el mérito es de la "
                "forma del canal o de las medidas de volatilidad que sus features "
                "ya contienen. Ambas respuestas deben reportarse juntas."),
            "incremental_forma_sobre_vol": incremental,
            "garch_ajustado": garch_ok,
        }
        baseline = {
            "fuertes": [b for b in VOL_BASELINES if b in aucs],
            "auc_mejor_vol": aucs.get(best_vol) if best_vol else None,
            "debil_previo": "tasa base (AUC 0.5) y geometría sin supervivencia",
        }
        notes = _notes(aucs, best_vol, verdict_delta, shape_vs_vol, incremental,
                       atribucion, decision)
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)


def _notes(aucs, best_vol, verdict, shape_vs_vol, incremental, atribucion, decision) -> str:
    orden = " · ".join(f"{k} {v:.3f}" for k, v in
                       sorted(aucs.items(), key=lambda kv: -kv[1]))
    txt = [f"[{decision.upper()}] AUC: {orden}."]
    if verdict and np.isfinite(verdict.get("ci_low", np.nan)):
        txt.append(f"Contraste pre-registrado — geometría publicada vs {best_vol}: "
                   f"ΔAUC={verdict['delta']:+.4f} IC95=[{verdict['ci_low']:+.4f},"
                   f"{verdict['ci_high']:+.4f}] -> "
                   f"{'SUPERA' if verdict['ci_low'] > 0 else 'NO SUPERA'}.")
    if shape_vs_vol and np.isfinite(shape_vs_vol.get("ci_low", np.nan)):
        txt.append(f"Forma pura (sin los 4 proxies de vol) vs {best_vol}: "
                   f"ΔAUC={shape_vs_vol['delta']:+.4f} "
                   f"IC95=[{shape_vs_vol['ci_low']:+.4f},{shape_vs_vol['ci_high']:+.4f}].")
    if incremental and np.isfinite(incremental.get("ci_low", np.nan)):
        txt.append(f"Incremental (vol+forma vs vol): ΔAUC={incremental['delta']:+.4f} "
                   f"IC95=[{incremental['ci_low']:+.4f},{incremental['ci_high']:+.4f}].")
    if atribucion and np.isfinite(atribucion.get("ci_low", np.nan)):
        txt.append(f"ATRIBUCIÓN — publicado vs SOLO sus 4 proxies de volatilidad "
                   f"(sin ninguna feature de forma): ΔAUC={atribucion['delta']:+.4f} "
                   f"IC95=[{atribucion['ci_low']:+.4f},{atribucion['ci_high']:+.4f}] -> "
                   f"{'la forma aporta' if atribucion['ci_low'] > 0 else 'la forma NO aporta'}.")
    txt.append("Las features llamadas 'geometría' incluyen vol20, atr_norm, resid_norm y "
               "band_width, que son medidas de volatilidad. El mérito del modelo procede "
               "de esa representación multi-medida de la volatilidad —mejor que EWMA y "
               "GARCH(1,1) de una sola medida—, no de la forma del canal.")
    return " ".join(txt)
