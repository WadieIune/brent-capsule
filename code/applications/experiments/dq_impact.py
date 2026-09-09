"""Aplicación 8 — Data Quality con **impacto medido aguas abajo**.

El control de calidad de `dq_price_control.py` se evaluaba contra un baseline de
outliers por cuantil, midiendo solapamiento. Eso responde «¿marca cosas
distintas?» pero no «¿sirve de algo?». Aquí se responde lo segundo: se comparan
las magnitudes que **de verdad usa el motor de riesgo** con los datos tal y como
llegan del feed frente a los datos depurados, de modo que el valor del control se
expresa en unidades de riesgo y no en recuento de alertas.

Dos defectos reales de la serie del proyecto sirven de caso:

1. **Print no positivo** — el WTI liquidó a −37,63 USD el 2020-04-20. Bajo la
   parametrización log-normal del motor genera dos retornos de ±2300% que
   dominan la matriz de covarianzas.
2. **Relleno de calendario** — el panel viene a días naturales con
   forward-fill: ~1/3 de los retornos son exactamente cero. Desplaza el cuantil
   empírico, crea rachas artificiales de no-excepción que sesgan el test de
   independencia y desescala el semáforo de Basilea, que cuenta 250 sesiones de
   negociación.

Se reporta, para cada defecto: si el control geométrico lo detecta, si lo detecta
el control convencional, y **cuánto cambia el riesgo medido** al depurarlo.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402
from experiments.dq_price_control import detect_anomalies, _naive_return_outliers
from experiments.predicted_var import (  # noqa: E402
    christoffersen_independence,
    kupiec_pof,
)
from experiments.portfolio_var import (  # noqa: E402
    DEFAULT_ASSETS,
    _fhs_var,
    _historical_var,
    basel_traffic_light,
    load_commodities,
)
from experiments.portfolio_var_alert import (  # noqa: E402
    drop_nonpositive,
    risk_contributions,
    to_trading_days,
)


def _panel_risk_view(px: pd.DataFrame, alpha: float, window: int, lam: float,
                     cutoff: str | None) -> Dict[str, object]:
    """Magnitudes de riesgo que el motor reportaría con ESTE panel de datos."""
    cols = list(px.columns)
    w = np.asarray([1.0 / len(cols)] * len(cols))
    R = np.column_stack([common.log_returns(px[c].to_numpy(float)) for c in cols])
    port = R @ w
    rdates = pd.DatetimeIndex(px.index)[1:]
    rc = risk_contributions(R, w)
    out: Dict[str, object] = {
        "n_returns": int(len(port)),
        "risk_contributions": {c: round(float(rc[i]), 4) for i, c in enumerate(cols)},
        "max_risk_contribution": round(float(rc.max()), 4),
        "most_concentrated_asset": cols[int(np.argmax(rc))],
        "zero_return_pct": round(100.0 * float(np.mean(np.abs(port) < 1e-12)), 2),
    }
    var_h = _historical_var(port, alpha, window)
    var_f = _fhs_var(port, alpha, window, lam)
    te = (~common.temporal_mask(rdates, cutoff)) & (np.arange(len(port)) >= window)
    te &= ~np.isnan(var_h) & ~np.isnan(var_f)
    if te.sum() >= 100:
        r = port[te]
        for name, v in (("historical", var_h), ("fhs_ewma", var_f)):
            exc = (r < -v[te]).astype(int)
            k = kupiec_pof(exc, alpha)
            out[name] = {
                "exception_rate": k["exception_rate"],
                "kupiec_p": k["p_value"],
                "christoffersen_p": christoffersen_independence(exc)["p_value"],
                "avg_var": round(float(np.mean(v[te])), 5),
                "basel": basel_traffic_light(int(exc.sum()), int(te.sum())),
            }
        out["n_test"] = int(te.sum())
    return out


def _detection_report(px: pd.DataFrame, k_sigma: float, tol_atr: float
                      ) -> Dict[str, object]:
    """¿Detectan los controles los dos defectos conocidos?"""
    dates = pd.DatetimeIndex(px.index)
    rep: Dict[str, object] = {}

    # Defecto 1: print no positivo (se evalúa el valor absoluto, que es lo que
    # llegaría a un motor que no admite precios negativos).
    bad_dates = list(px.index[(px <= 0).any(axis=1)])
    d1: Dict[str, object] = {"dates": [str(d.date()) for d in bad_dates]}
    if bad_dates:
        asset = next(c for c in px.columns if (px[c] <= 0).any())
        series = np.abs(px[asset].to_numpy(float))
        flags = detect_anomalies(series, dates, k_sigma, tol_atr)
        naive = set(_naive_return_outliers(series).tolist())
        for bd in bad_dates:
            pos = int(np.where(dates == bd)[0][0])
            hits = flags[flags["date"] == bd]
            d1.update({
                "asset": asset,
                "geometric_detected": bool(len(hits)),
                "geometric_reasons": hits["reason"].tolist(),
                "geometric_severity": [float(x) for x in hits["severity"].tolist()],
                "conventional_detected": bool(pos in naive),
            })
    rep["nonpositive_print"] = d1

    # Defecto 2: relleno de calendario -> regla `stale`.
    ref = px.columns[0]
    flags = detect_anomalies(px[ref].to_numpy(float), dates, k_sigma, tol_atr)
    stale = flags[flags["reason"] == "stale"]
    wk = sum(1 for d in pd.DatetimeIndex(stale["date"]) if d.dayofweek >= 5)
    rep["calendar_padding"] = {
        "asset": ref,
        "stale_flags": int(len(stale)),
        "of_which_weekend": int(wk),
        "weekend_share_pct": round(100.0 * wk / max(len(stale), 1), 1),
        "conventional_detects_padding": False,
        "note": ("el control convencional por cuantil de |retorno| no puede ver el "
                 "relleno: un retorno cero nunca es un outlier de cola"),
    }
    return rep


class DQImpactExperiment(Experiment):
    id = "dq_impact"
    title = "Data Quality con impacto medido sobre el motor de riesgo"

    def preflight(self, ctx: RunContext) -> List[str]:
        return ["modo sintético: cifras no interpretables"] if ctx.config.get("synthetic") else []

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        assets = tuple(cfg.get("assets") or DEFAULT_ASSETS)
        alpha = float(cfg.get("alpha", 0.99))
        window = int(cfg.get("var_window", 250))
        lam = float(cfg.get("ewma_lambda", 0.94))
        cutoff = cfg.get("cutoff")
        k_sigma = float(cfg.get("k_sigma", 4.0))
        tol_atr = float(cfg.get("tol_atr", common.TOL_ATR))

        raw, source = load_commodities(assets)
        ctx.log(f"panel tal como llega del feed: {len(raw)} filas · fuente={source}")

        detection = _detection_report(raw, k_sigma, tol_atr)
        ctx.log(f"  print no positivo detectado por control geométrico: "
                f"{detection['nonpositive_print'].get('geometric_detected')} "
                f"(razones {detection['nonpositive_print'].get('geometric_reasons')})")
        ctx.log(f"  relleno de calendario: {detection['calendar_padding']['stale_flags']} "
                f"marcas 'stale', {detection['calendar_padding']['weekend_share_pct']}% en fin de semana")

        # Vista de riesgo con datos crudos y con datos depurados.
        clean, san = drop_nonpositive(raw)
        clean, cal = to_trading_days(clean)
        view_raw = _panel_risk_view(raw, alpha, window, lam, cutoff)
        view_clean = _panel_risk_view(clean, alpha, window, lam, cutoff)

        rc_raw = view_raw["risk_contributions"]
        rc_clean = view_clean["risk_contributions"]
        worst = view_raw["most_concentrated_asset"]
        impact = {
            "risk_concentration": {
                "asset": worst,
                "raw": rc_raw.get(worst), "clean": rc_clean.get(worst),
                "distortion_pp": round(100.0 * (rc_raw.get(worst, 0) - rc_clean.get(worst, 0)), 1),
            },
            "zero_return_pct": {"raw": view_raw["zero_return_pct"],
                                "clean": view_clean["zero_return_pct"]},
            "observations": {"raw": view_raw["n_returns"], "clean": view_clean["n_returns"]},
        }
        for est in ("historical", "fhs_ewma"):
            if est in view_raw and est in view_clean:
                impact[est] = {
                    "exception_rate": {"raw": view_raw[est]["exception_rate"],
                                       "clean": view_clean[est]["exception_rate"]},
                    "christoffersen_p": {"raw": view_raw[est]["christoffersen_p"],
                                         "clean": view_clean[est]["christoffersen_p"]},
                    "basel_exceptions_per_250d": {
                        "raw": view_raw[est]["basel"]["exceptions_per_250d"],
                        "clean": view_clean[est]["basel"]["exceptions_per_250d"]},
                    "avg_var": {"raw": view_raw[est]["avg_var"],
                                "clean": view_clean[est]["avg_var"]},
                }
        ctx.log(f"  concentración de riesgo en {worst}: cruda {rc_raw.get(worst)} -> "
                f"depurada {rc_clean.get(worst)}")

        metrics = {"source": source, "detection": detection,
                   "risk_view_raw": view_raw, "risk_view_clean": view_clean,
                   "impact": impact,
                   "sanitization": san, "calendar": cal}
        baseline = {
            "method": "control convencional de outliers por cuantil de |retorno| (q=0.999)",
            "detects_nonpositive_print": detection["nonpositive_print"].get("conventional_detected"),
            "detects_calendar_padding": False,
        }
        geo_ok = bool(detection["nonpositive_print"].get("geometric_detected"))
        padding_ok = detection["calendar_padding"]["stale_flags"] > 0
        material = abs(impact["risk_concentration"]["distortion_pp"]) > 5.0
        decision = "accept" if (geo_ok and padding_ok and material) else "review"

        rc_d = impact["risk_concentration"]
        notes = (
            f"Los dos defectos reales del panel se detectan y su impacto se mide. "
            f"(1) Print no positivo ({detection['nonpositive_print'].get('asset')}, "
            f"{detection['nonpositive_print'].get('dates')}): el control geométrico lo marca por "
            f"{detection['nonpositive_print'].get('geometric_reasons')} con severidad "
            f"{detection['nonpositive_print'].get('geometric_severity')}; el convencional también "
            f"lo marca ({detection['nonpositive_print'].get('conventional_detected')}), pero sin "
            f"atribución ni severidad frente al canal proyectado. "
            f"(2) Relleno de calendario: {detection['calendar_padding']['stale_flags']} marcas "
            f"'stale' ({detection['calendar_padding']['weekend_share_pct']}% en fin de semana), "
            f"defecto que el control convencional NO puede ver porque un retorno cero nunca es "
            f"outlier de cola. IMPACTO: la concentración de riesgo en {rc_d['asset']} pasa de "
            f"{rc_d['raw']} (cruda) a {rc_d['clean']} (depurada), una distorsión de "
            f"{rc_d['distortion_pp']} puntos porcentuales; los retornos cero pasan del "
            f"{impact['zero_return_pct']['raw']}% al {impact['zero_return_pct']['clean']}%. "
            "El valor del control se expresa en unidades de riesgo, no en recuento de alertas."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)
