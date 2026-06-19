"""Métricas de clasificación balanceadas y validación estadística de backtests.

Incluye:
  - Métricas de clasificación robustas al desbalance (balanced accuracy,
    macro-F1, matriz de confusión, soporte por clase).
  - Métricas financieras con corrección por overfitting de López de Prado:
      * Probabilistic Sharpe Ratio (PSR).
      * Deflated Sharpe Ratio (DSR).
      * Probability of Backtest Overfitting (PBO) vía CSCV.

Referencias
-----------
- Bailey, D. H., & López de Prado, M. (2012). "The Sharpe Ratio Efficient
  Frontier." *Journal of Risk*, 15(2). [PSR]
- Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio:
  Correcting for Selection Bias, Backtest Overfitting, and Non-Normality."
  *Journal of Portfolio Management*, 40(5). [DSR]
- Bailey, Borwein, López de Prado & Zhu (2014/2017). "The Probability of
  Backtest Overfitting." *Journal of Computational Finance*. [PBO / CSCV]
- López de Prado, M. (2018). *Advances in Financial Machine Learning*, Wiley.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Sequence

import numpy as np


# Constante de Euler-Mascheroni (usada en el valor esperado del máximo de SR).
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
    plow = 0.02425
    phigh = 1 - plow
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


# ---------------------------------------------------------------------------
# Métricas de clasificación
# ---------------------------------------------------------------------------

def confusion_matrix(y_true: Sequence, y_pred: Sequence, labels: Sequence) -> np.ndarray:
    index = {label: i for i, label in enumerate(labels)}
    mat = np.zeros((len(labels), len(labels)), dtype=int)
    for t, p in zip(y_true, y_pred):
        if t in index and p in index:
            mat[index[t], index[p]] += 1
    return mat


def classification_metrics(
    y_true: Sequence,
    y_pred: Sequence,
    labels: Sequence,
) -> Dict[str, object]:
    """Métricas robustas al desbalance, sin dependencias externas obligatorias."""
    labels = list(labels)
    cm = confusion_matrix(y_true, y_pred, labels)
    support = cm.sum(axis=1)
    correct = np.diag(cm)

    # Recall por clase (sensibilidad), evitando división por cero.
    recall = np.divide(correct, support, out=np.zeros_like(correct, dtype=float), where=support > 0)
    pred_count = cm.sum(axis=0)
    precision = np.divide(correct, pred_count, out=np.zeros_like(correct, dtype=float), where=pred_count > 0)
    f1 = np.divide(2 * precision * recall, precision + recall,
                   out=np.zeros_like(precision), where=(precision + recall) > 0)

    present = support > 0
    accuracy = float(correct.sum() / max(1, cm.sum()))
    balanced_accuracy = float(np.mean(recall[present])) if present.any() else 0.0
    macro_f1 = float(np.mean(f1[present])) if present.any() else 0.0

    per_class = {
        labels[i]: {
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1[i]),
            "support": int(support[i]),
        }
        for i in range(len(labels))
    }
    return {
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "macro_f1": macro_f1,
        "confusion_matrix": cm.tolist(),
        "labels": labels,
        "per_class": per_class,
        "n": int(cm.sum()),
    }


def class_weights_from_counts(counts: np.ndarray, scheme: str = "balanced") -> np.ndarray:
    """Pesos de clase para CrossEntropy. 'balanced' = n / (k * count_c)."""
    counts = np.asarray(counts, dtype=float)
    k = len(counts)
    total = counts.sum()
    if scheme == "balanced":
        weights = np.where(counts > 0, total / (k * counts), 0.0)
    elif scheme == "inverse":
        weights = np.where(counts > 0, 1.0 / counts, 0.0)
    elif scheme == "sqrt_inverse":
        weights = np.where(counts > 0, 1.0 / np.sqrt(counts), 0.0)
    else:
        weights = np.ones_like(counts)
    # Normaliza a media 1 sobre clases presentes para no escalar el LR efectivo.
    present = counts > 0
    if present.any():
        weights = weights / weights[present].mean()
    return weights


# ---------------------------------------------------------------------------
# Métricas financieras / validación de backtest
# ---------------------------------------------------------------------------

def sharpe_ratio(returns: np.ndarray, periods_per_year: int = 252) -> float:
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]
    if returns.size < 2 or returns.std(ddof=1) == 0:
        return 0.0
    sr = returns.mean() / returns.std(ddof=1)
    return float(sr * math.sqrt(periods_per_year))


def probabilistic_sharpe_ratio(
    returns: np.ndarray,
    sr_benchmark: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """PSR: probabilidad de que el SR verdadero supere `sr_benchmark`.

    Bailey & López de Prado (2012). Trabaja con el SR no anualizado y corrige por
    asimetría (skew) y curtosis de los retornos.
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]
    n = returns.size
    if n < 4 or returns.std(ddof=1) == 0:
        return float("nan")
    mu = returns.mean()
    sigma = returns.std(ddof=1)
    sr_hat = mu / sigma  # por periodo
    sr_star = sr_benchmark / math.sqrt(periods_per_year)  # de anualizado a por periodo

    skew = float(((returns - mu) ** 3).mean() / sigma ** 3)
    kurt = float(((returns - mu) ** 4).mean() / sigma ** 4)  # curtosis (no exceso)

    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_hat + ((kurt - 1.0) / 4.0) * sr_hat ** 2))
    psr = _norm_cdf(((sr_hat - sr_star) * math.sqrt(n - 1)) / denom)
    return float(psr)


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """E[max SR] esperado bajo `n_trials` pruebas independientes (Bailey & LdP 2014)."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    e = math.e
    gamma = _EULER_MASCHERONI
    term = (1.0 - gamma) * _norm_ppf(1.0 - 1.0 / n_trials) + \
        gamma * _norm_ppf(1.0 - 1.0 / (n_trials * e))
    return float(math.sqrt(sr_variance) * term)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    sr_trials: Sequence[float],
    periods_per_year: int = 252,
) -> Dict[str, float]:
    """DSR: PSR usando como benchmark el SR máximo esperado por azar.

    `sr_trials` son los Sharpe (anualizados) de TODAS las configuraciones probadas
    durante la investigación (selección de hiperparámetros, folds, etc.). El DSR
    penaliza el número de pruebas y la varianza entre ellas (Bailey & LdP 2014).
    """
    sr_trials = np.asarray([s for s in sr_trials if np.isfinite(s)], dtype=float)
    n_trials = max(1, sr_trials.size)
    sr_var = float(np.var(sr_trials, ddof=1)) if n_trials > 1 else 0.0
    sr_star_annual = expected_max_sharpe(sr_var, n_trials)
    dsr = probabilistic_sharpe_ratio(returns, sr_benchmark=sr_star_annual, periods_per_year=periods_per_year)
    return {
        "deflated_sharpe_ratio": float(dsr),
        "n_trials": int(n_trials),
        "sr_trials_variance": sr_var,
        "expected_max_sharpe_annual": float(sr_star_annual),
        "observed_sharpe_annual": sharpe_ratio(returns, periods_per_year=periods_per_year),
    }


def probability_of_backtest_overfitting(
    perf_matrix: np.ndarray,
    n_partitions: int = 16,
) -> Dict[str, object]:
    """PBO mediante Combinatorial Symmetric Cross-Validation (CSCV).

    `perf_matrix` tiene forma (T, N): T periodos (filas) y N configuraciones
    (columnas), con el rendimiento por periodo (p.ej. retorno de la estrategia).
    Devuelve la probabilidad de que la mejor configuración in-sample quede por
    debajo de la mediana out-of-sample (logit <= 0).

    Bailey et al. (2014/2017).
    """
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2:
        return {"pbo": float("nan"), "n_combinations": 0, "logits": []}
    T, N = M.shape
    S = int(n_partitions)
    if S % 2 != 0:
        S += 1
    S = max(2, min(S, T))

    blocks = np.array_split(np.arange(T), S)
    block_ids = list(range(S))
    logits: List[float] = []

    for is_combo in combinations(block_ids, S // 2):
        is_rows = np.concatenate([blocks[b] for b in is_combo])
        oos_rows = np.concatenate([blocks[b] for b in block_ids if b not in is_combo])
        if is_rows.size == 0 or oos_rows.size == 0:
            continue

        is_perf = M[is_rows].mean(axis=0)
        oos_perf = M[oos_rows].mean(axis=0)
        best_is = int(np.argmax(is_perf))

        # Rango relativo OOS de la mejor configuración IS.
        order = np.argsort(oos_perf)
        ranks = np.empty(N, dtype=float)
        ranks[order] = np.arange(1, N + 1)
        w = ranks[best_is] / (N + 1.0)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1.0 - w)))

    if not logits:
        return {"pbo": float("nan"), "n_combinations": 0, "logits": []}
    logits_arr = np.asarray(logits, dtype=float)
    pbo = float(np.mean(logits_arr <= 0.0))
    return {
        "pbo": pbo,
        "n_combinations": int(len(logits)),
        "logit_mean": float(logits_arr.mean()),
        "logit_median": float(np.median(logits_arr)),
    }
