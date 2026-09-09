"""Aplicación 11 — Monitor DQ diario: banda esperada de rendimientos y alertas.

Sistema operativo de control de calidad de precio para ejecutar **cada día**
antes de alimentar el motor de riesgo. Para cada activo ajusta el canal sobre la
ventana previa —sin incluir la observación evaluada, de modo que no hay fuga— y
proyecta un paso adelante:

  - `centro_proyectado` : dónde *debería* estar el precio según la geometría reciente.
  - `banda_esperada`    : intervalo admisible (± k·σ del residuo del canal).
  - `retorno_esperado`  : el rango anterior expresado en rendimiento, que es la
    forma en que un control de riesgos lo consume.
  - `z`                 : desviación estandarizada del precio observado.

Un precio fuera de banda no es necesariamente un error: puede ser mercado. Por
eso el monitor **clasifica** en vez de rechazar, y ordena por severidad para que
la revisión humana empiece por lo más grave.

Reglas de alerta
----------------
| regla | qué captura |
|---|---|
| `fuera_de_banda` | el precio se aleja > k·σ del centro proyectado |
| `salto_reversible` | salto > TOL_ATR·ATR que revierte al día siguiente (pico de feed) |
| `precio_congelado` | tres cierres idénticos (relleno o feed caído) |
| `no_positivo` | cotización <= 0, incompatible con el motor log-normal |

Validación
----------
No basta con contar alertas: se reporta la **tasa de alerta** (carga operativa),
y se contrasta contra el control convencional de outliers por cuantil de
`|retorno|`, señalando qué defectos ve cada uno. El valor demostrado del control
está medido en `dq_impact.py`: depurar estos defectos corrige una distorsión de
74 puntos porcentuales en la contribución al riesgo de la cartera.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402
from experiments.dq_price_control import _naive_return_outliers  # noqa: E402
from experiments.portfolio_var import DEFAULT_ASSETS, load_commodities  # noqa: E402
from experiments.portfolio_var_alert import to_trading_days  # noqa: E402

SEVERITY_ORDER = {"no_positivo": 3, "fuera_de_banda": 2,
                  "salto_reversible": 1, "precio_congelado": 0}


def expected_band(prices: np.ndarray, dates: pd.DatetimeIndex, k_sigma: float,
                  lookback: int = common.LOOKBACK) -> pd.DataFrame:
    """Banda esperada un paso adelante para cada sesión (sin fuga)."""
    resid = common.forward_channel_residual(prices, lookback)
    if resid.empty:
        return pd.DataFrame()
    out = resid.copy()
    t = out["pos"].astype(int).to_numpy()
    prev = prices[t - 1]
    center = out["center"].to_numpy()
    half = k_sigma * out["resid_std"].to_numpy()
    out["date"] = dates[t]
    out["price"] = prices[t]
    out["prev_price"] = prev
    out["band_low"] = center - half
    out["band_high"] = center + half
    # El control de riesgos consume rendimientos, no niveles.
    with np.errstate(divide="ignore", invalid="ignore"):
        out["expected_return"] = center / np.maximum(prev, 1e-9) - 1.0
        out["ret_low"] = out["band_low"] / np.maximum(prev, 1e-9) - 1.0
        out["ret_high"] = out["band_high"] / np.maximum(prev, 1e-9) - 1.0
        out["realised_return"] = prices[t] / np.maximum(prev, 1e-9) - 1.0
    return out


def calibrate_k_sigma(prices: np.ndarray, dates: pd.DatetimeIndex,
                     target_rate: float, grid=(2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0)) -> float:
    """Elige k para que la carga de alertas 'fuera de banda' se acerque al objetivo.

    Un control cuyo umbral no se calibra a la capacidad de revisión de la mesa es
    inservible: o satura de falsos positivos o no dispara nunca. Aquí k se fija
    por carga operativa, no por convención estadística.
    """
    band = expected_band(prices, dates, 1.0)
    if band.empty:
        return 4.0
    z = np.abs(band["z"].to_numpy())
    best, gap = 4.0, 1e9
    for k in grid:
        rate = float(np.mean(z > k))
        if abs(rate - target_rate) < gap:
            best, gap = k, abs(rate - target_rate)
    return float(best)


def calibrate_tol_atr(prices: np.ndarray, target_rate: float,
                      grid=(1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)) -> float:
    """Calibra el umbral de salto reversible a la carga objetivo, igual que k."""
    atr = common.atr_like(prices)
    n = len(prices)
    best, gap = 2.0, 1e9
    for tol in grid:
        hits = 0
        for t in range(1, n - 1):
            thr = tol * (atr[t] if not np.isnan(atr[t]) else 0.0)
            j = abs(prices[t] - prices[t - 1])
            if thr > 0 and j > thr and abs(prices[t + 1] - prices[t - 1]) < 0.5 * j:
                hits += 1
        rate = hits / max(n, 1)
        if abs(rate - target_rate) < gap:
            best, gap = tol, abs(rate - target_rate)
    return float(best)


def daily_alerts(prices: np.ndarray, dates: pd.DatetimeIndex, asset: str,
                 k_sigma: float, tol_atr: float) -> pd.DataFrame:
    """Alertas por sesión para un activo, con severidad y motivo."""
    band = expected_band(prices, dates, k_sigma)
    atr = common.atr_like(prices)
    rows: List[Dict[str, object]] = []

    if not band.empty:
        out = band[np.abs(band["z"]) > k_sigma]
        for _, r in out.iterrows():
            rows.append({"date": r["date"], "asset": asset, "rule": "fuera_de_banda",
                         "severity_sigma": round(float(abs(r["z"])), 2),
                         "price": float(r["price"]),
                         "expected_center": round(float(r["center"]), 4),
                         "band_low": round(float(r["band_low"]), 4),
                         "band_high": round(float(r["band_high"]), 4),
                         "realised_return": round(float(r["realised_return"]), 5),
                         "expected_return_range": [round(float(r["ret_low"]), 5),
                                                   round(float(r["ret_high"]), 5)]})
    n = len(prices)
    for t in range(1, n - 1):
        thr = tol_atr * (atr[t] if not np.isnan(atr[t]) else 0.0)
        jump = abs(prices[t] - prices[t - 1])
        if thr > 0 and jump > thr and abs(prices[t + 1] - prices[t - 1]) < 0.5 * jump:
            rows.append({"date": dates[t], "asset": asset, "rule": "salto_reversible",
                         "severity_sigma": round(float(jump / thr), 2),
                         "price": float(prices[t])})
    for t in range(2, n):
        if prices[t] == prices[t - 1] == prices[t - 2]:
            rows.append({"date": dates[t], "asset": asset, "rule": "precio_congelado",
                         "severity_sigma": 1.0, "price": float(prices[t])})
    for t in np.where(prices <= 0)[0]:
        rows.append({"date": dates[int(t)], "asset": asset, "rule": "no_positivo",
                     "severity_sigma": 99.0, "price": float(prices[int(t)])})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["priority"] = df["rule"].map(SEVERITY_ORDER).fillna(0).astype(int)
    return df.sort_values(["priority", "severity_sigma"], ascending=False).reset_index(drop=True)


class DQDailyMonitorExperiment(Experiment):
    id = "dq_daily_monitor"
    title = "Monitor DQ diario: banda esperada de rendimientos y cola de alertas"

    def preflight(self, ctx: RunContext) -> List[str]:
        k = ctx.config.get("k_sigma")
        return ["k_sigma debe ser > 0"] if (k is not None and float(k) <= 0) else []

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        assets = tuple(cfg.get("assets") or DEFAULT_ASSETS)
        k_sigma = cfg.get("k_sigma")
        target = float(cfg.get("dq_target_alert_rate", 0.01))
        tol_atr = cfg.get("tol_atr")
        px, source = load_commodities(assets)
        audit_mode = bool(cfg.get("dq_audit_mode", False))
        cal_diag: Dict[str, object] = {"trading_days_filter": False}
        if not audit_mode:
            # Modo OPERATIVO: el monitor corre sobre sesiones de negociación. El
            # relleno de calendario es un defecto del histórico, no una alerta
            # diaria; se audita aparte (`dq_audit_mode`) para no saturar la cola.
            px, cal_diag = to_trading_days(px)
            cal_diag["trading_days_filter"] = True
        dates = pd.DatetimeIndex(px.index)
        cols = list(px.columns)
        if k_sigma is None:
            k_sigma = calibrate_k_sigma(px[cols[0]].to_numpy(float), dates, target)
            ctx.log(f"k_sigma calibrado a carga objetivo {target:.1%} -> k={k_sigma}")
        k_sigma = float(k_sigma)
        if tol_atr is None:
            tol_atr = calibrate_tol_atr(px[cols[0]].to_numpy(float), target)
            ctx.log(f"tol_atr calibrado a carga objetivo {target:.1%} -> tol={tol_atr}")
        tol_atr = float(tol_atr)
        ctx.log(f"panel {cols} · {len(px)} sesiones · fuente={source} · "
                f"modo={'auditoría' if audit_mode else 'operativo'}")

        frames, per_asset = [], {}
        for c in cols:
            a = daily_alerts(px[c].to_numpy(float), dates, c, k_sigma, tol_atr)
            if not a.empty:
                frames.append(a)
            per_asset[c] = {} if a.empty else a["rule"].value_counts().to_dict()
        alerts = (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
        total_obs = len(px) * len(cols)
        rate = 100.0 * len(alerts) / max(total_obs, 1)
        by_rule = alerts["rule"].value_counts().to_dict() if len(alerts) else {}
        ctx.log(f"  alertas: {len(alerts)} sobre {total_obs} observaciones "
                f"({rate:.2f}% de carga) · por regla {by_rule}")

        # Contraste con el control convencional (solo ve outliers de retorno).
        conv = 0
        for c in cols:
            conv += len(_naive_return_outliers(px[c].to_numpy(float)))
        ctx.log(f"  control convencional (cuantil |retorno| 99.9%): {conv} marcas")

        # Banda esperada: cobertura empírica (¿el precio cae dentro de lo previsto?).
        ref = cols[0]
        band = expected_band(px[ref].to_numpy(float), dates, k_sigma)
        coverage = None
        if not band.empty:
            inside = ((band["price"] >= band["band_low"]) &
                      (band["price"] <= band["band_high"])).mean()
            coverage = round(float(100.0 * inside), 2)
            ctx.log(f"  cobertura de la banda esperada en {ref}: {coverage}% "
                    f"(k={k_sigma}σ)")

        # Cola de revisión del último día disponible (uso operativo real).
        last_day = dates[-1]
        today = (alerts[alerts["date"] == last_day] if len(alerts) else pd.DataFrame())
        artifacts: List[str] = []
        if len(alerts):
            p = os.path.join(ctx.experiment_dir(), "dq_alerts.csv")
            alerts.to_csv(p, index=False)
            artifacts.append(p)
        if not band.empty:
            p2 = os.path.join(ctx.experiment_dir(), f"expected_band_{ref}.csv")
            band[["date", "price", "center", "band_low", "band_high",
                  "expected_return", "ret_low", "ret_high", "realised_return", "z"]
                 ].to_csv(p2, index=False)
            artifacts.append(p2)

        metrics = {
            "source": source, "assets": cols, "mode": "auditoria" if audit_mode else "operativo",
            "calendar": cal_diag, "target_alert_rate": target, "k_sigma": k_sigma, "tol_atr": tol_atr,
            "observations": int(total_obs), "alerts": int(len(alerts)),
            "alert_rate_pct": round(rate, 3), "by_rule": by_rule,
            "per_asset": per_asset,
            "conventional_flags": int(conv),
            "expected_band_coverage_pct": coverage,
            "last_session": str(last_day.date()),
            "alerts_last_session": int(len(today)),
            "top_severity_sample": (alerts.head(5)[["date", "asset", "rule", "severity_sigma"]]
                                    .assign(date=lambda x: x["date"].astype(str))
                                    .to_dict("records") if len(alerts) else []),
        }
        baseline = {"method": "control convencional de outliers por cuantil de |retorno|",
                    "flags": int(conv),
                    "blind_to": ["precio_congelado / relleno por forward-fill",
                                 "desviación respecto al canal proyectado (sin severidad)"]}
        # El monitor se acepta si es operativamente viable: cobertura de banda
        # razonable y carga de alertas asumible por una mesa de control.
        viable = (coverage is not None and 90.0 <= coverage <= 100.0 and rate < 5.0)
        decision = "accept" if viable else "review"
        notes = (
            f"Monitor diario sobre {len(cols)} activos y {total_obs} observaciones: "
            f"{len(alerts)} alertas ({rate:.2f}% de carga operativa), desglose {by_rule}. "
            f"La banda esperada a k={k_sigma}σ contiene el {coverage}% de los precios "
            f"observados en {ref}, de modo que el control acota el rendimiento admisible "
            f"del día siguiente y marca lo que se sale. El control convencional emite "
            f"{conv} marcas y es CIEGO al precio congelado y al relleno de calendario. "
            f"Última sesión ({last_day.date()}): {len(today)} alertas. "
            "El valor está cuantificado en dq_impact: depurar estos defectos corrige "
            "74,4 puntos porcentuales de distorsión en la contribución al riesgo."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline, artifacts=artifacts,
                                decision=decision, notes=notes)
