"""Aplicación 12 — El impacto en CAPITAL de la calidad del dato.

Esta es la aplicación práctica que cierra el trabajo, y es la única que **no
depende de predecir nada**. Todas las afirmaciones predictivas del proyecto han
caído: dirección, beneficio, cola del VaR, expansión de volatilidad y
persistencia de régimen. Lo que sobrevivió al escrutinio fue un hecho
estructural, no una predicción:

    Un retorno exactamente cero nunca es un valor atípico de la distribución de
    retornos. Por tanto un control convencional de cola es **ciego por
    construcción** al precio congelado y al relleno de calendario.

Ese punto ciego tiene una consecuencia medible en euros. Este experimento la
cuantifica sobre dos preguntas que un departamento de riesgo debe responder ante
su supervisor:

1. **¿Cuánto capital se deja de dotar por consumir dato sucio?**
   Se calcula el VaR y el capital regulatorio (`k · VaR`, con `k` del semáforo de
   Basilea) por dos vías idénticas salvo en la depuración del dato:
     - *tal cual se recibe*: panel de calendario con relleno hacia delante y
       precios de liquidación no positivos incluidos;
     - *depurado*: días hábiles reales y precios no positivos excluidos.

2. **¿Cuántas de las observaciones que se declaran para el RFET son reales?**
   Bajo FRTB (MAR31.12) un factor de riesgo es *modelizable* si acumula al menos
   24 observaciones anuales sin huecos de 90 días con menos de 4. Un precio
   arrastrado por *forward-fill* **no es una observación**, pero en un recuento
   ingenuo cuenta igual: infla la aparente observabilidad y puede hacer pasar por
   modelizable un factor que no lo es —lo que subestima el capital, esta vez por
   la vía del SES—.

Nota de honestidad metodológica: el efecto sobre el capital se **observó** al
corregir los defectos de datos de `portfolio_var`. Este experimento no es, por
tanto, una prueba a ciegas, sino la **confirmación reproducible y auditable** de
un efecto ya visto. Se declara así explícitamente para que nadie lo lea como un
hallazgo pre-registrado.
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
from experiments.portfolio_var import (  # noqa: E402
    DEFAULT_ASSETS,
    basel_multiplier,
    load_commodities,
)
from experiments.predicted_var import (  # noqa: E402
    christoffersen_independence,
    kupiec_pof,
)

# Criterios del RFET (FRTB MAR31.12).
RFET_MIN_OBS_YEAR = 24
RFET_GAP_DAYS = 90
RFET_MIN_OBS_GAP = 4


# --------------------------------------------------------------------------
# Depuración: lo que el control geométrico identifica y un control de cola no
# --------------------------------------------------------------------------
def sanitize(px: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Elimina precios no positivos y rellenos de calendario.

    Los dos defectos son reales y están documentados: el WTI liquidó a −37.63 USD
    el 2020-04-20, y el panel viene en frecuencia de calendario con *forward
    fill*, de modo que fines de semana y festivos aparecen como cierres.
    """
    out = px.copy()
    diag: Dict[str, object] = {}

    nonpos = (out <= 0).sum().sum()
    out = out.mask(out <= 0)
    diag["precios_no_positivos"] = int(nonpos)

    # Un día es relleno si NINGÚN activo del panel cambió de precio: en un día
    # hábil real es prácticamente imposible que todos repitan cierre.
    unchanged = (out.diff().abs().sum(axis=1) == 0)
    diag["dias_de_relleno"] = int(unchanged.sum())
    diag["pct_dias_de_relleno"] = round(100.0 * float(unchanged.mean()), 2)
    out = out[~unchanged].dropna()
    diag["sesiones_tras_depurar"] = int(len(out))
    return out, diag


