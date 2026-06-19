"""Validación cruzada purgada, embargo y walk-forward para series temporales.

Implementa los esquemas anti-fuga de López de Prado (2018), *Advances in
Financial Machine Learning*, Cap. 7 (Purged K-Fold CV, purging y embargo) y
Cap. 12 (Walk-Forward y Combinatorial Purged CV).

Motivación específica de este proyecto
--------------------------------------
Las ventanas de BRENT tienen `lookback=32` con `stride=1`, por lo que dos
ventanas contiguas comparten 31 de 32 observaciones. Además, cada etiqueta
depende del futuro (`horizon` + `support_resistance_horizon`). Sin purging y
embargo, ventanas de train solapan en el tiempo con ventanas de test y las
métricas quedan infladas (look-ahead / leakage).

Cada ventana `i` tiene un *information span* en el eje temporal del `frame`:

    left_i  = start_i                      (primer índice del lookback)
    right_i = end_i - 1 + max_future       (último índice que influye en la etiqueta)

Dos ventanas filtran información si sus spans se solapan. El purging elimina del
train toda ventana cuyo span solape con el de cualquier ventana de test; el
embargo elimina adicionalmente ventanas inmediatamente posteriores al test.

Referencias
-----------
- López de Prado, M. (2018). *Advances in Financial Machine Learning*, Wiley.
  Cap. 7.4 (Purged K-Fold CV), 7.4.1 (Purging), 7.4.2 (Embargo), 12.2
  (Walk-Forward), 12.3 (Combinatorial Purged CV).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FoldSplit:
    """Índices posicionales (0..N-1 sobre la window_table ordenada por fecha)."""

    fold_id: int
    train: np.ndarray
    valid: np.ndarray
    test: np.ndarray


def compute_information_spans(
    window_table: pd.DataFrame,
    max_future: int,
) -> np.ndarray:
    """Devuelve array (N, 2) con [left, right] del span temporal de cada ventana.

    `left`  = start (índice de inicio del lookback en el frame).
    `right` = end - 1 + max_future (último índice del frame que influye la etiqueta).
    """
    if not {"start", "end"}.issubset(window_table.columns):
        raise ValueError("window_table debe contener columnas 'start' y 'end'.")
    start = window_table["start"].to_numpy(dtype=np.int64)
    end = window_table["end"].to_numpy(dtype=np.int64)
    left = start
    right = end - 1 + int(max_future)
    return np.stack([left, right], axis=1)


def purge_indices(
    candidate_idx: np.ndarray,
    test_idx: np.ndarray,
    spans: np.ndarray,
) -> np.ndarray:
    """Elimina de `candidate_idx` toda muestra cuyo span solape con el de test.

    Implementa el purging de López de Prado (2018), Sección 7.4.1: dos muestras
    están relacionadas si sus intervalos de información se solapan.
    """
    if len(test_idx) == 0 or len(candidate_idx) == 0:
        return candidate_idx
    test_left = spans[test_idx, 0]
    test_right = spans[test_idx, 1]
    t_min = int(test_left.min())
    t_max = int(test_right.max())

    cand_left = spans[candidate_idx, 0]
    cand_right = spans[candidate_idx, 1]
    # Solape de intervalos [cand_left, cand_right] con [t_min, t_max].
    overlaps = (cand_left <= t_max) & (cand_right >= t_min)
    return candidate_idx[~overlaps]


def apply_embargo(
    candidate_idx: np.ndarray,
    test_idx: np.ndarray,
    n_total: int,
    embargo: int,
) -> np.ndarray:
    """Aplica embargo: elimina muestras dentro de `embargo` posiciones tras el test.

    López de Prado (2018), Sección 7.4.2. El embargo cubre correlación serial
    residual no capturada por el purging puro.
    """
    if embargo <= 0 or len(test_idx) == 0 or len(candidate_idx) == 0:
        return candidate_idx
    test_max = int(np.max(test_idx))
    embargo_end = min(n_total - 1, test_max + int(embargo))
    test_min = int(np.min(test_idx))
    # Embargo aplica a posiciones posteriores al bloque de test.
    embargoed = (candidate_idx > test_max) & (candidate_idx <= embargo_end)
    # También evitamos muestras anteriores inmediatas (embargo simétrico ligero).
    embargoed |= (candidate_idx < test_min) & (candidate_idx >= test_min - int(embargo))
    return candidate_idx[~embargoed]


def walk_forward_folds(
    window_table: pd.DataFrame,
    n_splits: int,
    max_future: int,
    embargo: int = 0,
    valid_fraction: float = 0.15,
    expanding: bool = True,
    min_train_size: int = 64,
    rolling_train_size: int | None = None,
) -> List[FoldSplit]:
    """Genera folds walk-forward purgados con embargo.

    El eje temporal (window_table ordenada por fecha) se parte en `n_splits`
    bloques de test consecutivos. Para cada bloque:
      - train = todo lo anterior (expanding) o una ventana rolling fija,
      - valid = cola contigua del train (fracción `valid_fraction`),
      - se purga el train respecto a valid y test y se aplica embargo.

    Esto reproduce el esquema "train + val + test" deslizante en el tiempo y,
    al repetirse sobre todos los bloques, "vuelve a empezar" hacia delante,
    generando múltiples caminos de backtest (cf. Cap. 12).
    """
    n = len(window_table)
    if n_splits < 1:
        raise ValueError("n_splits debe ser >= 1.")
    spans = compute_information_spans(window_table, max_future=max_future)

    test_blocks = np.array_split(np.arange(n), n_splits + 1)
    # El primer bloque solo sirve como train inicial; los test van del 2º en adelante.
    folds: List[FoldSplit] = []
    fold_id = 0
    for b in range(1, len(test_blocks)):
        test_idx = test_blocks[b]
        if len(test_idx) == 0:
            continue
        test_start = int(test_idx[0])

        history = np.arange(0, test_start)
        if rolling_train_size and not expanding:
            history = history[-int(rolling_train_size):]
        if len(history) < min_train_size:
            continue

        n_valid = max(1, int(round(len(history) * float(valid_fraction))))
        n_valid = min(n_valid, len(history) - 1)
        train_idx = history[:-n_valid]
        valid_idx = history[-n_valid:]

        # Purga train respecto a valid y a test, y aplica embargo.
        train_idx = purge_indices(train_idx, valid_idx, spans)
        train_idx = purge_indices(train_idx, test_idx, spans)
        train_idx = apply_embargo(train_idx, valid_idx, n, embargo)
        train_idx = apply_embargo(train_idx, test_idx, n, embargo)
        # Purga valid respecto a test.
        valid_idx = purge_indices(valid_idx, test_idx, spans)
        valid_idx = apply_embargo(valid_idx, test_idx, n, embargo)

        if len(train_idx) < min_train_size or len(valid_idx) == 0:
            continue

        folds.append(
            FoldSplit(
                fold_id=fold_id,
                train=np.sort(train_idx),
                valid=np.sort(valid_idx),
                test=np.sort(test_idx),
            )
        )
        fold_id += 1

    if not folds:
        raise ValueError(
            "No se generaron folds walk-forward. Revisa n_splits, min_train_size "
            "o el tamaño del dataset."
        )
    return folds


def single_holdout_split(
    window_table: pd.DataFrame,
    max_future: int,
    embargo: int = 0,
    train_fraction: float = 0.72,
    valid_fraction: float = 0.08,
) -> FoldSplit:
    """Split único train/valid/test purgado (compatible con el flujo clásico)."""
    n = len(window_table)
    spans = compute_information_spans(window_table, max_future=max_future)
    train_end = int(round(n * train_fraction))
    valid_end = int(round(n * (train_fraction + valid_fraction)))
    train_idx = np.arange(0, train_end)
    valid_idx = np.arange(train_end, valid_end)
    test_idx = np.arange(valid_end, n)

    train_idx = purge_indices(train_idx, valid_idx, spans)
    train_idx = purge_indices(train_idx, test_idx, spans)
    train_idx = apply_embargo(train_idx, valid_idx, n, embargo)
    train_idx = apply_embargo(train_idx, test_idx, n, embargo)
    valid_idx = purge_indices(valid_idx, test_idx, spans)
    valid_idx = apply_embargo(valid_idx, test_idx, n, embargo)

    return FoldSplit(fold_id=0, train=train_idx, valid=valid_idx, test=test_idx)


def folds_to_split_column(folds: Sequence[FoldSplit], n: int, fold_id: int) -> np.ndarray:
    """Construye un array de strings 'train'/'valid'/'test'/'none' para un fold."""
    fold = next((f for f in folds if f.fold_id == fold_id), None)
    if fold is None:
        raise ValueError(f"fold_id {fold_id} no encontrado.")
    split = np.full(n, "none", dtype=object)
    split[fold.train] = "train"
    split[fold.valid] = "valid"
    split[fold.test] = "test"
    return split
