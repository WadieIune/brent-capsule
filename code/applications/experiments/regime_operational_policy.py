"""WP2-B: supervivencia del canal como política operativa de riesgo.

Implementa el contrato congelado en docs/PREREGISTRO.md sin leer resultados del
Track A. La política revisa parámetros cuando la probabilidad condicional Cox de
ruptura en cinco sesiones cruza un umbral elegido exclusivamente en train.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

import common


COST_GRID = np.arange(4, 25, dtype=float)
TOLERANCE = 5
BOOTSTRAP = 3000
COX_PENALIZER = 0.1
EWMA_LAMBDA = 0.94


def load_observed_prices(cfg: Dict[str, object], seed: int) -> Tuple[pd.Series, str]:
    """Carga sesiones observadas sin insertar ni rellenar días ausentes."""
    if bool(cfg.get("synthetic", False)):
        return common.synthetic_brent(seed=seed), "synthetic"
    path = cfg.get("prices_path") or common.cs._default_prices_path()
    if not path or not os.path.exists(str(path)):
        return common.synthetic_brent(seed=seed), (
            "synthetic (fallback: serie real no encontrada)"
        )
    raw = pd.read_csv(str(path))
    dcol = next(
        c for c in raw.columns
        if c.lower() in ("date", "fecha", "observation_date")
    )
    pcol = next(
        c for c in raw.columns
        if c.upper() in ("BRENT", "DCOILBRENTEU", "VALUE", "CLOSE")
    )
    raw[dcol] = pd.to_datetime(raw[dcol])
    series = (
        raw[[dcol, pcol]]
        .dropna()
        .drop_duplicates(dcol, keep="last")
        .sort_values(dcol)
        .set_index(dcol)[pcol]
        .astype(float)
    )
    return series, f"file:{path} (sesiones observadas, sin relleno)"


def _step_value(times: np.ndarray, values: np.ndarray, x: float) -> float:
    index = int(np.searchsorted(times, x, side="right") - 1)
    return 0.0 if index < 0 else float(values[min(index, len(values) - 1)])


def _fit_cox(episodes: pd.DataFrame, cutoff: pd.Timestamp):
    """Cox único con censura administrativa en el corte."""
    from lifelines import CoxPHFitter

    censored = common.cs.administrative_censoring(episodes, cutoff)
    train = censored.loc[censored["start_date"] <= cutoff].copy()
    x = train[common.FEATURES].to_numpy(float)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    fit = pd.DataFrame((x - mean) / scale, columns=common.FEATURES)
    fit["duration"] = train["duration"].to_numpy(float).clip(min=0.5)
    fit["event"] = train["event"].to_numpy(int)
    model = CoxPHFitter(penalizer=COX_PENALIZER).fit(
        fit, duration_col="duration", event_col="event"
    )
    return model, mean, scale, train


def _conditional_scores(
    episodes: pd.DataFrame,
    dates: pd.DatetimeIndex,
    model,
    mean: np.ndarray,
    scale: np.ndarray,
) -> np.ndarray:
    """Calcula P(T <= edad+5 | T > edad, x) en cada sesión activa."""
    dense = np.full(len(dates), np.nan, dtype=float)
    positions = {pd.Timestamp(date): i for i, date in enumerate(dates)}
    baseline = model.baseline_cumulative_hazard_
    base_times = baseline.index.to_numpy(float)
    base_values = baseline.iloc[:, 0].to_numpy(float)
    x = (episodes[common.FEATURES].to_numpy(float) - mean) / scale
    risks = model.predict_partial_hazard(
        pd.DataFrame(x, columns=common.FEATURES)
    ).to_numpy().ravel()
    for (_, episode), risk in zip(episodes.iterrows(), risks):
        start = positions.get(pd.Timestamp(episode["start_date"]))
        end = positions.get(pd.Timestamp(episode["end_date"]))
        if start is None or end is None or end <= start:
            continue
        for position in range(start, end):
            age = float(position - start)
            increment = max(
                _step_value(base_times, base_values, age + TOLERANCE)
                - _step_value(base_times, base_values, age),
                0.0,
            )
            dense[position] = float(
                np.clip(1.0 - np.exp(-increment * risk), 0.0, 1.0)
            )
    return dense


def _threshold_reviews(
    scores: np.ndarray, mask: np.ndarray, threshold: float
) -> np.ndarray:
    """Revisa únicamente al cruzar el umbral desde abajo."""
    reviews: List[int] = []
    was_above = False
    for i, score in enumerate(scores):
        if not mask[i] or not np.isfinite(score):
            was_above = False
            continue
        above = bool(score >= threshold)
        if above and not was_above:
            reviews.append(i)
        was_above = above
    return np.asarray(reviews, dtype=int)


def _event_positions(
    episodes: pd.DataFrame, dates: pd.DatetimeIndex, mask: np.ndarray
) -> np.ndarray:
    positions = {pd.Timestamp(date): i for i, date in enumerate(dates)}
    result = []
    for date in episodes.loc[episodes["event"].astype(int) == 1, "end_date"]:
        position = positions.get(pd.Timestamp(date))
        if position is not None and mask[position]:
            result.append(position)
    return np.asarray(result, dtype=int)


def _hit_vector(
    events: np.ndarray, reviews: np.ndarray, tolerance: int = TOLERANCE
) -> np.ndarray:
    """Un evento está cubierto si hubo revisión 1..5 sesiones antes."""
    review_set = set(int(value) for value in reviews)
    return np.asarray(
        [
            float(
                any(
                    (int(event) - lag) in review_set
                    for lag in range(1, tolerance + 1)
                )
            )
            for event in events
        ],
        dtype=float,
    )


def _years(mask: np.ndarray, dates: pd.DatetimeIndex) -> float:
    selected = dates[mask]
    return max(float((selected[-1] - selected[0]).days) / 365.2425, 1.0 / 252.0)


def _rate_points(
    scores: np.ndarray,
    dates: pd.DatetimeIndex,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    train_events: np.ndarray,
    test_events: np.ndarray,
) -> List[Dict[str, object]]:
    """Calibra cada umbral de la curva exclusivamente con train.

    Los puntos de umbral trazan la curva y no son configuraciones distintas del
    modelo. Cada política desplegada usa un único umbral.
    """
    finite = scores[train_mask & np.isfinite(scores)]
    if not len(finite):
        return []
    thresholds = np.unique(np.quantile(finite, np.linspace(0.0, 1.0, 401)))
    train_years = _years(train_mask, dates)
    test_years = _years(test_mask, dates)
    candidates: List[Dict[str, object]] = []
    for threshold in thresholds:
        reviews = _threshold_reviews(scores, train_mask, float(threshold))
        hits = _hit_vector(train_events, reviews)
        candidates.append(
            {
                "threshold": float(threshold),
                "train_cost": float(len(reviews) / train_years),
                "train_coverage": float(hits.mean()) if len(hits) else 0.0,
            }
        )
    points: List[Dict[str, object]] = []
    used: set[float] = set()
    for target in COST_GRID:
        chosen = min(
            candidates,
            key=lambda row: (
                abs(float(row["train_cost"]) - target),
                -float(row["train_coverage"]),
                float(row["threshold"]),
            ),
        )
        threshold = float(chosen["threshold"])
        if threshold in used:
            continue
        used.add(threshold)
        reviews = _threshold_reviews(scores, test_mask, threshold)
        points.append(
            {
                "target_cost": float(target),
                "threshold": threshold,
                "train_cost": float(chosen["train_cost"]),
                "train_coverage": float(chosen["train_coverage"]),
                "test_reviews": reviews,
                "test_cost": float(len(reviews) / test_years),
                "test_hits": _hit_vector(test_events, reviews),
            }
        )
    return points


def _calendar_points(
    dates: pd.DatetimeIndex,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    train_events: np.ndarray,
    test_events: np.ndarray,
) -> List[Dict[str, object]]:
    """Baseline fuerte: periodicidad y fase óptimas elegidas en train."""
    train_years = _years(train_mask, dates)
    test_years = _years(test_mask, dates)
    positions = np.arange(len(dates))
    points: List[Dict[str, object]] = []
    for target in COST_GRID:
        period = max(int(round(252.0 / target)), 1)
        candidates = []
        for phase in range(period):
            reviews = positions[train_mask & ((positions % period) == phase)]
            hits = _hit_vector(train_events, reviews)
            coverage = float(hits.mean()) if len(hits) else 0.0
            candidates.append((coverage, phase, reviews))
        coverage, phase, train_reviews = max(
            candidates, key=lambda row: (row[0], -row[1])
        )
        test_reviews = positions[test_mask & ((positions % period) == phase)]
        points.append(
            {
                "target_cost": float(target),
                "period": int(period),
                "phase": int(phase),
                "train_cost": float(len(train_reviews) / train_years),
                "train_coverage": coverage,
                "test_reviews": test_reviews,
                "test_cost": float(len(test_reviews) / test_years),
                "test_hits": _hit_vector(test_events, test_reviews),
            }
        )
    return points


def _interpolated_hits(
    points: List[Dict[str, object]], cost: float
) -> Optional[np.ndarray]:
    ordered = sorted(points, key=lambda row: float(row["test_cost"]))
    collapsed: List[Dict[str, object]] = []
    for point in ordered:
        if (
            collapsed
            and abs(float(point["test_cost"]) - float(collapsed[-1]["test_cost"]))
            < 1e-12
        ):
            continue
        collapsed.append(point)
    if (
        not collapsed
        or cost < float(collapsed[0]["test_cost"])
        or cost > float(collapsed[-1]["test_cost"])
    ):
        return None
    for point in collapsed:
        if abs(float(point["test_cost"]) - cost) < 1e-12:
            return np.asarray(point["test_hits"], float)
    for left, right in zip(collapsed[:-1], collapsed[1:]):
        low, high = float(left["test_cost"]), float(right["test_cost"])
        if low <= cost <= high:
            weight = (cost - low) / max(high - low, 1e-12)
            return (
                (1.0 - weight) * np.asarray(left["test_hits"], float)
                + weight * np.asarray(right["test_hits"], float)
            )
    return None


def _random_expected_hits(
    events: np.ndarray,
    test_mask: np.ndarray,
    annual_cost: float,
    test_years: float,
) -> np.ndarray:
    """Esperanza exacta de una política aleatoria sin reemplazo."""
    eligible = np.flatnonzero(test_mask)
    eligible_set = set(int(value) for value in eligible)
    total = len(eligible)
    n_reviews = min(int(round(annual_cost * test_years)), total)
    probabilities = []
    for event in events:
        window = sum(
            (int(event) - lag) in eligible_set
            for lag in range(1, TOLERANCE + 1)
        )
        if window == 0 or n_reviews == 0:
            probabilities.append(0.0)
            continue
        if n_reviews > total - window:
            probabilities.append(1.0)
            continue
        p_none = 1.0
        for j in range(n_reviews):
            p_none *= (total - window - j) / (total - j)
        probabilities.append(1.0 - p_none)
    return np.asarray(probabilities, dtype=float)


def _bootstrap_delta(
    first: np.ndarray, second: np.ndarray, seed: int
) -> Dict[str, float]:
    if len(first) == 0 or len(first) != len(second):
        return {"delta": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    rng = np.random.default_rng(seed)
    difference = np.asarray(first, float) - np.asarray(second, float)
    draws = np.empty(BOOTSTRAP, dtype=float)
    for i in range(BOOTSTRAP):
        sample = rng.integers(0, len(difference), len(difference))
        draws[i] = difference[sample].mean()
    return {
        "delta": float(difference.mean()),
        "ci_low": float(np.percentile(draws, 2.5)),
        "ci_high": float(np.percentile(draws, 97.5)),
    }


def _lead_time(events: np.ndarray, reviews: np.ndarray) -> Dict[str, object]:
    leads = []
    reviews = np.asarray(reviews, int)
    for event in events:
        valid = reviews[
            (reviews < event) & (reviews >= event - TOLERANCE)
        ]
        if len(valid):
            leads.append(int(event - valid.max()))
    return {
        "covered_events": int(len(leads)),
        "median_sessions": float(np.median(leads)) if leads else None,
        "p25_sessions": float(np.percentile(leads, 25)) if leads else None,
        "p75_sessions": float(np.percentile(leads, 75)) if leads else None,
    }


def evaluate(
    prices: np.ndarray,
    dates: pd.DatetimeIndex,
    cutoff: str,
    seed: int,
    out_dir: str,
) -> Tuple[Dict[str, object], Dict[str, object], str, str, List[str]]:
    """Ejecuta el Track B preregistrado y devuelve piezas de ExperimentResult."""
    cutoff_ts = pd.Timestamp(cutoff)
    episodes = common.cs.extract_episodes(prices, dates)
    model, mean, scale, train_episodes = _fit_cox(episodes, cutoff_ts)
    survival_score = _conditional_scores(
        episodes, dates, model, mean, scale
    )
    returns = np.diff(np.log(np.clip(prices, 1e-12, None)))
    ewma_score = np.full(len(prices), np.nan)
    ewma_score[1:] = common.ewma_vol(returns, EWMA_LAMBDA)

    train_mask = np.asarray(dates <= cutoff_ts, bool)
    test_mask = ~train_mask
    train_events = _event_positions(episodes, dates, train_mask)
    test_events = _event_positions(episodes, dates, test_mask)
    survival_points = _rate_points(
        survival_score, dates, train_mask, test_mask, train_events, test_events
    )
    ewma_points = _rate_points(
        ewma_score, dates, train_mask, test_mask, train_events, test_events
    )
    calendar_points = _calendar_points(
        dates, train_mask, test_mask, train_events, test_events
    )
    test_years = _years(test_mask, dates)

    rows: List[Dict[str, object]] = []
    comparable: List[Dict[str, object]] = []
    for cost in COST_GRID:
        survival_hits = _interpolated_hits(survival_points, float(cost))
        calendar_hits = _interpolated_hits(calendar_points, float(cost))
        ewma_hits = _interpolated_hits(ewma_points, float(cost))
        if survival_hits is None or calendar_hits is None or ewma_hits is None:
            rows.append({"cost_reviews_year": float(cost), "comparable": False})
            continue
        random_hits = _random_expected_hits(
            test_events, test_mask, float(cost), test_years
        )
        delta_calendar = _bootstrap_delta(
            survival_hits, calendar_hits, seed + int(cost) * 10 + 1
        )
        delta_ewma = _bootstrap_delta(
            survival_hits, ewma_hits, seed + int(cost) * 10 + 2
        )
        delta_random = _bootstrap_delta(
            survival_hits, random_hits, seed + int(cost) * 10 + 3
        )
        row = {
            "cost_reviews_year": float(cost),
            "comparable": True,
            "coverage_survival": float(survival_hits.mean()),
            "coverage_calendar": float(calendar_hits.mean()),
            "coverage_ewma": float(ewma_hits.mean()),
            "coverage_random": float(random_hits.mean()),
            "delta_calendar": delta_calendar["delta"],
            "ci_calendar_low": delta_calendar["ci_low"],
            "ci_calendar_high": delta_calendar["ci_high"],
            "delta_ewma": delta_ewma["delta"],
            "ci_ewma_low": delta_ewma["ci_low"],
            "ci_ewma_high": delta_ewma["ci_high"],
            "delta_random": delta_random["delta"],
            "ci_random_low": delta_random["ci_low"],
            "ci_random_high": delta_random["ci_high"],
        }
        rows.append(row)
        comparable.append(row)

    table = pd.DataFrame(rows)
    artifact = os.path.join(out_dir, "regime_policy_cost_coverage.csv")
    os.makedirs(out_dir, exist_ok=True)
    table.to_csv(artifact, index=False)

    comparable_frame = pd.DataFrame(comparable)
    if len(comparable_frame):
        x = comparable_frame["cost_reviews_year"].to_numpy(float)
        span = max(float(x[-1] - x[0]), 1.0)
        area = {
            name: float(
                np.trapz(
                    comparable_frame[f"coverage_{name}"].to_numpy(float), x
                )
                / span
            )
            for name in ("survival", "calendar", "ewma", "random")
        }
        full_range = bool(x[0] <= 4.0 and x[-1] >= 24.0 and len(x) == 21)
        dominates = bool(
            full_range
            and (comparable_frame["delta_calendar"] >= 0.05).all()
            and (comparable_frame["delta_ewma"] >= 0.05).all()
            and (comparable_frame["ci_calendar_low"] > 0.0).all()
            and (comparable_frame["ci_ewma_low"] > 0.0).all()
            and (comparable_frame["ci_random_low"] > 0.0).all()
        )
    else:
        area, full_range, dominates = {}, False, False

    selected = (
        max(
            survival_points,
            key=lambda row: (
                float(row["train_coverage"])
                - float(row["train_cost"]) / 24.0,
                -float(row["train_cost"]),
            ),
        )
        if survival_points
        else None
    )
    selected_metrics: Dict[str, object] = {}
    if selected is not None:
        selected_hits = np.asarray(selected["test_hits"], float)
        selected_metrics = {
            "threshold": float(selected["threshold"]),
            "train_cost_reviews_year": float(selected["train_cost"]),
            "train_coverage": float(selected["train_coverage"]),
            "test_cost_reviews_year": float(selected["test_cost"]),
            "test_coverage": (
                float(selected_hits.mean()) if len(selected_hits) else 0.0
            ),
            "lead_time": _lead_time(
                test_events, np.asarray(selected["test_reviews"], int)
            ),
        }

    test_episodes = episodes.loc[episodes["start_date"] > cutoff_ts].copy()
    c_index = None
    if len(test_episodes) and int(test_episodes["event"].sum()) > 0:
        from lifelines.utils import concordance_index

        x_test = (
            test_episodes[common.FEATURES].to_numpy(float) - mean
        ) / scale
        risk = model.predict_partial_hazard(
            pd.DataFrame(x_test, columns=common.FEATURES)
        ).to_numpy().ravel()
        c_index = float(
            concordance_index(
                test_episodes["duration"].to_numpy(float),
                -risk,
                test_episodes["event"].to_numpy(int),
            )
        )

    active_test = np.flatnonzero(test_mask & np.isfinite(survival_score))
    event_set = set(int(value) for value in test_events)
    y_day = np.asarray(
        [
            float(
                any(
                    (int(position) + lag) in event_set
                    for lag in range(1, TOLERANCE + 1)
                )
            )
            for position in active_test
        ]
    )
    brier = (
        float(brier_score_loss(y_day, survival_score[active_test]))
        if len(active_test)
        else None
    )

    decision = "accept" if dominates else "reject"
    metrics = {
        "protocol": {
            "cutoff": str(cutoff_ts.date()),
            "business_days": "observed_only",
            "tolerance_sessions": TOLERANCE,
            "operational_range_reviews_year": [4, 24],
            "bootstrap_replicates": BOOTSTRAP,
            "cox_penalizer": COX_PENALIZER,
            "ewma_lambda": EWMA_LAMBDA,
            "model_configurations_explored": 1,
            "threshold_selection": (
                "train only; one threshold per deployed policy"
            ),
        },
        "n_episodes": int(len(episodes)),
        "n_train_episodes_after_admin_censoring": int(len(train_episodes)),
        "n_train_events": int(len(train_events)),
        "n_test_events": int(len(test_events)),
        "test_years": test_years,
        "full_operational_range_comparable": full_range,
        "area_under_cost_coverage": area,
        "selected_train_threshold_policy": selected_metrics,
        "secondary": {
            "cox_c_index_test": c_index,
            "break_probability_brier_test": brier,
        },
        "cost_coverage": comparable,
        "success_rule": {
            "minimum_gain_pp_each_cost": 5.0,
            "ci95_excludes_zero_each_cost": True,
            "dominates_calendar_and_ewma": dominates,
        },
    }
    baseline = {
        "calendar": (
            "periodicidad y fase óptimas elegidas exclusivamente en train"
        ),
        "volatility": (
            "EWMA lambda=0.94; umbrales calibrados exclusivamente en train"
        ),
        "random_control": (
            "fechas aleatorias sin reemplazo, misma frecuencia; esperanza exacta"
        ),
        "area_under_cost_coverage": area,
    }
    if len(comparable_frame):
        min_calendar = 100.0 * float(comparable_frame["delta_calendar"].min())
        min_ewma = 100.0 * float(comparable_frame["delta_ewma"].min())
        min_random = 100.0 * float(comparable_frame["delta_random"].min())
    else:
        min_calendar = min_ewma = min_random = float("nan")
    notes = (
        f"WP2-B {'ACEPTADO' if dominates else 'RECHAZADO'} contra el umbral "
        f"congelado. AUC coste-cobertura: supervivencia={area.get('survival')} · "
        f"calendario={area.get('calendar')} · EWMA={area.get('ewma')} · "
        f"azar={area.get('random')}. Ganancia mínima en 4-24 revisiones/año: "
        f"calendario={min_calendar:+.2f} pp · EWMA={min_ewma:+.2f} pp · "
        f"azar={min_random:+.2f} pp."
    )
    return metrics, baseline, decision, notes, [artifact]