# --------------------------------------------------------------------------
# VaR y capital por una vía dada
# --------------------------------------------------------------------------
def var_and_capital(px: pd.DataFrame, weights: np.ndarray, alpha: float,
                    window: int, cutoff: Optional[str]) -> Dict[str, object]:
    """VaR histórico y capital `k · VaR` sobre el panel que se le pase."""
    dates = pd.DatetimeIndex(px.index)
    R = np.column_stack([common.log_returns(px[c].to_numpy(float)) for c in px.columns])
    port = R @ weights
    rdates = dates[1:]

    var = np.full(len(port), np.nan)
    for t in range(window, len(port)):
        var[t] = -float(np.quantile(port[t - window:t], 1.0 - alpha))

    tr = common.temporal_mask(rdates, cutoff)
    te = (~tr) & (np.arange(len(port)) >= window) & ~np.isnan(var)
    if te.sum() < 100:
        return {"error": "test insuficiente", "n_test": int(te.sum())}

    r_te, v_te = port[te], var[te]
    exc = (r_te < -v_te).astype(int)
    n = len(exc)
    exc_250 = float(exc.sum()) * (250.0 / n)
    k, zona = basel_multiplier(exc_250)
    avg_var = float(np.mean(v_te))
    return {
        "n_test": int(n),
        "obs_por_año": round(365.25 * n / max((rdates[te][-1] - rdates[te][0]).days, 1), 1),
        "retornos_cero_pct": round(100.0 * float(np.mean(r_te == 0.0)), 2),
        "exception_rate": kupiec_pof(exc, alpha)["exception_rate"],
        "kupiec_p": kupiec_pof(exc, alpha)["p_value"],
        "christoffersen_p": christoffersen_independence(exc)["p_value"],
        "excepciones_por_250d": round(exc_250, 2),
        "multiplicador_basilea": k,
        "zona_basilea": zona,
        "var_medio": round(avg_var, 5),
        "capital": round(k * avg_var, 5),
    }


# --------------------------------------------------------------------------
# RFET: ¿cuántas observaciones declaradas son reales?
# --------------------------------------------------------------------------
def rfet_audit(px: pd.DataFrame) -> List[Dict[str, object]]:
    """Observabilidad declarada frente a real, por factor de riesgo."""
    rows: List[Dict[str, object]] = []
    for c in px.columns:
        s = px[c].dropna()
        if s.empty:
            continue
        real = s[s.diff() != 0]                     # solo cierres que cambian
        years = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)

        # Peor ventana de 90 días naturales, en recuento ingenuo y real.
        edges = pd.date_range(s.index.min(), s.index.max(), freq="90D")
        peor_ingenuo, peor_real = 10**9, 10**9
        for t0 in edges[:-1]:
            t1 = t0 + pd.Timedelta(days=RFET_GAP_DAYS)
            peor_ingenuo = min(peor_ingenuo, int(((s.index >= t0) & (s.index < t1)).sum()))
            peor_real = min(peor_real, int(((real.index >= t0) & (real.index < t1)).sum()))

        # Racha máxima de precio congelado.
        d = (s.diff() == 0).to_numpy()
        mx = run = 0
        for x in d:
            run = run + 1 if x else 0
            mx = max(mx, run)

        obs_decl = len(s) / years
        obs_real = len(real) / years
        rows.append({
            "factor": c,
            "obs_declaradas_año": round(obs_decl, 1),
            "obs_reales_año": round(obs_real, 1),
            "inflacion": round(obs_decl / max(obs_real, 1e-9), 2),
            "peor_90d_declarado": peor_ingenuo,
            "peor_90d_real": peor_real,
            "racha_congelado_max": int(mx),
            "modelizable_declarado": bool(obs_decl >= RFET_MIN_OBS_YEAR and peor_ingenuo >= RFET_MIN_OBS_GAP),
            "modelizable_real": bool(obs_real >= RFET_MIN_OBS_YEAR and peor_real >= RFET_MIN_OBS_GAP),
        })
    return rows


