"""Aplicación 7 — FRTB (IMA) exportable: ES 97.5%, horizontes de liquidez,
ES estresado, IMCC y **impacto en capital del cambio de modelo**.

Para qué sirve
--------------
La cápsula calcula hoy capital al estilo *modelos internos Basilea 2.5*:
`k · VaR(99%)`, con `k` del semáforo de backtesting. FRTB sustituye esa métrica
por **Expected Shortfall al 97.5%** con **horizontes de liquidez** por clase de
factor, calibrado a un **periodo de estrés**. Este módulo deja preparada la
migración: produce las magnitudes IMA y las compara con el capital actual, de
modo que el cambio de modelo de riesgo sea una decisión cuantificada y no una
reimplementación desde cero.

Qué se calcula (y con qué estatus)
----------------------------------
| magnitud | estatus |
|---|---|
| ES 97.5% 1-día (FHS-EWMA) | calculado |
| escalado a 10 días y a horizonte de liquidez (MAR33.5) | calculado |
| periodo de estrés y ES estresado | calculado |
| IMCC (MAR33.6) | calculado con ratio reducido/completo = 1 |
| backtesting FRTB (VaR 97.5% y 99%) y recargo del multiplicador | calculado |
| RFET / NMRF y SES | **proxy**: requiere datos por factor de riesgo |
| PLA test (P&L attribution) | **no calculable**: requiere P&L hipotético y teórico de mesa |

Horizontes de liquidez
----------------------
Los LH **los fija la norma** por clase de factor (MAR33.12), no se estiman: para
commodities de energía, metales preciosos y no férreos, LH = 20 sesiones; otras
materias primas, 60. La vida mediana del canal que estima la 2ª pata del proyecto
se reporta como *evidencia empírica de apoyo* al cubo prescrito, nunca como
sustituto — presentarla como estimación propia invalidaría el cálculo.

Salida exportable
-----------------
Escribe `frtb_export.json` con un esquema estable (parámetros, series agregadas y
resultados) pensado para alimentar un motor FRTB corporativo, más un CSV con la
serie diaria de ES y VaR.
"""
from __future__ import annotations

import json
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
from experiments.predicted_var import kupiec_pof  # noqa: E402
from experiments.portfolio_var import (  # noqa: E402
    DEFAULT_ASSETS,
    basel_multiplier,
    load_commodities,
)
from experiments.portfolio_var_alert import (  # noqa: E402
    drop_nonpositive,
    to_trading_days,
)

# MAR33.12 — horizontes de liquidez por clase de factor (sesiones).
LH_BY_CLASS = {
    "commodity_energy": 20, "commodity_precious_metal": 20,
    "commodity_base_metal": 20, "commodity_other": 60,
    "commodity_volatility": 60,
}
ASSET_CLASS = {
    "BRENT": "commodity_energy", "WTI": "commodity_energy",
    "NATGAS": "commodity_energy", "GOLD": "commodity_precious_metal",
    "SILVER": "commodity_precious_metal", "COPPER": "commodity_base_metal",
    "COFFEE": "commodity_other",
}
BASE_T = 10          # horizonte base del ES en FRTB (sesiones)
RHO_IMCC = 0.5       # ponderación del agregado en IMCC (MAR33.6)


def _filtered_z(rets: np.ndarray, window: int, lam: float) -> Tuple[np.ndarray, np.ndarray]:
    """Devuelve (vol EWMA, residuos estandarizados) para simulación filtrada."""
    vol = common.ewma_vol(rets, lam)
    safe = np.where(vol > 1e-12, vol, np.nan)
    return vol, rets / safe


