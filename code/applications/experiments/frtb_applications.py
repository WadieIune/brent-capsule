"""Aplicación 4 — Insumos para FRTB (proxies / scaffolding).

A partir de los episodios de canal y sus rupturas (`extract_episodes` de la 2ª
pata) deriva tres insumos que un motor FRTB podría consumir. Son PROXIES
metodológicos, no cálculos regulatorios finales:

  - `stress_period`  : ventanas de máxima pérdida acumulada (candidatas al
    periodo de estrés del Expected Shortfall del IMA).
  - `liquidity_horizon`: mapeo de la vida esperada del canal (mediana de
    duración de episodios) a los cubos LH de FRTB {10,20,40,60,120}.
  - `observability`  : proxy de modelabilidad (RFET) — nº de movimientos
    "reales" por trimestre y hueco máximo, como señal NMRF.

Decisión siempre `review`: requieren integración con el motor FRTB corporativo.
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

LH_BUCKETS = [10, 20, 40, 60, 120]


def _stress_windows(prices: np.ndarray, dates: pd.DatetimeIndex,
                    win: int, top: int) -> List[Dict[str, object]]:
    n = len(prices)
    rows: List[Dict[str, object]] = []
    for t in range(win, n):
        cum = prices[t] / prices[t - win] - 1.0
        rows.append({"end_pos": t, "cum_return": cum})
    df = pd.DataFrame(rows).sort_values("cum_return").head(top)
    out: List[Dict[str, object]] = []
    for _, r in df.iterrows():
        t = int(r["end_pos"])
        out.append({
            "start_date": str(dates[t - win].date()),
            "end_date": str(dates[t].date()),
            "cum_return": round(float(r["cum_return"]), 4),
            "window_days": win,
        })
    return out


def _liquidity_horizon(median_life: float) -> int:
    """Mapea la vida mediana del canal (sesiones) al cubo LH de FRTB."""
    for b in LH_BUCKETS:
        if median_life <= b:
            return b
    return LH_BUCKETS[-1]


def _observability(prices: np.ndarray, dates: pd.DatetimeIndex) -> Dict[str, object]:
    moves = np.abs(np.diff(prices)) > 1e-9
    df = pd.DataFrame({"date": dates[1:], "moved": moves})
    df["quarter"] = df["date"].dt.to_period("Q")
    per_q = df.groupby("quarter")["moved"].sum()
    # hueco máximo (nº de sesiones consecutivas sin movimiento real)
    max_gap, gap = 0, 0
    for m in moves:
        gap = 0 if m else gap + 1
        max_gap = max(max_gap, gap)
    min_obs_q = int(per_q.min()) if len(per_q) else 0
    # RFET (proxy simplificado): >=24 obs/año ~ >=6 por trimestre y sin hueco > ~21 sesiones
    modellable = bool(min_obs_q >= 6 and max_gap <= 21)
    return {
        "min_real_moves_per_quarter": min_obs_q,
        "max_gap_sessions": int(max_gap),
        "rfet_modellable_proxy": modellable,
        "note": "proxy simplificado de RFET; el criterio oficial usa observaciones "
                "verificables y huecos <= 1 mes por factor de riesgo",
    }


class FRTBApplicationsExperiment(Experiment):
    id = "frtb_applications"
    title = "FRTB — stress period, liquidity horizon y observabilidad (proxies)"

    def preflight(self, ctx: RunContext) -> List[str]:
        return []

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        s, source = common.load_prices(cfg.get("prices_path"),
                                       cfg.get("synthetic", False), ctx.seed)
        prices = s.to_numpy()
        dates = pd.DatetimeIndex(s.index)
        stress_win = int(cfg.get("stress_window", 60))
        top = int(cfg.get("stress_top", 3))

        episodes = common.cs.extract_episodes(prices, dates)
        n_ep = int(len(episodes))
        n_ev = int(episodes["event"].sum()) if n_ep else 0
        if n_ep and n_ev:
            median_life = float(episodes.loc[episodes["event"] == 1, "duration"].median())
        elif n_ep:
            median_life = float(episodes["duration"].median())
        else:
            median_life = float("nan")

        stress = _stress_windows(prices, dates, stress_win, top)
        lh = _liquidity_horizon(median_life) if median_life == median_life else None
        obs = _observability(prices, dates)

        metrics = {
            "source": source,
            "n_episodes": n_ep,
            "n_breakouts": n_ev,
            "median_channel_life_sessions": round(median_life, 1) if median_life == median_life else None,
            "stress_period_candidates": stress,
            "liquidity_horizon_bucket": lh,
            "observability_proxy": obs,
        }
        artifacts: List[str] = []
        if n_ep:
            path = os.path.join(ctx.experiment_dir(), "frtb_episodes.csv")
            episodes.to_csv(path, index=False)
            artifacts.append(path)

        baseline = {"method": "sin baseline (insumos regulatorios descriptivos)"}
        notes = (f"{n_ep} episodios ({n_ev} rupturas); vida mediana "
                 f"{metrics['median_channel_life_sessions']} → LH={lh}. "
                 "Proxies para alimentar el motor FRTB; no son cálculos oficiales.")
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                artifacts=artifacts, decision="review", notes=notes)