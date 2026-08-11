"""metrics_min — métricas de robustez financiera (vendorizadas, sin dependencias).

Copia mínima y autocontenida de las métricas de validación de backtest que usa la
1ª pata del proyecto (`code/brent_pattern_system/metrics.py`), para que este
módulo siga siendo independiente del paquete principal (misma filosofía que
`patterns_min.py`).

Incluye:
  - `sharpe_ratio`                        Sharpe anualizado.
  - `probabilistic_sharpe_ratio` (PSR)    Bailey & López de Prado (2012).
  - `deflated_sharpe_ratio` (DSR)         Bailey & López de Prado (2014).
  - `probability_of_backtest_overfitting` (PBO/CSCV)  Bailey et al. (2017).

El criterio del proyecto es que **ninguna afirmación económica se reporta con el
Sharpe a secas**: siempre acompañado de DSR (corrige por nº de configuraciones
probadas) y PBO (probabilidad de que la mejor configuración in-sample falle
out-of-sample).
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Sequence

import numpy as np

_EULER_MASCHERONI = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inversa de la CDF normal estándar (aproximación de Acklam)."""
    if p <= 0.0:
        return -np.inf
    if p >= 1.0:
        return np.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def sharpe_ratio(returns: np.ndarray, periods_per_year: float = 252) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods_per_year))


def probabilistic_sharpe_ratio(returns: np.ndarray, sr_benchmark: float = 0.0,
                               periods_per_year: float = 252) -> float:
    """P(SR verdadero > sr_benchmark), corrigiendo por asimetría y curtosis."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = r.size
    if n < 4 or r.std(ddof=1) == 0:
        return float("nan")
    mu, sigma = r.mean(), r.std(ddof=1)
    sr_hat = mu / sigma
    sr_star = sr_benchmark / math.sqrt(periods_per_year)
    skew = float(((r - mu) ** 3).mean() / sigma ** 3)
    kurt = float(((r - mu) ** 4).mean() / sigma ** 4)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_hat + ((kurt - 1.0) / 4.0) * sr_hat ** 2))
    return float(_norm_cdf(((sr_hat - sr_star) * math.sqrt(n - 1)) / denom))


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """E[máx SR] bajo `n_trials` pruebas independientes (Bailey & LdP 2014)."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    g = _EULER_MASCHERONI
    term = (1.0 - g) * _norm_ppf(1.0 - 1.0 / n_trials) + \
        g * _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(math.sqrt(sr_variance) * term)


def deflated_sharpe_ratio(returns: np.ndarray, sr_trials: Sequence[float],
                          periods_per_year: float = 252) -> Dict[str, float]:
    """PSR usando como referencia el SR máximo esperable por puro azar."""
    trials = np.asarray([s for s in sr_trials if np.isfinite(s)], dtype=float)
    n_trials = max(1, trials.size)
    sr_var = float(np.var(trials, ddof=1)) if n_trials > 1 else 0.0
    sr_star = expected_max_sharpe(sr_var, n_trials)
    return {
        "deflated_sharpe_ratio": probabilistic_sharpe_ratio(
            returns, sr_benchmark=sr_star, periods_per_year=periods_per_year),
        "n_trials": int(n_trials),
        "sr_trials_variance": sr_var,
        "expected_max_sharpe_annual": float(sr_star),
        "observed_sharpe_annual": sharpe_ratio(returns, periods_per_year),
    }


def probability_of_backtest_overfitting(perf_matrix: np.ndarray,
                                        n_partitions: int = 12) -> Dict[str, object]:
    """PBO por Combinatorially Symmetric Cross-Validation (CSCV).

    `perf_matrix` (T, N): T periodos x N configuraciones. Devuelve la frecuencia
    con que la mejor configuración in-sample cae bajo la mediana out-of-sample.
    """
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2 or M.shape[0] < 4:
        return {"pbo": float("nan"), "n_combinations": 0}
    T, N = M.shape
    S = int(n_partitions) + (int(n_partitions) % 2)
    S = max(2, min(S, T))
    blocks = np.array_split(np.arange(T), S)
    ids = list(range(S))
    logits: List[float] = []
    for combo in combinations(ids, S // 2):
        is_rows = np.concatenate([blocks[b] for b in combo])
        oos_rows = np.concatenate([blocks[b] for b in ids if b not in combo])
        if is_rows.size == 0 or oos_rows.size == 0:
            continue
        best_is = int(np.argmax(M[is_rows].mean(axis=0)))
        oos = M[oos_rows].mean(axis=0)
        order = np.argsort(oos)
        ranks = np.empty(N, dtype=float)
        ranks[order] = np.arange(1, N + 1)
        w = min(max(ranks[best_is] / (N + 1.0), 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1.0 - w)))
    if not logits:
        return {"pbo": float("nan"), "n_combinations": 0}
    arr = np.asarray(logits)
    return {
        "pbo": float(np.mean(arr <= 0.0)),
        "n_combinations": int(arr.size),
        "logit_mean": float(arr.mean()),
        "logit_median": float(np.median(arr)),
    }


def performance_stats(returns: np.ndarray, periods_per_year: float = 252) -> Dict[str, float]:
    """Estadísticos descriptivos de una curva de resultados."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size == 0:
        return {"n": 0}
    equity = np.cumprod(1.0 + r)
    dd = equity / np.maximum.accumulate(equity) - 1.0
    return {
        "n": int(r.size),
        "cumulative_return": float(equity[-1] - 1.0),
        "mean_per_trade": float(r.mean()),
        "annualized_return": float(r.mean() * periods_per_year),
        "annualized_vol": float(r.std(ddof=1) * math.sqrt(periods_per_year)) if r.size > 1 else 0.0,
        "sharpe_annual": sharpe_ratio(r, periods_per_year),
        "psr_vs_zero": probabilistic_sharpe_ratio(r, 0.0, periods_per_year),
        "max_drawdown": float(dd.min()),
        "hit_rate": float(np.mean(r > 0)),
    }
