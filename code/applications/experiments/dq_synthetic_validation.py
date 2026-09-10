"""Track A (WP2-A) — Validación del control geométrico con verdad conocida.

Los experimentos `dq_price_control`, `dq_impact` y `dq_daily_monitor` miden el
control de calidad sobre los defectos **reales** del panel (n = 2). Eso basta para
ilustrar, pero no para sostener una afirmación de rendimiento: sin *ground truth*
no hay precisión ni recall, y sin ellas no hay comparación honesta con un
baseline.

Este experimento inyecta defectos **sintéticos con posición conocida** sobre una
serie limpia y mide la capacidad de detección del control geométrico frente a
baselines fuertes, familia por familia.

Diseño congelado en `docs/PREREGISTRO.md` (Track A). Resumen:

  - **Serie base limpia**: cierres observados del Brent (FRED) tras eliminar los
    rellenos por *forward-fill*, de modo que la serie no contiene rachas ni
    retornos nulos que contaminen la verdad de referencia.
  - **Familias de defecto**: stale/relleno, salto reversible, outlier de cola,
    precio no positivo y desfase de calendario.
  - **Tasas de corrupción**: 0.5 %, 1 % y 2 %. **10 semillas** por combinación.
  - **Métrica primaria**: AUC-PR (precisión-recall) por familia. Se usa PR y no
    ROC porque la clase positiva es rara y el ROC resulta optimista con
    desbalance severo.
  - **Baselines fuertes**: Hampel/MAD móvil, vallas de Tukey, *isolation forest*
    y detector de rachas constantes. El mejor por familia es el rival a batir.
  - **Control de nivel**: detector aleatorio que marca la misma fracción de
    observaciones. Descarta que el mérito venga del volumen de alertas.
  - **Regla de parada**: una única configuración del control geométrico, con los
    parámetros ya publicados. **No se optimizan hiperparámetros.**

El veredicto se emite contra los umbrales **pre-registrados**, no contra la
impresión que dejen los números.
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

# --- Parámetros congelados por el pre-registro -------------------------------
RATES = (0.005, 0.01, 0.02)
N_SEEDS = 10
K_SIGMA = 5.0          # banda esperada del control geométrico (ya publicado)
TOL_ATR = 1.0          # tolerancia de salto ATR (ya publicado)
OPERATING_QUANTILE = 0.99   # umbral operativo común a todos los detectores
BOOTSTRAP = 3000

FAMILIES = ("stale_fill", "salto_reversible", "outlier_de_cola",
            "precio_no_positivo", "desfase_calendario")

# Familias en las que el argumento estructural predice ceguera del control
# convencional de cola (un retorno exactamente cero nunca es atípico de cola).
BLIND_FAMILIES = ("stale_fill", "precio_no_positivo")


# --------------------------------------------------------------------------
# Serie base limpia
# --------------------------------------------------------------------------
def clean_base_series(path: Optional[str] = None, n_tail: int = 4000
                      ) -> Tuple[np.ndarray, pd.DatetimeIndex]:
    """Cierres observados sin rellenos: base sin defectos para inyectar sobre ella.

    `brent_fred_daily.csv` está reindexado a días hábiles con *forward-fill*, de
    modo que los festivos aparecen como cierres repetidos. Esos repetidos son
    exactamente el defecto que queremos inyectar de forma controlada, así que se
    eliminan primero: en caso contrario la verdad de referencia quedaría
    contaminada (habría "stale" no etiquetado como tal).
    """
    if path is None:
        d = _APP
        for _ in range(5):
            cand = os.path.join(d, "data", "brent_fred_daily.csv")
            if os.path.exists(cand):
                path = cand
                break
            d = os.path.dirname(d)
    s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["BRENT"].astype(float)
    s = s[s.diff() != 0]          # elimina los rellenos por ffill
    s = s.tail(n_tail)
    return s.to_numpy(dtype=float), pd.DatetimeIndex(s.index)


# --------------------------------------------------------------------------
# Inyección de defectos (verdad de referencia conocida)
# --------------------------------------------------------------------------
def inject(prices: np.ndarray, family: str, rate: float, seed: int
           ) -> Tuple[np.ndarray, np.ndarray]:
    """Devuelve (serie corrupta, máscara booleana de posiciones corruptas)."""
    rng = np.random.default_rng(seed)
    p = prices.copy()
    n = len(p)
    truth = np.zeros(n, dtype=bool)
    atr = common.atr_like(prices)
    lo, hi = 40, n - 40           # margen para no tocar los bordes
    n_events = max(1, int(round(rate * n)))

    if family == "stale_fill":
        # Rachas de 2-5 sesiones repitiendo el último cierre (feed congelado/ffill).
        starts = rng.choice(np.arange(lo, hi), size=max(1, n_events // 3), replace=False)
        for t0 in starts:
            k = int(rng.integers(2, 6))
            for t in range(t0, min(t0 + k, n)):
                p[t] = p[t0 - 1]
                truth[t] = True

    elif family == "salto_reversible":
        # Pico puntual que revierte al día siguiente (error de captura tipo fat finger).
        idx = rng.choice(np.arange(lo, hi), size=n_events, replace=False)
        for t in idx:
            mag = float(rng.uniform(4.0, 8.0)) * max(atr[t], 1e-8)
            p[t] = p[t] + mag * rng.choice([-1.0, 1.0])
            truth[t] = True

    elif family == "outlier_de_cola":
        # Salto persistente (desplazamiento de nivel que NO revierte).
        idx = rng.choice(np.arange(lo, hi), size=n_events, replace=False)
        for t in idx:
            mag = float(rng.uniform(4.0, 8.0)) * max(atr[t], 1e-8)
            shift = mag * rng.choice([-1.0, 1.0])
            p[t:] = p[t:] + shift      # el nivel se desplaza a partir de t
            truth[t] = True

    elif family == "precio_no_positivo":
        # Precio cero o negativo (como el WTI el 2020-04-20).
        idx = rng.choice(np.arange(lo, hi), size=n_events, replace=False)
        for t in idx:
            p[t] = float(rng.choice([0.0, -abs(p[t]) * rng.uniform(0.1, 0.5)]))
            truth[t] = True

    elif family == "desfase_calendario":
        # Bloque desplazado una posición: el precio de t aparece en t+1.
        starts = rng.choice(np.arange(lo, hi - 10), size=max(1, n_events // 4), replace=False)
        for t0 in starts:
            k = int(rng.integers(3, 8))
            seg = p[t0:t0 + k].copy()
            p[t0 + 1:t0 + k + 1] = seg
            truth[t0:t0 + k + 1] = True
    else:
        raise ValueError(f"familia desconocida: {family}")

    return p, truth


# --------------------------------------------------------------------------
# Detectores: cada uno devuelve un score continuo por posición
# --------------------------------------------------------------------------
def _rank01(x: np.ndarray) -> np.ndarray:
    """Normaliza a rango [0,1] por rangos, para poder combinar escalas distintas."""
    x = np.nan_to_num(np.asarray(x, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    if x.size == 0 or np.allclose(x, x[0]):
        return np.zeros_like(x)
    order = np.argsort(np.argsort(x))
    return order / max(1.0, len(x) - 1.0)


def score_geometric(prices: np.ndarray) -> np.ndarray:
    """Control geométrico: banda del canal + salto ATR reversible + racha constante.

    Combina las tres reglas por rango normalizado y toma el máximo, de modo que
    las escalas heterogéneas (|z|, jump/ATR, indicador de racha) sean comparables.
    """
    n = len(prices)
    safe = np.where(prices > 0, prices, np.nan)

    # 1) Residuo proyectado sobre el canal reciente.
    s_band = np.zeros(n)
    try:
        resid = common.forward_channel_residual(
            np.nan_to_num(safe, nan=np.nanmedian(safe)), common.LOOKBACK)
        for _, r in resid.iterrows():
            s_band[int(r["pos"])] = abs(float(r["z"]))
    except Exception:
        pass

    # 2) Salto ATR que revierte al día siguiente.
    atr = common.atr_like(np.nan_to_num(safe, nan=np.nanmedian(safe)))
    s_jump = np.zeros(n)
    for t in range(1, n - 1):
        jump = abs(prices[t] - prices[t - 1])
        thr = TOL_ATR * (atr[t] if not np.isnan(atr[t]) else 0.0)
        if thr > 0 and jump > thr:
            revert = abs(prices[t + 1] - prices[t - 1])
            if revert < 0.5 * jump:
                s_jump[t] = jump / thr

    # 3) Racha de cierres idénticos.
    s_stale = np.zeros(n)
    for t in range(2, n):
        if prices[t] == prices[t - 1] == prices[t - 2]:
            s_stale[t] = 1.0
            s_stale[t - 1] = max(s_stale[t - 1], 1.0)

    # 4) Precio no positivo: imposible por definición en una serie de precios.
    s_nonpos = (prices <= 0).astype(float)

    return np.maximum.reduce([_rank01(s_band), _rank01(s_jump),
                              s_stale, s_nonpos])


def _returns(prices: np.ndarray) -> np.ndarray:
    safe = np.where(prices > 0, prices, np.nan)
    r = np.diff(np.log(safe), prepend=np.log(safe[0]) if safe[0] > 0 else 0.0)
    # Un precio no positivo produce NaN: se marca como retorno extremo, que es
    # como lo vería un control de cola aplicado sobre retornos.
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


def score_mad_hampel(prices: np.ndarray, win: int = 30) -> np.ndarray:
    """Filtro de Hampel: z robusto sobre la mediana móvil (MAD)."""
    r = pd.Series(_returns(prices))
    med = r.rolling(win, min_periods=5, center=True).median()
    mad = (r - med).abs().rolling(win, min_periods=5, center=True).median()
    z = (r - med).abs() / (1.4826 * mad.replace(0.0, np.nan))
    return _rank01(z.fillna(0.0).to_numpy())


def score_tukey(prices: np.ndarray) -> np.ndarray:
    """Vallas de Tukey sobre los retornos: distancia más allá de la valla."""
    r = _returns(prices)
    q1, q3 = np.quantile(r, 0.25), np.quantile(r, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    d = np.maximum(np.maximum(lo - r, r - hi), 0.0)
    return _rank01(d)


def score_iforest(prices: np.ndarray, seed: int = 42) -> np.ndarray:
    """Isolation forest sobre retorno, |retorno| y variación local."""
    from sklearn.ensemble import IsolationForest

    r = _returns(prices)
    feats = np.column_stack([
        r, np.abs(r),
        pd.Series(r).rolling(5, min_periods=1).std().fillna(0.0).to_numpy(),
    ])
    iso = IsolationForest(n_estimators=200, contamination="auto",
                          random_state=seed).fit(feats)
    return _rank01(-iso.score_samples(feats))


def score_run_detector(prices: np.ndarray) -> np.ndarray:
    """Detector especializado de rachas constantes (baseline fuerte para stale)."""
    n = len(prices)
    s = np.zeros(n)
    run = 1
    for t in range(1, n):
        run = run + 1 if prices[t] == prices[t - 1] else 1
        if run >= 2:
            for k in range(t - run + 1, t + 1):
                s[k] = max(s[k], float(run))
    return _rank01(s)


def score_random(prices: np.ndarray, seed: int = 0) -> np.ndarray:
    """Control de nivel: marca al azar, sin mirar el dato."""
    return np.random.default_rng(seed).random(len(prices))


BASELINES = {
    "hampel_mad": score_mad_hampel,
    "tukey": score_tukey,
    "iforest": score_iforest,
    "run_detector": score_run_detector,
}


# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------
def auc_pr(truth: np.ndarray, score: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score

    if truth.sum() == 0 or truth.all():
        return float("nan")
    return float(average_precision_score(truth.astype(int), score))


def recall_precision_at(truth: np.ndarray, score: np.ndarray,
                        q: float = OPERATING_QUANTILE, seed: int = 0
                        ) -> Tuple[float, float]:
    """Recall y precisión con **presupuesto fijo de alertas**: el top-k del score.

    Se usa presupuesto fijo (k = (1-q)·n) y no un umbral por cuantil porque un
    detector con score constante —el caso de un detector de rachas frente a una
    serie sin rachas— no supera ningún umbral y, con la regla ingenua
    `score >= max`, acabaría marcando *todas* las observaciones y exhibiendo un
    recall de 1.0 espurio. Con presupuesto fijo y desempate aleatorio, ese
    detector obtiene el recall que le corresponde: el de marcar al azar.
    """
    n = len(score)
    k = max(1, int(round((1.0 - q) * n)))
    rng = np.random.default_rng(seed)
    order = np.lexsort((rng.random(n), -np.asarray(score, dtype=float)))
    pred = np.zeros(n, dtype=bool)
    pred[order[:k]] = True
    tp = int(np.sum(pred & truth))
    return (tp / max(1, int(truth.sum())), tp / k)


def bootstrap_delta(truth: np.ndarray, s_a: np.ndarray, s_b: np.ndarray,
                    b: int = BOOTSTRAP, seed: int = 42) -> Dict[str, float]:
    """IC 95 % de ΔAUC-PR = A − B por remuestreo estratificado de posiciones."""
    rng = np.random.default_rng(seed)
    n = len(truth)
    pos, neg = np.where(truth)[0], np.where(~truth)[0]
    if len(pos) < 5:
        return {"delta": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    deltas = []
    for _ in range(b):
        idx = np.concatenate([rng.choice(pos, len(pos), replace=True),
                              rng.choice(neg, len(neg), replace=True)])
        t = truth[idx]
        if t.sum() == 0 or t.all():
            continue
        deltas.append(auc_pr(t, s_a[idx]) - auc_pr(t, s_b[idx]))
    if not deltas:
        return {"delta": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    d = np.asarray(deltas)
    return {"delta": float(np.mean(d)),
            "ci_low": float(np.percentile(d, 2.5)),
            "ci_high": float(np.percentile(d, 97.5))}


# --------------------------------------------------------------------------
# Experimento
# --------------------------------------------------------------------------
class DQSyntheticValidationExperiment(Experiment):
    id = "dq_synthetic_validation"
    title = "Track A — control geométrico validado con inyección sintética (verdad conocida)"

    def preflight(self, ctx: RunContext) -> List[str]:
        issues: List[str] = []
        if ctx.config.get("n_seeds", N_SEEDS) < 5:
            issues.append("menos semillas de las pre-registradas: resultado no comparable")
        return issues

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        rates = tuple(cfg.get("rates") or RATES)
        n_seeds = int(cfg.get("n_seeds", N_SEEDS))
        prices, dates = clean_base_series(n_tail=int(cfg.get("n_tail", 4000)))
        ctx.log(f"serie base limpia: {len(prices)} cierres "
                f"({dates.min().date()} → {dates.max().date()})")

        rows: List[Dict[str, object]] = []
        for family in FAMILIES:
            for rate in rates:
                for seed in range(n_seeds):
                    p, truth = inject(prices, family, rate, seed=1000 + seed)
                    if truth.sum() < 5:
                        continue
                    scores = {"geometrico": score_geometric(p)}
                    for name, fn in BASELINES.items():
                        try:
                            scores[name] = (fn(p, seed) if name == "iforest" else fn(p))
                        except Exception as exc:  # pragma: no cover
                            ctx.log(f"  baseline {name} falló: {exc}")
                            scores[name] = np.zeros(len(p))
                    scores["aleatorio"] = score_random(p, seed)

                    for name, sc in scores.items():
                        rec, prec = recall_precision_at(truth, sc, seed=seed)
                        rows.append({
                            "familia": family, "tasa": rate, "semilla": seed,
                            "detector": name, "auc_pr": auc_pr(truth, sc),
                            "recall": rec, "precision": prec,
                            "n_defectos": int(truth.sum()),
                        })
            ctx.log(f"  {family}: {n_seeds * len(rates)} corridas completadas")

        df = pd.DataFrame(rows)
        art = os.path.join(ctx.experiment_dir(), "synthetic_runs.csv")
        df.to_csv(art, index=False)

        # --- Agregación por familia y detector -------------------------------
        agg = (df.groupby(["familia", "detector"])
                 .agg(auc_pr=("auc_pr", "mean"), recall=("recall", "mean"),
                      precision=("precision", "mean"))
                 .reset_index())
        por_familia: Dict[str, object] = {}
        for family in FAMILIES:
            sub = agg[agg["familia"] == family].set_index("detector")
            if sub.empty:
                continue
            base_only = sub.drop(index=["geometrico", "aleatorio"], errors="ignore")
            best_base = base_only["auc_pr"].idxmax() if not base_only.empty else None
            por_familia[family] = {
                "geometrico": {k: round(float(sub.loc["geometrico", k]), 4)
                               for k in ("auc_pr", "recall", "precision")},
                "mejor_baseline": best_base,
                "baselines": {d: {k: round(float(sub.loc[d, k]), 4)
                                  for k in ("auc_pr", "recall", "precision")}
                              for d in base_only.index},
                "control_aleatorio": {k: round(float(sub.loc["aleatorio", k]), 4)
                                      for k in ("auc_pr", "recall", "precision")}
                if "aleatorio" in sub.index else None,
            }

        # --- Contraste bootstrap en una corrida representativa ---------------
        deltas: Dict[str, object] = {}
        for family in FAMILIES:
            info = por_familia.get(family)
            if not info or not info.get("mejor_baseline"):
                continue
            p, truth = inject(prices, family, rates[len(rates) // 2], seed=1000)
            s_geo = score_geometric(p)
            bb = info["mejor_baseline"]
            s_base = (BASELINES[bb](p, 0) if bb == "iforest" else BASELINES[bb](p))
            deltas[family] = {k: round(v, 4) for k, v in
                              bootstrap_delta(truth, s_geo, s_base).items()}
            deltas[family]["vs"] = bb

        # --- Veredicto contra los umbrales PRE-REGISTRADOS -------------------
        crit1: Dict[str, object] = {}
        for family in BLIND_FAMILIES:
            info = por_familia.get(family)
            if not info:
                continue
            base_recalls = {d: v["recall"] for d, v in info["baselines"].items()}
            worst_case = max(base_recalls.values()) if base_recalls else 0.0
            crit1[family] = {
                "recall_geometrico": info["geometrico"]["recall"],
                "recall_mejor_baseline": round(float(worst_case), 4),
                "baseline_recall_por_detector": base_recalls,
                "cumple": bool(info["geometrico"]["recall"] >= 0.70 and worst_case < 0.10),
            }
        crit1_ok = bool(crit1) and all(v["cumple"] for v in crit1.values())

        common_fams = [f for f in FAMILIES if f not in BLIND_FAMILIES]
        crit2: Dict[str, object] = {}
        for family in common_fams:
            d = deltas.get(family)
            if not d or not np.isfinite(d.get("ci_low", np.nan)):
                continue
            crit2[family] = {"delta_auc_pr": d["delta"], "ci_low": d["ci_low"],
                             "ci_high": d["ci_high"], "vs": d["vs"],
                             "cumple": bool(d["ci_low"] >= -0.05)}
        crit2_ok = bool(crit2) and all(v["cumple"] for v in crit2.values())

        if crit1_ok and crit2_ok:
            decision = "accept"
        elif crit1_ok:
            decision = "review"
        else:
            decision = "reject"

        metrics = {
            "diseno": {"rates": list(rates), "n_seeds": n_seeds,
                       "n_obs_serie": int(len(prices)),
                       "familias": list(FAMILIES),
                       "umbral_operativo_q": OPERATING_QUANTILE,
                       "config_geometrica": {"lookback": common.LOOKBACK,
                                             "k_sigma": K_SIGMA, "tol_atr": TOL_ATR},
                       "hiperparametros_optimizados": False},
            "por_familia": por_familia,
            "bootstrap_delta_auc_pr": deltas,
            "criterio_1_familias_ciegas": {"detalle": crit1, "cumple": crit1_ok,
                                           "regla": "recall geométrico >= 0.70 y recall del mejor baseline < 0.10"},
            "criterio_2_familias_comunes": {"detalle": crit2, "cumple": crit2_ok,
                                            "regla": "IC95 inferior de ΔAUC-PR >= -0.05 (no ser materialmente peor)"},
        }
        baseline = {
            "fuertes": list(BASELINES.keys()),
            "control_de_nivel": "detector aleatorio de igual volumen de alertas",
            "debil_previo": "cuantil de |retorno| (usado en dq_price_control)",
        }
        notes = _notes(por_familia, crit1, crit2, crit1_ok, crit2_ok, decision)
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                artifacts=[art], decision=decision, notes=notes)


def _notes(por_familia, crit1, crit2, crit1_ok, crit2_ok, decision) -> str:
    partes: List[str] = []
    for f, info in por_familia.items():
        g = info["geometrico"]["auc_pr"]
        bb = info.get("mejor_baseline")
        b = info["baselines"][bb]["auc_pr"] if bb else float("nan")
        partes.append(f"{f}: AUC-PR geom {g:.3f} vs {bb} {b:.3f}")
    txt = " · ".join(partes)
    c1 = "CUMPLE" if crit1_ok else "NO CUMPLE"
    c2 = "CUMPLE" if crit2_ok else "NO CUMPLE"
    detalle_c1 = "; ".join(
        f"{f}: geom {v['recall_geometrico']:.2f} vs baseline {v['recall_mejor_baseline']:.2f}"
        for f, v in crit1.items())
    return (f"[{decision.upper()}] {txt}. "
            f"Criterio 1 (familias ciegas, pre-registrado) {c1} — {detalle_c1}. "
            f"Criterio 2 (familias comunes) {c2}. "
            "Veredicto emitido contra los umbrales congelados en docs/PREREGISTRO.md, "
            "sin optimizar hiperparámetros del control geométrico.")