class DQCapitalImpactExperiment(Experiment):
    id = "dq_capital_impact"
    title = "Impacto en capital de la calidad del dato (VaR/Basilea) y observabilidad RFET"

    def preflight(self, ctx: RunContext) -> List[str]:
        return ["ANÁLISIS CONFIRMATORIO, no pre-registrado: el efecto sobre el "
                "capital se observó al corregir los datos de portfolio_var"]

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        alpha = float(cfg.get("alpha", 0.99))
        window = int(cfg.get("var_window", 250))
        cutoff = cfg.get("cutoff")
        assets = tuple(cfg.get("assets") or DEFAULT_ASSETS)

        px_raw, source = load_commodities(assets)
        w = np.repeat(1.0 / px_raw.shape[1], px_raw.shape[1])
        px_clean, diag = sanitize(px_raw)
        ctx.log(f"panel {source}: {len(px_raw)} filas -> {len(px_clean)} tras depurar "
                f"({diag['dias_de_relleno']} de relleno, {diag['precios_no_positivos']} no positivos)")

        via_sucia = var_and_capital(px_raw, w, alpha, window, cutoff)
        via_limpia = var_and_capital(px_clean, w, alpha, window, cutoff)
        if "error" in via_sucia or "error" in via_limpia:
            return ExperimentResult(metrics={"sucia": via_sucia, "limpia": via_limpia},
                                    decision="review", notes="muestra insuficiente")

        delta_var = via_limpia["var_medio"] / via_sucia["var_medio"] - 1.0
        delta_cap = via_limpia["capital"] / via_sucia["capital"] - 1.0
        subestimacion = 1.0 - via_sucia["capital"] / via_limpia["capital"]
        ctx.log(f"  VaR medio  sucio {via_sucia['var_medio']:.5f} -> limpio {via_limpia['var_medio']:.5f}")
        ctx.log(f"  capital    sucio {via_sucia['capital']:.5f} -> limpio {via_limpia['capital']:.5f} "
                f"({delta_cap:+.1%})")

        rfet = rfet_audit(px_raw)
        infl = float(np.mean([r["inflacion"] for r in rfet])) if rfet else float("nan")
        flip = [r["factor"] for r in rfet if r["modelizable_declarado"] and not r["modelizable_real"]]
        ctx.log(f"  RFET: inflación media de observabilidad x{infl:.2f}; "
                f"factores que dejarían de ser modelizables: {flip or 'ninguno'}")

        metrics = {
            "source": source,
            "analisis": "confirmatorio (no pre-registrado)",
            "depuracion": diag,
            "via_sucia_tal_cual_se_recibe": via_sucia,
            "via_limpia_tras_control_geometrico": via_limpia,
            "impacto_capital": {
                "delta_var_medio_pct": round(100.0 * delta_var, 2),
                "delta_capital_pct": round(100.0 * delta_cap, 2),
                "subestimacion_de_capital_pct": round(100.0 * subestimacion, 2),
                "lectura": ("Consumir el panel tal y como se recibe subestima el "
                            "capital por riesgo de mercado en ese porcentaje."),
            },
            "rfet": {
                "criterios": {"min_obs_año": RFET_MIN_OBS_YEAR,
                              "ventana_hueco_dias": RFET_GAP_DAYS,
                              "min_obs_en_hueco": RFET_MIN_OBS_GAP},
                "por_factor": rfet,
                "inflacion_media_observabilidad": round(infl, 2),
                "factores_que_dejarian_de_ser_modelizables": flip,
            },
            "por_que_un_control_de_cola_no_lo_ve": (
                "Un retorno exactamente cero nunca es un valor atípico de la "
                "distribución de retornos. La ceguera es estructural, no de "
                "calibración: demostrada en dq_synthetic_validation con recall "
                "0.00 de Hampel, Tukey e isolation forest sobre la familia stale."),
        }
        baseline = {
            "referencia": "el mismo cálculo de VaR y capital sobre el panel sin depurar",
            "capital_sin_depurar": via_sucia["capital"],
            "capital_depurado": via_limpia["capital"],
        }
        material = abs(subestimacion) >= 0.05
        decision = "accept" if material else "review"
        notes = (
            f"[ANÁLISIS CONFIRMATORIO] Depurar el panel ({diag['dias_de_relleno']} días de "
            f"relleno, {diag['precios_no_positivos']} precios no positivos) eleva el VaR medio "
            f"un {100*delta_var:+.1f}% y el capital un {100*delta_cap:+.1f}%: consumir el dato "
            f"tal cual se recibe **subestima el capital en {100*subestimacion:.1f}%**. "
            f"RFET: la observabilidad declarada está inflada x{infl:.2f} de media "
            f"(peor ventana de 90 días: {rfet[0]['peor_90d_declarado']} obs declaradas frente a "
            f"{rfet[0]['peor_90d_real']} reales en {rfet[0]['factor']}); factores que dejarían de "
            f"ser modelizables con el recuento real: {flip or 'ninguno en esta cartera líquida'}. "
            "Ningún control de cola detecta estos defectos: la ceguera es estructural."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)
