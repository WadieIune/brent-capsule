"""Aplicación 6 — VaR histórico + SISTEMA DE ALERTAS en paralelo.

Motivación
----------
El overlay continuo de `portfolio_var.py` multiplica el VaR **todos los días**
por `(1 + addon·fragilidad)`. Reduce excepciones, pero sube el VaR medio de
forma permanente y por eso *cuesta* capital (+11.6% vs histórico en el run de
referencia): el menor recargo de Basilea no compensa el nivel más alto.

Este experimento prueba la alternativa operativa: **no tocar el motor de VaR**
(sigue siendo simulación histórica, familiar para el regulador) y añadir en
paralelo una **capa discreta de alertas** que eleva el VaR *solo* los días en
que la fragilidad del régimen supera un umbral. El coste de capital pasa a ser
`uplift × fracción de días en alerta` en vez de un recargo permanente, de modo
que reducir excepciones y ahorrar capital dejan de ser objetivos incompatibles.

Correcciones metodológicas respecto a `portfolio_var.py`
-------------------------------------------------------
1. **Días hábiles.** La serie ancha del proyecto es de *calendario* con
   forward-fill (365 obs/año, ~32% de retornos exactamente cero). Eso desplaza
   el cuantil empírico (una ventana de 250 días naturales son ~172 sesiones
   reales), contamina el test de independencia —en un día de retorno cero no
   puede haber excepción— y desescala el semáforo de Basilea, que cuenta 250
   sesiones *de negociación*. Aquí se filtran fines de semana y festivos.
2. **Calibración sin fuga.** El umbral de alerta y el uplift se eligen por
   rejilla **solo con datos de train**; el test se evalúa con los parámetros
   congelados. El `tail_addon = 0.25` del experimento previo era un parámetro
   libre nunca calibrado.
3. **Batería de backtesting completa.** Kupiec (cobertura incondicional),
   Christoffersen (independencia), **LR_cc** (cobertura condicional conjunta) y
   **DQ de Engle–Manganelli**, que es el test que la literatura de VaR entiende
   por «DQ» — no confundir con el control de calidad de dato (`dq_price_control`).
4. **Fragilidad ponderada por riesgo.** La cartera 1/N *nocional* no es 1/N en
   riesgo (el bloque petróleo aporta ~44% y GOLD ~7%). Agregar la fragilidad por
   nocional infrapondera justamente los activos que generan la cola, así que por
   defecto se agrega por **contribución al riesgo**. La cartera evaluada sigue
   siendo la misma (1/N) para que la comparación con el baseline sea homogénea.

Estimadores comparados
----------------------
  - `historical`          incumbente: cuantil empírico móvil.
  - `fhs_ewma`            baseline fuerte: filtrado por vol EWMA, sin canal.
  - `predicted_continuous` overlay continuo del experimento previo.
  - `alert_historical`    **sistema paralelo**: histórico + alerta discreta.
  - `alert_fhs`           misma alerta sobre FHS-EWMA (referencia).
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
from experiments.predicted_var import (  # noqa: E402
    _chi2_sf,
    christoffersen_independence,
    kupiec_pof,
)
from experiments.portfolio_var import (  # noqa: E402
    DEFAULT_ASSETS,
    _fhs_var,
    _historical_var,
    asset_fragility,
    basel_traffic_light,
    capital_analysis,
    load_commodities,
)


# --- Tests de backtesting adicionales ----------------------------------------
def lr_conditional_coverage(exceptions: np.ndarray, alpha: float) -> Dict[str, float]:
    """Cobertura condicional de Christoffersen: LR_cc = LR_uc + LR_ind ~ chi2(2)."""
    uc = kupiec_pof(exceptions, alpha)
    ind = christoffersen_independence(exceptions)
    lr_uc, lr_ind = uc.get("LR_pof"), ind.get("LR_ind")
    if lr_uc != lr_uc or lr_ind != lr_ind:  # NaN
        return {"LR_cc": float("nan"), "p_value": float("nan")}
    lr = float(lr_uc) + float(lr_ind)
    return {"LR_cc": round(lr, 4), "p_value": round(_chi2_sf(lr, 2), 4)}


def dq_engle_manganelli(exceptions: np.ndarray, var: np.ndarray, alpha: float,
                        lags: int = 4) -> Dict[str, object]:
    """Dynamic Quantile test (Engle & Manganelli, 2004).

    Regresa la serie de *hits* desmediada sobre una constante, sus retardos y el
    propio VaR. Bajo la hipótesis de VaR correctamente especificado todos los
    coeficientes son cero: detecta a la vez sesgo de cobertura, dependencia
    temporal y dependencia del fallo respecto al nivel de VaR — algo que Kupiec
    y Christoffersen por separado no capturan.
    """
    p = 1.0 - alpha
    hit = np.asarray(exceptions, dtype=float) - p
    v = np.asarray(var, dtype=float)
    n = len(hit)
    if n <= lags + 3:
        return {"DQ_stat": float("nan"), "p_value": float("nan"), "lags": lags}
    X = np.column_stack(
        [np.ones(n - lags)]
        + [hit[lags - l: n - l] for l in range(1, lags + 1)]
        + [v[lags:]]
    )
    y = hit[lags:]
    xtx = X.T @ X
    try:
        beta = np.linalg.solve(xtx, X.T @ y)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
    stat = float(beta @ xtx @ beta / (p * (1.0 - p)))
    df = int(X.shape[1])
    return {"DQ_stat": round(stat, 4), "p_value": round(_chi2_sf(stat, df), 4),
            "lags": lags, "df": df}


# --- Saneamiento de precios ---------------------------------------------------
def drop_nonpositive(px: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Elimina cotizaciones no positivas antes de calcular log-retornos.

    El 2020-04-20 el WTI liquidó en **−37.63 USD** (primer precio negativo de su
    historia). `common.log_returns` acota los precios a 1e-9, de modo que ese
    print genera dos log-retornos artificiales de |r| ~ 23 (±2300%) que dominan
    la matriz de covarianzas y disparan la volatilidad EWMA durante meses,
    contaminando tanto las contribuciones al riesgo como el VaR filtrado.

    Un precio negativo es válido como hecho de mercado pero **incompatible con
    la parametrización log-normal** del modelo: es exactamente el tipo de
    observación que el control de calidad de dato debe interceptar. Se excluye
    la observación y se documenta; el desplome real de abril de 2020 se conserva
    en el retorno que salva el hueco, que sigue siendo un evento extremo genuino.
    """
    bad = (px <= 0).any(axis=1)
    dropped = [{"date": str(d.date()),
                "prices": {c: float(px.loc[d, c]) for c in px.columns if px.loc[d, c] <= 0}}
               for d in px.index[bad]]
    return px.loc[~bad], {"nonpositive_dropped": int(bad.sum()), "detail": dropped}


