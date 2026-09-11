"""Monitor diario para Risk Director sobre Brent y variables exogenas.

Objetivo operativo
------------------
El paper necesita una salida util cada dia mientras el mercado este vivo. Este
experimento no valida una CNN ni identifica causalidad geopolitica: construye un
parte diario reproducible con el estado observable del Brent, la volatilidad
realizada y las variables externas disponibles en el panel extendido.

La salida sirve para decidir si hay que revisar exposicion, coberturas y
escenarios antes de esperar a que madure una evaluacion academica completa.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from harness import Experiment, ExperimentResult, RunContext  # noqa: E402


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_panel_path() -> Path:
    return _repo_root() / "data" / "panel_extendido_2026-09-09.csv"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _last_two(s: pd.Series) -> Tuple[pd.Timestamp, float, pd.Timestamp, float]:
    clean = s.dropna()
    if len(clean) < 2:
        raise ValueError(f"serie {s.name!r} necesita al menos dos observaciones")
    return clean.index[-2], float(clean.iloc[-2]), clean.index[-1], float(clean.iloc[-1])


def _pct_change_since(s: pd.Series, periods: int) -> float:
    clean = s.dropna()
    if len(clean) <= periods:
        return float("nan")
    return float(clean.iloc[-1] / clean.iloc[-1 - periods] - 1.0)


def _percentile(x: float, sample: pd.Series) -> float:
    vals = sample.dropna().to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0 or not np.isfinite(x):
        return float("nan")
    return float(np.mean(vals <= x))


def _classify(vol_pctile: float, vol_julsep: float, move20: float, wti_spread: float) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    if vol_pctile >= 0.98:
        reasons.append("volatilidad realizada en percentil >= 98")
    elif vol_pctile >= 0.90:
        reasons.append("volatilidad realizada en percentil >= 90")
    if np.isfinite(vol_julsep) and vol_julsep >= 0.75:
        reasons.append("volatilidad julio-septiembre en zona de tension")
    if np.isfinite(move20) and abs(move20) >= 0.20:
        reasons.append("movimiento Brent 20 sesiones >= 20%")
    if np.isfinite(wti_spread) and wti_spread <= -10.0:
        reasons.append("Brent cotiza con prima amplia frente a WTI")

    if vol_pctile >= 0.98 or (np.isfinite(move20) and abs(move20) >= 0.30):
        return "crisis", reasons
    if vol_pctile >= 0.90 or (np.isfinite(move20) and abs(move20) >= 0.20):
        return "alerta", reasons
    if vol_pctile >= 0.75 or (np.isfinite(move20) and abs(move20) >= 0.10):
        return "vigilancia", reasons
    return "normal", reasons


def build_daily_report(panel_path: Path) -> Dict[str, object]:
    raw_hash = _sha256(panel_path)
    df = pd.read_csv(panel_path, parse_dates=["date"]).sort_values("date")
    if "BRENT" not in df.columns:
        raise ValueError("el panel debe contener columna BRENT")
    panel = df.set_index("date")
    brent = panel["BRENT"].astype(float).dropna()
    if len(brent) < 260:
        raise ValueError("historia BRENT insuficiente para monitor diario")

    prev_date, prev_price, latest_date, latest_price = _last_two(brent)
    ret = np.log(brent).diff()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vol60 = ret.rolling(60).std() * np.sqrt(252)
    latest_vol20 = float(vol20.dropna().iloc[-1])
    latest_vol60 = float(vol60.dropna().iloc[-1])
    vol_pctile = _percentile(latest_vol20, vol20)
    vol_julsep = float(vol20.loc["2026-07-01":"2026-09-30"].dropna().max())
    vol_julsep_date = str(vol20.loc["2026-07-01":"2026-09-30"].idxmax().date())

    move1 = float(latest_price / prev_price - 1.0)
    move5 = _pct_change_since(brent, 5)
    move20 = _pct_change_since(brent, 20)
    move_from_0629 = float(latest_price / brent.loc[pd.Timestamp("2026-06-29")] - 1.0) if pd.Timestamp("2026-06-29") in brent.index else float("nan")

    exog_cols = [
        "WTI", "SPREAD_WTI_BRENT", "RATIO_WTI_BRENT", "VIX", "DTWEXBGS",
        "DGS2", "DGS10", "DGS30", "SPREAD_US10Y_US2Y", "DFF", "SOFR",
        "NATGAS", "GOLD", "SILVER", "COPPER", "SP500", "DAX",
        "EUROSTOXX50", "EURUSD", "BRENT_EURUSD_RATIO",
    ]
    exog: Dict[str, Dict[str, object]] = {}
    for col in exog_cols:
        if col not in panel.columns:
            continue
        s = panel[col].astype(float).dropna()
        if s.empty:
            continue
        change_5 = float(s.iloc[-1] / s.iloc[-6] - 1.0) if len(s) > 5 and s.iloc[-6] != 0 else float("nan")
        exog[col] = {
            "latest_date": str(s.index[-1].date()),
            "latest": float(s.iloc[-1]),
            "change_5_obs": change_5,
        }

    spread = float(exog.get("SPREAD_WTI_BRENT", {}).get("latest", float("nan")))
    state, reasons = _classify(vol_pctile, vol_julsep, move20, spread)

    recommended_actions = {
        "normal": [
            "Mantener monitor diario y actualizar escenarios si cambia la exposicion.",
        ],
        "vigilancia": [
            "Revisar sensibilidad de caja/margen a +/-10 y +/-20 USD por barril.",
            "Comprobar limites internos antes de nuevas posiciones largas/cortas Brent.",
        ],
        "alerta": [
            "Convocar revision Risk Director de exposicion y coberturas.",
            "Ejecutar escenarios de stress de coste energetico y liquidez a 10 sesiones.",
            "Congelar cualquier titular del paper que dependa del corte 2026-06-29.",
        ],
        "crisis": [
            "Activar comite de riesgo: limites, coberturas, colateral y escenarios intradia.",
            "Separar decision operativa de validacion academica; publicar solo cifras auditadas.",
            "Reevaluar VaR/capital con el panel extendido antes de decisiones de tamano.",
        ],
    }[state]

    return {
        "as_of": str(latest_date.date()),
        "panel_path": str(panel_path),
        "panel_sha256": raw_hash,
        "panel_rows": int(len(df)),
        "panel_columns": int(len(df.columns)),
        "panel_date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "brent": {
            "latest": latest_price,
            "previous_date": str(prev_date.date()),
            "previous": prev_price,
            "return_1_obs": move1,
            "return_5_obs": move5,
            "return_20_obs": move20,
            "return_since_2026_06_29": move_from_0629,
            "vol20_ann": latest_vol20,
            "vol60_ann": latest_vol60,
            "vol20_percentile_panel": vol_pctile,
            "max_vol20_jul_sep_2026": vol_julsep,
            "max_vol20_jul_sep_2026_date": vol_julsep_date,
        },
        "state": state,
        "state_reasons": reasons,
        "recommended_actions": recommended_actions,
        "exogenous_latest": exog,
        "limits": [
            "Monitor descriptivo y operativo; no prueba causal ni modelo CNN validado.",
            "Disponibilidad as-of/release/vintage pendiente de auditoria por variable.",
            "La atribucion a Iran/Ormuz requiere calendario externo documentado.",
        ],
    }


class RiskDirectorDailyExperiment(Experiment):
    id = "risk_director_daily"
    title = "Risk Director diario: Brent, volatilidad y exogenas extendidas"

    def preflight(self, ctx: RunContext) -> List[str]:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        issues: List[str] = []
        if not panel_path.exists():
            issues.append(f"no existe panel_path={panel_path}")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        panel_path = Path(ctx.config.get("panel_path") or _default_panel_path())
        report = build_daily_report(panel_path)
        out_dir = Path(ctx.experiment_dir())
        json_path = out_dir / "risk_director_daily.json"
        csv_path = out_dir / "risk_director_daily.csv"
        with json_path.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)

        row = {
            "as_of": report["as_of"],
            "state": report["state"],
            "brent_latest": report["brent"]["latest"],
            "brent_return_1_obs": report["brent"]["return_1_obs"],
            "brent_return_5_obs": report["brent"]["return_5_obs"],
            "brent_return_20_obs": report["brent"]["return_20_obs"],
            "brent_return_since_2026_06_29": report["brent"]["return_since_2026_06_29"],
            "vol20_ann": report["brent"]["vol20_ann"],
            "vol20_percentile_panel": report["brent"]["vol20_percentile_panel"],
            "max_vol20_jul_sep_2026": report["brent"]["max_vol20_jul_sep_2026"],
            "panel_sha256": report["panel_sha256"],
        }
        pd.DataFrame([row]).to_csv(csv_path, index=False)

        metrics = {
            "as_of": report["as_of"],
            "state": report["state"],
            "brent_latest": report["brent"]["latest"],
            "brent_return_20_obs": report["brent"]["return_20_obs"],
            "brent_return_since_2026_06_29": report["brent"]["return_since_2026_06_29"],
            "vol20_ann": report["brent"]["vol20_ann"],
            "vol20_percentile_panel": report["brent"]["vol20_percentile_panel"],
            "max_vol20_jul_sep_2026": report["brent"]["max_vol20_jul_sep_2026"],
            "panel_sha256": report["panel_sha256"],
        }
        decision = "review" if report["state"] in {"alerta", "crisis"} else "accept"
        notes = f"estado={report['state']} · Brent {report['as_of']}={report['brent']['latest']:.2f}"
        return ExperimentResult(
            metrics=metrics,
            artifacts=[str(json_path), str(csv_path)],
            decision=decision,
            notes=notes,
        )