def expected_shortfall_fhs(rets: np.ndarray, alpha: float, window: int,
                           lam: float) -> Tuple[np.ndarray, np.ndarray]:
    """ES y VaR al nivel `alpha` por simulación histórica filtrada (FHS-EWMA).

    El ES es la media de la cola más allá del cuantil: a diferencia del VaR sí es
    subaditivo y describe la severidad, que es la razón por la que FRTB lo adopta.
    """
    vol, z = _filtered_z(rets, lam=lam, window=window)
    es = np.full(len(rets), np.nan)
    var = np.full(len(rets), np.nan)
    for t in range(window, len(rets)):
        zw = z[t - window:t]
        zw = zw[~np.isnan(zw)]
        if zw.size < 30 or vol[t] <= 1e-12:
            continue
        q = float(np.quantile(zw, 1.0 - alpha))
        tail = zw[zw <= q]
        var[t] = -q * vol[t]
        es[t] = -float(tail.mean()) * vol[t] if tail.size else -q * vol[t]
    return es, var


def scale_to_liquidity_horizon(es_10d: float, lh: int, base_t: int = BASE_T) -> float:
    """Escala el ES de `base_t` sesiones al horizonte de liquidez (MAR33.5).

    Con todos los factores en un mismo cubo LH la fórmula de agregación colapsa
    en `ES(T) · sqrt(LH/T)`; se implementa así y se documenta el supuesto.
    """
    return float(es_10d) * float(np.sqrt(lh / base_t))


def portfolio_liquidity_horizon(assets: List[str], weights: np.ndarray) -> Dict[str, object]:
    """LH de cartera: el más conservador (mayor) de los factores presentes."""
    lhs = {a: LH_BY_CLASS[ASSET_CLASS.get(a, "commodity_other")] for a in assets}
    return {"per_asset": lhs, "portfolio_lh": int(max(lhs.values())),
            "rule": "MAR33.12; se aplica el LH más largo entre los factores de la cartera"}


def stress_period(rets: np.ndarray, dates: pd.DatetimeIndex, window: int
                  ) -> Dict[str, object]:
    """Ventana de máxima pérdida acumulada: candidata al periodo de estrés IMA."""
    if len(rets) <= window:
        return {}
    cum = pd.Series(rets).rolling(window).sum().to_numpy()
    end = int(np.nanargmin(cum))
    return {"start_date": str(dates[max(end - window, 0)].date()),
            "end_date": str(dates[end].date()),
            "cum_log_return": round(float(cum[end]), 4),
            "window_sessions": int(window),
            "slice": (int(max(end - window, 0)), int(end))}


def frtb_backtest_addon(exc_99: int, n: int) -> Dict[str, object]:
    """Recargo del multiplicador por backtesting (tabla MAR33.44), a 250 sesiones."""
    scaled = int(round(exc_99 * (250.0 / n))) if n else 0
    if scaled <= 4:
        addon, zone = 0.00, "verde"
    elif scaled <= 9:
        addon, zone = {5: 0.15, 6: 0.19, 7: 0.25, 8: 0.29, 9: 0.33}[scaled], "ámbar"
    else:
        addon, zone = 0.50, "roja"
    return {"exceptions_99_per_250d": scaled, "addon": addon, "zone": zone,
            "m_c": round(1.5 + addon, 2)}


def rfet_proxy(px: pd.DataFrame) -> Dict[str, object]:
    """Proxy de modelabilidad (RFET). NO sustituye al conteo oficial.

    El RFET exige, por factor de riesgo, ≥24 precios *reales y verificables* al
    año sin huecos > 1 mes. Aquí solo se observa si el precio se movió, que es
    condición necesaria pero no suficiente: no acredita que el precio sea
    ejecutable ni su procedencia. Se reporta como señal, no como certificación.
    """
    out: Dict[str, object] = {}
    for c in px.columns:
        moved = px[c].diff().abs() > 1e-12
        per_y = moved.groupby(px.index.year).sum()
        gap, mx = 0, 0
        for m in moved.to_numpy():
            gap = 0 if m else gap + 1
            mx = max(mx, gap)
        out[c] = {"min_real_moves_per_year": int(per_y.min()),
                  "max_gap_sessions": int(mx),
                  "modellable_proxy": bool(per_y.min() >= 24 and mx <= 21)}
    return out


