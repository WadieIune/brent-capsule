"""Aplicación 5 — Predicted VaR de una CARTERA multi-commodity.

Lleva el *predicted VaR* de un activo (`predicted_var.py`) a una cartera de
varias materias primas. Es la prueba de fuego de la tesis del proyecto: si para
entender el régimen de un activo **basta su propio precio**, entonces el mismo
tratamiento se replica activo por activo y se agrega a nivel cartera sin
necesitar un modelo multivariante de factores.

Diseño
------
Para cada commodity, y usando **solo su serie de precios**:
  1. se extraen episodios de canal (geometría de la 2ª pata);
  2. se ajusta la supervivencia con episodios **de train** y se obtiene la
     *propensión de ruptura* diaria `1 − P(T>k)` = fragilidad del régimen.

La fragilidad de la cartera es la media ponderada por peso de las fragilidades
individuales. El VaR se estima con tres estimadores para poder **atribuir** la
mejora a su causa real:

  - `historical`  (baseline débil): cuantil empírico de los retornos de cartera.
  - `fhs_ewma`    (baseline FUERTE): simulación histórica filtrada por vol EWMA,
    **sin ninguna información de canal**.
  - `predicted`   : `fhs_ewma` + add-on de cola escalado por la fragilidad de
    cartera.

La comparación `predicted` vs `fhs_ewma` es la que importa: aísla lo que aporta
la geometría del canal por encima del simple filtrado de volatilidad. Comparar
solo contra `historical` inflaría el mérito del canal atribuyéndole la mejora
que ya da el EWMA.

Backtest regulatorio sobre el tramo de test: excepciones, **Kupiec (POF)**,
**Christoffersen** (independencia) y **semáforo de Basilea**.
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
    christoffersen_independence,
    dq_engle_manganelli,
    kupiec_pof,
    lr_conditional_coverage,
)

DEFAULT_ASSETS = ("BRENT", "WTI", "GOLD", "SILVER", "COPPER", "NATGAS")

# Zonas del semáforo de Basilea para 250 días y 99% (Traffic Light Approach).
_BASEL_GREEN, _BASEL_YELLOW = 4, 9


def basel_traffic_light(exceptions: int, n: int) -> Dict[str, object]:
    """Semáforo de Basilea reescalado a la longitud real de la muestra."""
    scaled = exceptions * (250.0 / n) if n else float("nan")
    zone = ("verde" if scaled <= _BASEL_GREEN
            else "amarilla" if scaled <= _BASEL_YELLOW else "roja")
    return {"exceptions": int(exceptions), "n": int(n),
            "exceptions_per_250d": round(float(scaled), 2), "zone": zone}


def basel_multiplier(exceptions_250d: float) -> Tuple[float, str]:
    """Multiplicador `k` del Traffic Light Approach (BCBS) según excepciones/250d.

    El capital por riesgo de mercado en modelos internos es proporcional a
    `k · VaR`, de modo que **las excepciones sí consumen capital**: no solo
    importa el nivel del VaR, también el recargo por fallos de backtesting.
    """
    e = int(round(exceptions_250d))
    if e <= _BASEL_GREEN:
        return 3.00, "verde"
    if e <= _BASEL_YELLOW:
        return {5: 3.40, 6: 3.50, 7: 3.65, 8: 3.75, 9: 3.85}[e], "amarilla"
    return 4.00, "roja"


def capital_analysis(exceptions: np.ndarray, avg_var: float,
                     window: int = 250) -> Dict[str, object]:
    """Capital regulatorio aproximado: `k(excepciones) · VaR`, en dos escenarios.

    - *medio*: multiplicador según la tasa media de excepciones del test.
    - *peor ventana*: multiplicador según la peor ventana móvil de 250 sesiones,
      que es la que de verdad determina el recargo en un momento dado. Un VaR
      que agrupa excepciones puede estar bien en media y aun así migrar de zona
      en un episodio de estrés.
    """
    e = np.asarray(exceptions, dtype=int)
    n = len(e)
    avg_250 = float(e.sum()) * (250.0 / n) if n else float("nan")
    k_avg, z_avg = basel_multiplier(avg_250)

    roll = pd.Series(e).rolling(window).sum()
    worst = int(np.nanmax(roll.to_numpy())) if n >= window else int(e.sum())
    k_worst, z_worst = basel_multiplier(worst)
    return {
        "exceptions_per_250d_avg": round(avg_250, 2),
        "multiplier_avg": k_avg, "zone_avg": z_avg,
        "worst_250d_exceptions": worst,
        "multiplier_worst": k_worst, "zone_worst": z_worst,
        "avg_var": round(float(avg_var), 5),
        "capital_avg": round(float(k_avg * avg_var), 5),
        "capital_worst": round(float(k_worst * avg_var), 5),
    }


def _wide_dataset_path() -> Optional[str]:
    """Localiza `data/dataset_wide_with_target.csv` subiendo directorios."""
    d = _APP
    for _ in range(5):
        cand = os.path.join(d, "data", "dataset_wide_with_target.csv")
        if os.path.exists(cand):
            return cand
        d = os.path.dirname(d)
    return None


def load_commodities(assets: Tuple[str, ...]) -> Tuple[pd.DataFrame, str]:
    """Carga los precios de las commodities disponibles (o sintéticos)."""
    path = _wide_dataset_path()
    if path:
        df = pd.read_csv(path, parse_dates=["date"])
        cols = [a for a in assets if a in df.columns]
        if cols:
            out = df[["date"] + cols].dropna().set_index("date").sort_index()
            if len(out) > 500:
                return out, os.path.basename(path)
    # Fallback sintético: permite ejecutar sin la serie propietaria.
    rng = np.random.default_rng(42)
    base = common.synthetic_brent(1600, seed=42)
    data = {a: base.to_numpy() * (1.0 + 0.15 * rng.standard_normal(len(base)).cumsum() / 100.0)
            for a in assets}
    return pd.DataFrame(data, index=base.index), "synthetic"


def asset_fragility(prices: np.ndarray, dates: pd.DatetimeIndex,
                    cutoff: Optional[str], horizon: int) -> Tuple[np.ndarray, Dict[str, object]]:
    """Propensión de ruptura diaria `1 − P(T>k)` usando SOLO el precio del activo.

    Devuelve un vector alineado con los *retornos* (longitud n−1) y un
    diagnóstico del activo (episodios, vida mediana, método de supervivencia).
    """
    episodes = common.cs.extract_episodes(prices, dates)
    featurizer = common.SurvivalFeaturizer().fit(episodes, cutoff)
    idxs, _flags, featdf = common.window_features(prices)
    frag = np.zeros(max(len(prices) - 1, 0), dtype=float)
    if featurizer.method != "none" and not featdf.empty:
        pk = featurizer.predict_pk(featdf, horizon)
        prop = {int(e0): (1.0 - float(pk[k])) for k, e0 in enumerate(idxs)
                if pk[k] == pk[k]}
        for t in range(len(frag)):
            frag[t] = prop.get(t + 1, 0.0)   # el retorno t corresponde al precio t+1
    diag = {
        "n_episodes": int(len(episodes)),
        "median_life": (float(episodes["duration"].median()) if len(episodes) else None),
        "survival_method": featurizer.method,
        "mean_fragility": round(float(np.mean(frag)), 4) if len(frag) else None,
    }
    return frag, diag


def _fhs_var(rets: np.ndarray, alpha: float, window: int, lam: float,
             addon_scale: Optional[np.ndarray] = None,
             addon: float = 0.0) -> np.ndarray:
    """Simulación histórica filtrada por vol EWMA, con add-on de cola opcional."""
    vol = common.ewma_vol(rets, lam)
    var = np.full(len(rets), np.nan)
    for t in range(window, len(rets)):
        v = vol[t]
        if v <= 1e-12:
            var[t] = -float(np.quantile(rets[t - window:t], 1.0 - alpha))
            continue
        prev = vol[t - window:t]
        z = rets[t - window:t] / np.where(prev > 1e-12, prev, v)
        base = -float(np.quantile(z, 1.0 - alpha)) * v
        if addon_scale is not None and addon:
            base *= (1.0 + addon * float(addon_scale[t]))
        var[t] = base
    return var


def _historical_var(rets: np.ndarray, alpha: float, window: int) -> np.ndarray:
    var = np.full(len(rets), np.nan)
    for t in range(window, len(rets)):
        var[t] = -float(np.quantile(rets[t - window:t], 1.0 - alpha))
    return var


def _backtest(name: str, rets: np.ndarray, var: np.ndarray, alpha: float) -> Dict[str, object]:
    exc = (rets < -var).astype(int)
    k = kupiec_pof(exc, alpha)
    avg_var = float(np.mean(var))
    return {
        "estimator": name,
        "exception_rate": k["exception_rate"],
        "kupiec": k,
        "christoffersen": christoffersen_independence(exc),
        "lr_cc": lr_conditional_coverage(exc, alpha),
        "dq_engle_manganelli": dq_engle_manganelli(exc, var, alpha),
        "basel": basel_traffic_light(int(exc.sum()), len(exc)),
        "avg_var": round(avg_var, 5),
        "capital": capital_analysis(exc, avg_var),
    }


class PortfolioVaRExperiment(Experiment):
    id = "portfolio_var"
    title = "Predicted VaR de cartera multi-commodity (canal por activo, solo-precio)"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        a = float(ctx.config.get("alpha", 0.99))
        if not 0.90 <= a < 1.0:
            issues.append("alpha fuera de [0.90, 1.0)")
        if ctx.config.get("synthetic"):
            issues.append("modo sintético: cifras NO interpretables como resultado de mercado")
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

        px, source = load_commodities(assets)
        # Saneamiento y calendario: ver `portfolio_var_alert.py` para el detalle.
        # Sin esto, el print negativo del WTI (2020-04-20) genera log-retornos de
        # ±2300% que dominan la covarianza y la vol EWMA, y el relleno a días
        # naturales desescala el cuantil y el semáforo de Basilea.
        from experiments.portfolio_var_alert import drop_nonpositive, to_trading_days
        data_diag: Dict[str, object] = {}
        if bool(cfg.get("sanitize_prices", True)):
            px, san = drop_nonpositive(px)
            data_diag["sanitization"] = san
            if san["nonpositive_dropped"]:
                ctx.log(f"  saneado: {san['nonpositive_dropped']} print no positivo -> {san['detail']}")
        if bool(cfg.get("trading_days", True)):
            px, cal = to_trading_days(px)
            data_diag["calendar"] = cal
            ctx.log(f"  calendario: {cal['rows_calendar']} -> {cal['rows_trading']} sesiones "
                    f"({cal['obs_per_year']} obs/año)")
        cols = list(px.columns)
        dates = pd.DatetimeIndex(px.index)
        ctx.log(f"cartera: {len(cols)} activos {cols} · {len(px)} sesiones · fuente={source}")

        # Pesos: equiponderada por defecto (o los del config).
        w = np.asarray(cfg.get("weights") or [1.0 / len(cols)] * len(cols), dtype=float)
        w = w / w.sum()

        # Retornos por activo y de la cartera.
        R = np.column_stack([common.log_returns(px[c].to_numpy(float)) for c in cols])
        port = R @ w
        rdates = dates[1:]

        if len(port) < window + 150:
            return ExperimentResult(metrics={"source": source, "n_returns": int(len(port))},
                                    decision="review", notes="serie corta para backtest de VaR")

        # Fragilidad por activo (SOLO su precio) y agregación por pesos.
        frag_cols, diags = [], {}
        for j, c in enumerate(cols):
            f, d = asset_fragility(px[c].to_numpy(float), dates, cutoff, horizon)
            frag_cols.append(f)
            diags[c] = d
            ctx.log(f"  {c:<7} episodios={d['n_episodes']:>4} vida_mediana="
                    f"{d['median_life']} surv={d['survival_method']}")
        F = np.column_stack(frag_cols)
        port_frag = F @ w

        # Tres estimadores de VaR.
        var_hist = _historical_var(port, alpha, window)
        var_fhs = _fhs_var(port, alpha, window, lam)
        var_pred = _fhs_var(port, alpha, window, lam, addon_scale=port_frag, addon=addon)

        tr = common.temporal_mask(rdates, cutoff)
        te = (~tr) & (np.arange(len(port)) >= window)
        valid = te & ~np.isnan(var_hist) & ~np.isnan(var_fhs) & ~np.isnan(var_pred)
        if valid.sum() < 150:
            return ExperimentResult(metrics={"source": source, "n_test": int(valid.sum())},
                                    decision="review", notes="test insuficiente")

        # Control de NIVEL: constante con el mismo VaR medio que el overlay.
        k_const = float(np.mean(var_pred[valid]) / np.mean(var_fhs[valid]))
        var_const = var_fhs * k_const

        r_te = port[valid]
        res = {
            "historical": _backtest("historical", r_te, var_hist[valid], alpha),
            "fhs_ewma": _backtest("fhs_ewma", r_te, var_fhs[valid], alpha),
            "predicted": _backtest("predicted", r_te, var_pred[valid], alpha),
            "constant_equivalent": _backtest("constant_equivalent", r_te, var_const[valid], alpha),
        }
        target = 1.0 - alpha
        dist = {k: abs(v["exception_rate"] - target) for k, v in res.items()}
        best = min(dist, key=dist.get)

        # Atribución en DOS dimensiones: un VaR puede fallar por nivel (cobertura,
        # Kupiec) o por agrupación de excepciones (independencia, Christoffersen).
        # Cada componente del estimador arregla una cosa distinta, y reportar solo
        # la cobertura ocultaría el papel del filtrado EWMA.
        ind_p = {k: res[k]["christoffersen"]["p_value"] for k in res}
        attribution = {
            "target_exception_rate": round(target, 5),
            "coverage": {
                "gap_historical": round(dist["historical"], 5),
                "gap_fhs_ewma": round(dist["fhs_ewma"], 5),
                "gap_predicted": round(dist["predicted"], 5),
                "gain_from_ewma_filtering": round(dist["historical"] - dist["fhs_ewma"], 5),
                "gain_from_channel_addon": round(dist["fhs_ewma"] - dist["predicted"], 5),
            },
            "independence_p_value": ind_p,
            "independence_gain_from_ewma": round(
                float(ind_p["fhs_ewma"] - ind_p["historical"]), 4),
            # Coste en CAPITAL, no solo en nivel de VaR. Bajo modelos internos el
            # capital es proporcional a k(excepciones)·VaR: las excepciones sí
            # consumen capital vía el recargo del semáforo, de modo que reducirlas
            # puede compensar un VaR más alto... o no. Se reporta el balance real.
            "capital_cost": {
                est: {
                    "avg_var": res[est]["avg_var"],
                    "multiplier_worst_250d": res[est]["capital"]["multiplier_worst"],
                    "zone_worst_250d": res[est]["capital"]["zone_worst"],
                    "capital_worst": res[est]["capital"]["capital_worst"],
                } for est in ("historical", "fhs_ewma", "predicted")
            },
            "capital_predicted_vs_historical_pct": round(
                100.0 * (res["predicted"]["capital"]["capital_worst"]
                         / res["historical"]["capital"]["capital_worst"] - 1.0), 2),
            "capital_predicted_vs_fhs_pct": round(
                100.0 * (res["predicted"]["capital"]["capital_worst"]
                         / res["fhs_ewma"]["capital"]["capital_worst"] - 1.0), 2),
            "best_estimator": best,
            # Control decisivo: ¿bate el overlay a una constante con su mismo
            # nivel medio de VaR? Si no, la mejora no viene del régimen.
            "constant_equivalent_multiplier": round(k_const, 4),
            "channel_beats_constant": bool(dist["predicted"] < dist["constant_equivalent"]),
            "reading": ("El filtrado EWMA corrige la AGRUPACIÓN de excepciones "
                        "(Christoffersen). El add-on de canal desplaza el NIVEL, "
                        "pero el control `constant_equivalent` muestra que una "
                        "constante del mismo VaR medio logra lo mismo: la señal "
                        "de canal no aporta timing de cola. En CAPITAL el overlay "
                        "es además más caro, porque el menor recargo de Basilea no "
                        "compensa el VaR más alto."),
        }
        metrics = {
            "source": source, "data_quality": data_diag,
            "assets": cols, "weights": [round(x, 4) for x in w],
            "alpha": alpha, "var_window": window, "ewma_lambda": lam,
            "tail_addon": addon, "survival_horizon": horizon,
            "n_test": int(valid.sum()),
            "test_period": [str(rdates[valid][0].date()), str(rdates[valid][-1].date())],
            "mean_portfolio_fragility": round(float(np.mean(port_frag[valid])), 4),
            "per_asset": diags,
            "backtests": res,
            "attribution": attribution,
        }
        baseline = {
            "weak": "VaR histórico (cuantil empírico)",
            "strong": "FHS-EWMA sin información de canal",
            "gap_historical": attribution["coverage"]["gap_historical"],
            "gap_fhs_ewma": attribution["coverage"]["gap_fhs_ewma"],
            "christoffersen_p_historical": ind_p["historical"],
            "christoffersen_p_fhs_ewma": ind_p["fhs_ewma"],
        }

        pred_ok = (res["predicted"]["kupiec"]["p_value"] >= 0.05
                   and res["predicted"]["christoffersen"]["p_value"] >= 0.05)
        beats_strong = attribution["coverage"]["gain_from_channel_addon"] > 0
        beats_const = attribution["channel_beats_constant"]
        if pred_ok and beats_strong and beats_const:
            decision = "accept"
        elif pred_ok and (beats_strong or beats_const):
            decision = "review"
        else:
            decision = "reject"

        notes = (
            f"[datos corregidos: saneado de precios no positivos + días hábiles] "
            f"Cartera {len(cols)} commodities equiponderada, {int(valid.sum())} "
            f"sesiones de test. Cobertura (objetivo {target:.2%}): histórico "
            f"{res['historical']['exception_rate']:.3%} · FHS-EWMA "
            f"{res['fhs_ewma']['exception_rate']:.3%} · predicted "
            f"{res['predicted']['exception_rate']:.3%} -> mejor: {best}. "
            f"Independencia (Christoffersen p): histórico {ind_p['historical']:.4f} "
            f"{'(RECHAZA: excepciones agrupadas)' if ind_p['historical'] < 0.05 else ''} -> "
            f"FHS-EWMA {ind_p['fhs_ewma']:.4f} -> predicted {ind_p['predicted']:.4f}. "
            f"Cada pieza arregla algo distinto: el EWMA desagrupa las excepciones y "
            f"el canal ajusta el nivel, pero una CONSTANTE x{k_const:.3f} del mismo "
            f"VaR medio iguala al overlay (bate_a_constante={beats_const}), luego el "
            f"canal no aporta timing de cola. CAPITAL (k·VaR con el multiplicador de la "
            f"peor ventana de 250d): predicted {attribution['capital_predicted_vs_historical_pct']:+.1f}% "
            f"vs histórico y {attribution['capital_predicted_vs_fhs_pct']:+.1f}% vs FHS-EWMA "
            f"-> el menor recargo (k {res['historical']['capital']['multiplier_worst']:.2f} -> "
            f"{res['predicted']['capital']['multiplier_worst']:.2f}) NO compensa el VaR más alto; "
            f"el overlay se justifica por validación/gobernanza, no por ahorro de capital. "
            "El régimen de cada activo se estima con su PROPIO precio: la tesis "
            "solo-precio escala a cartera sin modelo multivariante de factores."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)
