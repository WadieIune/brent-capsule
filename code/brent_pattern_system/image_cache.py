"""Precomputación y caché de imágenes de ventanas.

El dataset real es pequeño (~1.2k ventanas), por lo que reconstruir la imagen
RGB en cada ``__getitem__`` (GASF/GADF + resize) es el cuello de botella que mata
el rendimiento en GPU. Aquí se precomputan todas las imágenes UNA vez y se
cachean en memoria (uint8) y opcionalmente en disco.

Memoria aproximada: N x image_size^2 x 3 bytes. Para N=1230 e image_size=240:
~212 MB en uint8 (vs ~850 MB en float32).
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from .datasets import build_image_for_record, synthetic_example_from_index


def _cache_key(
    feature_cols: Sequence[str],
    image_size: int,
    target_col: str,
    n_windows: int,
    extra: str = "",
) -> str:
    payload = json.dumps(
        {
            "feature_cols": list(feature_cols),
            "image_size": int(image_size),
            "target_col": str(target_col),
            "n_windows": int(n_windows),
            "extra": extra,
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def precompute_window_images(
    frame: pd.DataFrame,
    window_table: pd.DataFrame,
    feature_cols: Sequence[str],
    image_size: int,
    target_col: str,
    cache_dir: str | None = None,
    verbose: bool = True,
) -> np.ndarray:
    """Devuelve un array (N, H, W, 3) uint8 con las imágenes de todas las ventanas.

    Si `cache_dir` se proporciona y existe un fichero compatible, lo carga.
    """
    n = len(window_table)
    key = _cache_key(feature_cols, image_size, target_col, n)
    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"window_images_{key}.npy")
        if os.path.exists(cache_path):
            arr = np.load(cache_path)
            if arr.shape[0] == n and arr.shape[1] == image_size:
                if verbose:
                    print(f"[image_cache] Cargadas {arr.shape[0]} imágenes desde {cache_path}")
                return arr

    images = np.empty((n, image_size, image_size, 3), dtype=np.uint8)
    for i in range(n):
        row = window_table.iloc[i]
        img = build_image_for_record(
            frame, row, feature_cols=feature_cols, image_size=image_size, target_col=target_col
        )
        images[i] = np.clip(img, 0, 255).astype(np.uint8)
        if verbose and (i + 1) % 200 == 0:
            print(f"[image_cache] Precomputadas {i + 1}/{n} imágenes")

    if cache_path:
        np.save(cache_path, images)
        if verbose:
            print(f"[image_cache] Guardadas {n} imágenes en {cache_path}")
    return images


def precompute_synthetic_images(
    config: Dict[str, object],
    n_samples: int,
    cache_dir: str | None = None,
    verbose: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precomputa imágenes sintéticas (X uint8, y_class int64, y_reg float32)."""
    image_size = int(config["dataset"]["image_size"])
    key = _cache_key([], image_size, "synthetic", n_samples,
                     extra=str(config["dataset"].get("synthetic_seed", 123)))
    paths = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        paths = (
            os.path.join(cache_dir, f"synth_x_{key}.npy"),
            os.path.join(cache_dir, f"synth_yc_{key}.npy"),
            os.path.join(cache_dir, f"synth_yr_{key}.npy"),
        )
        if all(os.path.exists(p) for p in paths):
            if verbose:
                print(f"[image_cache] Cargadas {n_samples} imágenes sintéticas de caché")
            return np.load(paths[0]), np.load(paths[1]), np.load(paths[2])

    X = np.empty((n_samples, image_size, image_size, 3), dtype=np.uint8)
    yc = np.empty((n_samples,), dtype=np.int64)
    yr = np.empty((n_samples, 3), dtype=np.float32)
    for i in range(n_samples):
        img, label, target = synthetic_example_from_index(i, config)
        X[i] = np.clip(img, 0, 255).astype(np.uint8)
        yc[i] = int(label)
        yr[i] = target.astype(np.float32)
        if verbose and (i + 1) % 1000 == 0:
            print(f"[image_cache] Precomputadas {i + 1}/{n_samples} sintéticas")

    if paths:
        np.save(paths[0], X)
        np.save(paths[1], yc)
        np.save(paths[2], yr)
    return X, yc, yr