class FRTBCapitalExperiment(Experiment):
    id = "frtb_capital"
    title = "FRTB IMA exportable: ES 97.5%, LH, ES estresado, IMCC y cambio de modelo"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        if ctx.config.get("synthetic"):
            issues.append("modo sintético: cifras NO interpretables")
        if not ctx.config.get("cutoff"):
            issues.append("sin cutoff: se usa toda la muestra como periodo actual")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        assets = tuple(cfg.get("assets") or DEFAULT_ASSETS)
        window = int(cfg.get("var_window", 250))
        lam = float(cfg.get("ewma_lambda", 0.94))
        es_alpha = float(cfg.get("es_alpha", 0.975))
        stress_win = int(cfg.get("stress_window", 250))
        cutoff = cfg.get("cutoff")

        px, source = load_commodities(assets)
        px, san = drop_nonpositive(px)
        px, cal = to_trading_days(px)
        cols = list(px.columns)
        dates = pd.DatetimeIndex(px.index)
        w = np.asarray(cfg.get("weights") or [1.0 / len(cols)] * len(cols), dtype=float)
        w = w / w.sum()
        R = np.column_stack([common.log_returns(px[c].to_numpy(float)) for c in cols])
        port = R @ w
        rdates = dates[1:]
        ctx.log(f"cartera {cols} · {len(port)} retornos · fuente={source} "
                f"(saneado {san['nonpositive_dropped']}, hábiles {cal['obs_per_year']}/año)")

        if len(port) < window + 300:
            return ExperimentResult(metrics={"n_returns": int(len(port))},
                                    decision="review", notes="serie corta")

        # --- 1) ES 97.5% y VaR (99% y 97.5%) por FHS-EWMA -------------------
        es, var_es = expected_shortfall_fhs(port, es_alpha, window, lam)
        _, var99 = expected_shortfall_fhs(port, 0.99, window, lam)
        ok = ~np.isnan(es) & ~np.isnan(var99)
        te = ok & (~common.temporal_mask(rdates, cutoff) if cutoff else ok)
        if te.sum() < 150:
            te = ok
        r_te = port[te]

        # --- 2) Horizonte de liquidez (prescrito) ---------------------------
        lh_info = portfolio_liquidity_horizon(cols, w)
        lh = int(lh_info["portfolio_lh"])
        es_1d = float(np.mean(es[te]))
        es_10d = es_1d * float(np.sqrt(BASE_T))
        es_lh = scale_to_liquidity_horizon(es_10d, lh)
        ctx.log(f"  ES{es_alpha:.3%} 1d={es_1d:.5f} · 10d={es_10d:.5f} · LH={lh} -> {es_lh:.5f}")

        # Evidencia empírica de apoyo (NO sustituye al LH normativo).
        eps = common.cs.extract_episodes(px[cols[0]].to_numpy(float), dates)
        median_life = (float(eps.loc[eps["event"] == 1, "duration"].median())
                       if len(eps) and eps["event"].sum() else None)

        # --- 3) Periodo de estrés y ES estresado ----------------------------
        sp = stress_period(port, rdates, stress_win)
        es_stressed = None
        if sp:
            a, b = sp["slice"]
            seg = port[a:b]
            if len(seg) > 30:
                q = float(np.quantile(seg, 1.0 - es_alpha))
                tail = seg[seg <= q]
                es_s_1d = -float(tail.mean()) if tail.size else -q
                es_stressed = scale_to_liquidity_horizon(es_s_1d * float(np.sqrt(BASE_T)), lh)
        # IMCC (MAR33.6): ES_{R,S} · (ES_{F,C} / ES_{R,C}); sin conjunto reducido
        # el ratio es 1 y IMCC = ES estresado con LH.
        imcc = es_stressed if es_stressed is not None else es_lh
        ratio_note = "ratio ES_FC/ES_RC = 1 (no hay conjunto reducido de factores)"

        # --- 4) Backtesting FRTB y multiplicador ----------------------------
        exc99 = int((r_te < -var99[te]).sum())
        exc975 = int((r_te < -var_es[te]).sum())
        bt = frtb_backtest_addon(exc99, int(te.sum()))
        k99 = kupiec_pof((r_te < -var99[te]).astype(int), 0.99)

        # --- 5) Capital: modelo actual (Basilea 2.5) vs FRTB IMA ------------
        # Comparación homogénea. El IMCC va a 10 días y luego a LH, y está
        # calibrado a estrés; enfrentarlo a un VaR de 1 día y sin estresar
        # inflaría artificialmente el salto. Por eso el lado actual se lleva
        # también a 10 días y se le añade el VaR estresado, que es lo que exige
        # Basilea 2.5: capital = k·VaR(10d) + k_s·sVaR(10d).
        avg_var99_1d = float(np.mean(var99[te]))
        sqrtT = float(np.sqrt(BASE_T))
        avg_var99_10d = avg_var99_1d * sqrtT
        svar99_10d = None
        if sp:
            a, b = sp["slice"]
            seg = port[a:b]
            if len(seg) > 30:
                svar99_10d = -float(np.quantile(seg, 0.01)) * sqrtT
        k_basel, zone_basel = basel_multiplier(exc99 * (250.0 / int(te.sum())))
        capital_current = k_basel * (avg_var99_10d + (svar99_10d or 0.0))
        capital_frtb = bt["m_c"] * imcc                          # m_c · IMCC (parte modelizable)
        delta_pct = 100.0 * (capital_frtb / capital_current - 1.0) if capital_current else float("nan")
        ctx.log(f"  Basilea 2.5 k·(VaR10d+sVaR10d) = {capital_current:.5f} · "
                f"FRTB m_c·IMCC = {capital_frtb:.5f} ({delta_pct:+.1f}%)")

        # --- 6) RFET / NMRF -------------------------------------------------
        rfet = rfet_proxy(px)
        nmrf = [c for c, v in rfet.items() if not v["modellable_proxy"]]

        # --- 7) Paquete exportable -----------------------------------------
        export = {
            "schema": "frtb-ima-export/v1",
            "portfolio": {"assets": cols, "weights": [round(float(x), 6) for x in w]},
            "parameters": {"es_alpha": es_alpha, "var_window": window,
                           "ewma_lambda": lam, "base_horizon_sessions": BASE_T,
                           "liquidity_horizon": lh, "rho_imcc": RHO_IMCC,
                           "stress_window_sessions": stress_win},
            "liquidity_horizons": lh_info,
            "expected_shortfall": {"es_1d": round(es_1d, 6),
                                   "es_10d": round(es_10d, 6),
                                   "es_liquidity_adjusted": round(es_lh, 6),
                                   "es_stressed_liquidity_adjusted":
                                       (round(es_stressed, 6) if es_stressed else None)},
            "imcc": {"value": round(float(imcc), 6), "note": ratio_note},
            "backtesting": {"exceptions_99": exc99, "exceptions_975": exc975,
                            "n_test": int(te.sum()), **bt},
            "capital": {"basis": "homogénea: ambos lados a 10 sesiones y con componente estresado",
                        "current_basel25": round(capital_current, 6),
                        "current_var99_10d": round(avg_var99_10d, 6),
                        "current_svar99_10d": (round(svar99_10d, 6) if svar99_10d else None),
                        "current_multiplier": k_basel, "current_zone": zone_basel,
                        "frtb_ima_modellable": round(capital_frtb, 6),
                        "delta_pct": round(delta_pct, 2),
                        "coverage": "PARCIAL — solo componente modelizable",
                        "excludes": ["SES (NMRF)", "DRC", "residual risk add-on"],
                        "warning": ("El delta NO es el impacto final de capital: el lado "
                                    "FRTB omite SES, DRC y RRAO, que son precisamente los "
                                    "componentes que elevan el cargo IMA. La caída refleja "
                                    "sobre todo que Basilea 2.5 suma VaR y sVaR con k=3, "
                                    "duplicidad que FRTB sustituye por un único ES estresado "
                                    "con m_c=1.5.")},
            "nmrf": {"rfet_proxy": rfet, "candidates": nmrf,
                     "status": "PROXY — requiere conteo oficial de precios reales por factor"},
            "not_computed": {
                "pla_test": "requiere P&L hipotético y risk-theoretical por mesa",
                "ses": "requiere escenarios de estrés por factor no modelizable",
                "drc": "requiere exposiciones de crédito/emisor",
            },
        }
        out_dir = ctx.experiment_dir()
        exp_path = os.path.join(out_dir, "frtb_export.json")
        with open(exp_path, "w", encoding="utf-8") as fh:
            json.dump(export, fh, indent=2, ensure_ascii=False)
        ser_path = os.path.join(out_dir, "frtb_daily_series.csv")
        pd.DataFrame({"date": rdates[te], "portfolio_return": r_te,
                      "es_975": es[te], "var_975": var_es[te], "var_99": var99[te]}
                     ).to_csv(ser_path, index=False)

        metrics = {
            "source": source, "data_quality": {"sanitization": san, "calendar": cal},
            "assets": cols, "n_test": int(te.sum()),
            "test_period": [str(rdates[te][0].date()), str(rdates[te][-1].date())],
            "liquidity_horizon": lh_info,
            "channel_median_life_supporting_evidence": median_life,
            "expected_shortfall": export["expected_shortfall"],
            "stress_period": {k: v for k, v in sp.items() if k != "slice"},
            "imcc": export["imcc"], "backtesting": export["backtesting"],
            "kupiec_99": k99, "capital": export["capital"],
            "nmrf": {"candidates": nmrf, "rfet_proxy": rfet},
        }
        baseline = {"method": "Basilea 2.5: k(semáforo)·(VaR 99% 10d + sVaR 99% 10d)",
                    "capital": round(capital_current, 6), "multiplier": k_basel,
                    "zone": zone_basel}
        # La decisión es de PREPARACIÓN, no de superioridad: el módulo se acepta si
        # produce el paquete exportable y el backtesting queda en zona verde.
        # El paquete exportable puede estar completo y aun así el delta de capital
        # ser parcial: mientras falten SES/DRC/RRAO la comparación no es un cargo
        # final, de modo que la decisión se mantiene en `review` a propósito.
        export_ready = bool(es_stressed is not None and os.path.exists(exp_path))
        decision = "review"
        notes = (
            f"ES {es_alpha:.1%} 1d={es_1d:.5f} -> 10d={es_10d:.5f} -> LH={lh} sesiones "
            f"(MAR33.12, prescrito; vida mediana del canal {median_life} solo como "
            f"evidencia de apoyo) = {es_lh:.5f}. Periodo de estrés "
            f"{sp.get('start_date')}..{sp.get('end_date')} (retorno acumulado "
            f"{sp.get('cum_log_return')}) -> ES estresado {es_stressed:.5f}. "
            f"Backtesting FRTB: {exc99} excepciones al 99% ({bt['exceptions_99_per_250d']}/250d, "
            f"zona {bt['zone']}) -> m_c={bt['m_c']}. CAMBIO DE MODELO: capital actual "
            f"Basilea 2.5 k·(VaR10d+sVaR10d)={capital_current:.5f} (k={k_basel}) vs "
            f"FRTB m_c·IMCC={capital_frtb:.5f} "
            f"-> {delta_pct:+.1f}%. Excluye SES/DRC/RRAO y el PLA test, que requieren "
            f"datos por factor y P&L de mesa. NMRF candidatos (proxy): {nmrf or 'ninguno'}. "
            f"Paquete exportable {'LISTO' if export_ready else 'INCOMPLETO'} en frtb_export.json "
            f"(schema frtb-ima-export/v1). AVISO: el delta de capital es PARCIAL — el lado "
            f"FRTB omite SES/DRC/RRAO; la caída refleja sobre todo que Basilea 2.5 suma "
            f"VaR+sVaR con k=3 frente a un único ES estresado con m_c=1.5."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                artifacts=[exp_path, ser_path],
                                decision=decision, notes=notes)