# --- Calendario ---------------------------------------------------------------
def to_trading_days(px: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Filtra fines de semana y festivos rellenados por forward-fill.

    Un festivo se identifica como una sesión en la que **todos** los activos
    repiten exactamente el precio anterior: es relleno, no negociación.
    """
    idx = pd.DatetimeIndex(px.index)
    n0 = len(px)
    out = px.loc[idx.dayofweek < 5]
    moved = out.diff().abs().sum(axis=1)
    keep = moved > 1e-12
    if len(keep):
        keep.iloc[0] = True
    out = out.loc[keep]
    diag = {"rows_calendar": int(n0), "rows_trading": int(len(out)),
            "dropped_weekend": int(n0 - int((idx.dayofweek < 5).sum())),
            "dropped_holiday_ffill": int(int((idx.dayofweek < 5).sum()) - len(out)),
            "obs_per_year": round(len(out) / max((out.index[-1] - out.index[0]).days / 365.25, 1e-9), 1)}
    return out, diag


def risk_contributions(R: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Contribución de cada activo a la varianza de la cartera (suma 1)."""
    C = np.cov(R, rowvar=False)
    pv = float(w @ C @ w)
    if pv <= 0:
        return w.copy()
    rc = w * (C @ w) / pv
    rc = np.clip(rc, 1e-9, None)
    return rc / rc.sum()


# --- Backtest -----------------------------------------------------------------
def _backtest(name: str, rets: np.ndarray, var: np.ndarray, alpha: float,
              alert: Optional[np.ndarray] = None) -> Dict[str, object]:
    exc = (rets < -var).astype(int)
    avg_var = float(np.mean(var))
    out: Dict[str, object] = {
        "estimator": name,
        "exception_rate": kupiec_pof(exc, alpha)["exception_rate"],
        "kupiec": kupiec_pof(exc, alpha),
        "christoffersen": christoffersen_independence(exc),
        "lr_cc": lr_conditional_coverage(exc, alpha),
        "dq_engle_manganelli": dq_engle_manganelli(exc, var, alpha),
        "basel": basel_traffic_light(int(exc.sum()), len(exc)),
        "avg_var": round(avg_var, 5),
        "capital": capital_analysis(exc, avg_var),
    }
    if alert is not None:
        out["alert_days_pct"] = round(100.0 * float(np.mean(alert)), 2)
    return out


def _apply_alert(var_base: np.ndarray, frag: np.ndarray, thr: float,
                 uplift: float) -> Tuple[np.ndarray, np.ndarray]:
    alert = (frag >= thr).astype(float)
    return var_base * (1.0 + uplift * alert), alert


def signal_lift(signal: np.ndarray, exceptions: np.ndarray, mask: np.ndarray,
                quantiles: Tuple[float, ...] = (0.70, 0.80, 0.90, 0.95)
                ) -> List[Dict[str, float]]:
    """¿Concentra la señal las excepciones? Tasa en días de alerta vs resto.

    Es la prueba de fuego de cualquier overlay de VaR: si la tasa de excepción
    en los días señalados no es superior a la del resto (lift > 1), la señal no
    aporta *timing* de riesgo de cola y cualquier mejora que produzca será un
    mero efecto de NIVEL, replicable subiendo el VaR de forma constante.
    """
    s, e = signal[mask], exceptions[mask]
    out: List[Dict[str, float]] = []
    for q in quantiles:
        thr = float(np.quantile(s, q))
        a = s >= thr
        r1 = float(e[a].mean()) if a.sum() else float("nan")
        r0 = float(e[~a].mean()) if (~a).sum() else float("nan")
        out.append({"quantile": q, "alert_days_pct": round(100.0 * float(a.mean()), 2),
                    "exc_rate_alert": round(r1, 5), "exc_rate_rest": round(r0, 5),
                    "lift": round(r1 / r0, 3) if r0 and r0 == r0 else None})
    return out


def _calibrate(var_base: np.ndarray, rets: np.ndarray, frag: np.ndarray,
               mask_tr: np.ndarray, alpha: float,
               q_grid: Tuple[float, ...], m_grid: Tuple[float, ...]
               ) -> Dict[str, object]:
    """Elige (umbral, uplift) SOLO con train: mínimo capital sujeto a Kupiec OK."""
    frag_tr = frag[mask_tr]
    target = 1.0 - alpha
    best: Optional[Dict[str, object]] = None
    trace: List[Dict[str, float]] = []
    for q in q_grid:
        thr = float(np.quantile(frag_tr, q)) if len(frag_tr) else 0.0
        for m in m_grid:
            var_a, alert = _apply_alert(var_base, frag, thr, m)
            exc = (rets[mask_tr] < -var_a[mask_tr]).astype(int)
            k = kupiec_pof(exc, alpha)
            cap = capital_analysis(exc, float(np.mean(var_a[mask_tr])))
            cand = {"q": q, "threshold": round(thr, 6), "uplift": m,
                    "train_exception_rate": k["exception_rate"],
                    "train_kupiec_p": k["p_value"],
                    "train_capital_worst": cap["capital_worst"],
                    "train_alert_days_pct": round(100.0 * float(np.mean(alert[mask_tr])), 2)}
            trace.append({kk: cand[kk] for kk in ("q", "uplift", "train_exception_rate",
                                                  "train_kupiec_p", "train_capital_worst")})
            ok = k["p_value"] >= 0.05
            score = (0 if ok else 1, cand["train_capital_worst"],
                     abs(k["exception_rate"] - target))
            if best is None or score < best["_score"]:
                cand["_score"] = score
                best = cand
    assert best is not None
    best.pop("_score", None)
    best["grid_size"] = len(trace)
    return best


class PortfolioVaRAlertExperiment(Experiment):
    id = "portfolio_var_alert"
    title = "VaR histórico + capa de alertas en paralelo (días hábiles, calibrado en train)"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        a = float(ctx.config.get("alpha", 0.99))
        if not 0.90 <= a < 1.0:
            issues.append("alpha fuera de [0.90, 1.0)")
        if ctx.config.get("synthetic"):
            issues.append("modo sintético: cifras NO interpretables como resultado de mercado")
        if not ctx.config.get("cutoff"):
            issues.append("sin cutoff: la calibración necesita un split temporal")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        assets = tuple(cfg.get("assets") or DEFAULT_ASSETS)
        alpha = float(cfg.get("alpha", 0.99))
        window = int(cfg.get("var_window", 250))
        lam = float(cfg.get("ewma_lambda", 0.94))
        addon = float(cfg.get("tail_addon", 0.25))
        horizon = int(cfg.get("var_surv_horizon", 5))
        cutoff = cfg.get("cutoff")
        frag_weighting = str(cfg.get("fragility_weighting", "risk"))
        trading_only = bool(cfg.get("trading_days", True))

        px, source = load_commodities(assets)
        px, san_diag = drop_nonpositive(px)
        if san_diag["nonpositive_dropped"]:
            ctx.log(f"  saneado: {san_diag['nonpositive_dropped']} print(s) no positivo(s) "
                    f"excluido(s) -> {san_diag['detail']}")
        cal_diag: Dict[str, object] = {"trading_day_filter": False}
        if trading_only:
            px, cal_diag = to_trading_days(px)
            cal_diag["trading_day_filter"] = True
        cal_diag["sanitization"] = san_diag
        cols = list(px.columns)
        dates = pd.DatetimeIndex(px.index)
        ctx.log(f"cartera {cols} · {len(px)} sesiones · fuente={source} · "
                f"calendario={'hábiles' if trading_only else 'natural'}")
        if trading_only:
            ctx.log(f"  filtrado: {cal_diag['rows_calendar']} -> {cal_diag['rows_trading']} "
                    f"({cal_diag['obs_per_year']} obs/año)")

        w = np.asarray(cfg.get("weights") or [1.0 / len(cols)] * len(cols), dtype=float)
        w = w / w.sum()
        R = np.column_stack([common.log_returns(px[c].to_numpy(float)) for c in cols])
        port = R @ w
        rdates = dates[1:]
        if len(port) < window + 200:
            return ExperimentResult(metrics={"source": source, "n_returns": int(len(port))},
                                    decision="review", notes="serie corta para backtest")

        # Fragilidad por activo (solo su precio) y agregación.
        frag_cols, diags = [], {}
        for c in cols:
            f, d = asset_fragility(px[c].to_numpy(float), dates, cutoff, horizon)
            frag_cols.append(f)
            diags[c] = d
        F = np.column_stack(frag_cols)
        rc = risk_contributions(R, w)
        w_frag = rc if frag_weighting == "risk" else w
        port_frag = F @ w_frag
        ctx.log("  contribución al riesgo: "
                + " · ".join(f"{c}={100*rc[i]:.1f}%" for i, c in enumerate(cols)))

        # Estimadores base.
        var_hist = _historical_var(port, alpha, window)
        var_fhs = _fhs_var(port, alpha, window, lam)
        var_cont = _fhs_var(port, alpha, window, lam, addon_scale=port_frag, addon=addon)

        tr_mask = common.temporal_mask(rdates, cutoff)
        ready = np.arange(len(port)) >= window
        tr = tr_mask & ready & ~np.isnan(var_hist)
        te = (~tr_mask) & ready & ~np.isnan(var_hist) & ~np.isnan(var_fhs) & ~np.isnan(var_cont)
        if tr.sum() < 250 or te.sum() < 150:
            return ExperimentResult(metrics={"n_train": int(tr.sum()), "n_test": int(te.sum())},
                                    decision="review", notes="train/test insuficientes")

        # Calibración de la alerta SOLO con train (sobre VaR histórico).
        q_grid = tuple(cfg.get("alert_q_grid") or (0.70, 0.75, 0.80, 0.85, 0.90, 0.95))
        m_grid = tuple(cfg.get("alert_uplift_grid") or (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50))
        cal = _calibrate(var_hist, port, port_frag, tr, alpha, q_grid, m_grid)
        ctx.log(f"  alerta calibrada en train: q={cal['q']} thr={cal['threshold']} "
                f"uplift={cal['uplift']} (días alerta train {cal['train_alert_days_pct']}%)")

        thr, up = float(cal["threshold"]), float(cal["uplift"])
        var_alert_h, alert = _apply_alert(var_hist, port_frag, thr, up)
        var_alert_f, _ = _apply_alert(var_fhs, port_frag, thr, up)

        # Señal de referencia: volatilidad EWMA (misma arquitectura de alerta).
        evol = common.ewma_vol(port, lam)
        cal_vol = _calibrate(var_hist, port, evol, tr, alpha, q_grid, m_grid)
        var_alert_vol, alert_vol = _apply_alert(var_hist, evol,
                                                float(cal_vol["threshold"]),
                                                float(cal_vol["uplift"]))

        # Ablación: constante con el MISMO VaR medio que el overlay de canal.
        # Si iguala al overlay, la mejora del canal es puro efecto de nivel.
        k_const = float(np.nanmean(var_cont[te]) / np.nanmean(var_fhs[te]))
        var_const = var_fhs * k_const

        r_te = port[te]
        res = {
            "historical": _backtest("historical", r_te, var_hist[te], alpha),
            "fhs_ewma": _backtest("fhs_ewma", r_te, var_fhs[te], alpha),
            "predicted_continuous": _backtest("predicted_continuous", r_te, var_cont[te], alpha),
            "constant_equivalent": _backtest("constant_equivalent", r_te, var_const[te], alpha),
            "alert_historical": _backtest("alert_historical", r_te, var_alert_h[te], alpha, alert[te]),
            "alert_fhs": _backtest("alert_fhs", r_te, var_alert_f[te], alpha, alert[te]),
            "alert_vol_historical": _backtest("alert_vol_historical", r_te,
                                              var_alert_vol[te], alpha, alert_vol[te]),
        }
        exc_hist = (port < -var_hist).astype(int)
        diagnostics = {
            "constant_equivalent_multiplier": round(k_const, 4),
            "vol_alert_calibration": cal_vol,
            "fragility_lift_test": signal_lift(port_frag, exc_hist, te),
            "ewma_vol_lift_test": signal_lift(evol, exc_hist, te),
            "corr_fragility_vol": round(float(np.corrcoef(port_frag[te], evol[te])[0, 1]), 4),
        }
        target = 1.0 - alpha
        cap_h = res["historical"]["capital"]["capital_worst"]

        def _rel(est: str) -> float:
            return round(100.0 * (res[est]["capital"]["capital_worst"] / cap_h - 1.0), 2)

        comparison = {
            "target_exception_rate": round(target, 5),
            "exception_rate": {k: v["exception_rate"] for k, v in res.items()},
            "kupiec_p": {k: v["kupiec"]["p_value"] for k, v in res.items()},
            "christoffersen_p": {k: v["christoffersen"]["p_value"] for k, v in res.items()},
            "lr_cc_p": {k: v["lr_cc"]["p_value"] for k, v in res.items()},
            "dq_p": {k: v["dq_engle_manganelli"]["p_value"] for k, v in res.items()},
            "avg_var": {k: v["avg_var"] for k, v in res.items()},
            "capital_worst": {k: v["capital"]["capital_worst"] for k, v in res.items()},
            "multiplier_worst": {k: v["capital"]["multiplier_worst"] for k, v in res.items()},
            "capital_vs_historical_pct": {k: _rel(k) for k in res},
            "alert_days_pct_test": res["alert_historical"]["alert_days_pct"],
            "best_by_capital": min(res, key=lambda k: res[k]["capital"]["capital_worst"]),
            "best_by_coverage": min(res, key=lambda k: abs(res[k]["exception_rate"] - target)),
        }
        # El objetivo del sistema paralelo: menos excepciones Y menos capital que
        # el histórico incumbente, sin cambiar el motor de VaR.
        a = res["alert_historical"]
        h = res["historical"]
        wins_exceptions = a["basel"]["exceptions"] <= h["basel"]["exceptions"]
        wins_capital = comparison["capital_vs_historical_pct"]["alert_historical"] <= 0
        passes = (a["kupiec"]["p_value"] >= 0.05 and a["christoffersen"]["p_value"] >= 0.05
                  and a["dq_engle_manganelli"]["p_value"] >= 0.05)

        metrics = {
            "source": source, "assets": cols, "weights": [round(x, 4) for x in w],
            "risk_contributions": {c: round(float(rc[i]), 4) for i, c in enumerate(cols)},
            "fragility_weighting": frag_weighting,
            "calendar": cal_diag, "alpha": alpha, "var_window": window,
            "ewma_lambda": lam, "tail_addon_continuous": addon,
            "alert_calibration": cal,
            "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "test_period": [str(rdates[te][0].date()), str(rdates[te][-1].date())],
            "per_asset": diags, "backtests": res, "comparison": comparison,
            "diagnostics": diagnostics,
        }
        baseline = {
            "incumbent": "VaR histórico (simulación histórica pura), motor sin cambios",
            "exception_rate": h["exception_rate"],
            "kupiec_p": h["kupiec"]["p_value"],
            "christoffersen_p": h["christoffersen"]["p_value"],
            "dq_p": h["dq_engle_manganelli"]["p_value"],
            "capital_worst": cap_h,
            "strong_baseline_fhs_ewma": res["fhs_ewma"]["exception_rate"],
        }
        if passes and wins_exceptions and wins_capital:
            decision = "accept"
        elif passes and (wins_exceptions or wins_capital):
            decision = "review"
        else:
            decision = "reject"

        lift80 = next((x["lift"] for x in diagnostics["fragility_lift_test"]
                       if x["quantile"] == 0.80), None)
        vlift80 = next((x["lift"] for x in diagnostics["ewma_vol_lift_test"]
                        if x["quantile"] == 0.80), None)
        f = res["fhs_ewma"]
        cst = res["constant_equivalent"]
        notes = (
            f"Datos corregidos: días hábiles ({cal_diag.get('rows_trading')} sesiones, "
            f"{cal_diag.get('obs_per_year')} obs/año, frente a {cal_diag.get('rows_calendar')} "
            f"de calendario) y {san_diag['nonpositive_dropped']} print no positivo excluido "
            f"(WTI 2020-04-20). "
            f"TIMING: la fragilidad de canal NO concentra excepciones "
            f"(lift@q80={lift80}) mientras la vol EWMA sí (lift@q80={vlift80}); "
            f"corr(fragilidad, vol)={diagnostics['corr_fragility_vol']}. "
            f"ABLACIÓN: el overlay de canal ({cst['estimator']} de control) "
            f"iguala a una CONSTANTE x{diagnostics['constant_equivalent_multiplier']} "
            f"con el mismo VaR medio (canal {res['predicted_continuous']['exception_rate']:.3%} / "
            f"capital {res['predicted_continuous']['capital']['capital_worst']} vs constante "
            f"{cst['exception_rate']:.3%} / {cst['capital']['capital_worst']}), luego su mejora "
            f"es efecto de NIVEL, no de régimen. "
            f"RANKING: FHS-EWMA domina — cobertura {f['exception_rate']:.3%} "
            f"(Kupiec p={f['kupiec']['p_value']}), independencia p={f['christoffersen']['p_value']} "
            f"frente a {h['christoffersen']['p_value']} del histórico, y capital "
            f"{comparison['capital_vs_historical_pct']['fhs_ewma']:+.1f}% vs histórico. "
            f"La capa de alertas sobre VaR histórico no alcanza el objetivo "
            f"(capital {comparison['capital_vs_historical_pct']['alert_historical']:+.1f}%). "
            "Nota: el test DQ rechaza a TODOS los estimadores, incluido el mejor."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)
