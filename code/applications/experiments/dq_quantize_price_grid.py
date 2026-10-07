#!/usr/bin/env python3
"""¿El hueco de `quantize` es de representación o de método?

En `dq_conformal_gate` la pérdida de precisión quedó como el único defecto que
**ningún** detector caza (CNN 0,060; `1-R²` 0,055; 3σ 0,032; vol-ratio 0,056,
todos en el azar de 0,056). Pero allí la inyección se aplicaba sobre **retornos ya
normalizados**, donde la rejilla se difumina. Un feed que trunca decimales actúa
sobre **precios**.

Este experimento rehace la familia de forma fiel:

  1. La truncación se aplica a los **precios crudos** del tramo de la ventana.
  2. Retornos y normalización causal se **recalculan** sobre la serie corrompida,
     de modo que la huella del defecto se propaga como en producción.
  3. Se añade un **control de rejilla** que mira los precios, no los retornos:
     busca el paso de malla más grande compatible con la ventana. Brent cotiza
     nativamente en pasos de 0,01, así que una truncación a 0,5 es visible.

Si el control de rejilla lo caza, el hueco era de **representación**: la capa de
DQ no puede mirar solo retornos normalizados. Si tampoco lo caza, el defecto es
genuinamente difícil y la fila se mantiene como negativo.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

#: Escalera de pasos candidatos, en dólares. El primero es el tick nativo de la
#: serie; los siguientes son truncaciones progresivamente más groseras.
GRID_LADDER = (0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 1.00, 2.00, 5.00)

#: Pasos a los que se trunca la serie objetivo al inyectar el defecto.
INJECTED_STEPS = (0.10, 0.25, 0.50, 1.00)


def _load_base():
    path = Path(__file__).resolve().parent / "dq_cnn1d_supervised.py"
    spec = importlib.util.spec_from_file_location("dq_cnn1d_supervised", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()
ASSETS = base.ASSETS
WINDOW = base.WINDOW
WINDOW_STRIDE = base.WINDOW_STRIDE
FIT_END = base.FIT_END
VAL_END = base.VAL_END
FP_TARGET = base.FP_TARGET

gate_path = Path(__file__).resolve().parent / "dq_conformal_gate.py"
_gspec = importlib.util.spec_from_file_location("dq_conformal_gate", gate_path)
gate = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(gate)


def read_prices(panel_path: Path) -> tuple[np.ndarray, pd.DatetimeIndex]:
    frame = pd.read_csv(panel_path, parse_dates=["date"])
    frame = frame[["date", *ASSETS]].dropna().reset_index(drop=True)
    return (frame[list(ASSETS)].to_numpy(dtype=float),
            pd.DatetimeIndex(frame["date"]))


def normalize(prices: np.ndarray) -> np.ndarray:
    """Replica exactamente la tubería de `dq_cnn1d_supervised.load_windows`.

    Retornos logarítmicos salvo WTI (diferencias en dólares, para preservar su
    settlement negativo real de 2020), y normalización causal con media y
    desviación móviles de 60 sesiones desplazadas una.
    """
    log_cols = [i for i, a in enumerate(ASSETS) if a != "WTI"]
    returns = np.empty((len(prices) - 1, len(ASSETS)), dtype=float)
    returns[:, log_cols] = np.diff(np.log(prices[:, log_cols]), axis=0)
    wti = ASSETS.index("WTI")
    returns[:, wti] = np.diff(prices[:, wti])
    scaled = np.full_like(returns, np.nan)
    for j in range(returns.shape[1]):
        history = pd.Series(returns[:, j])
        mean = history.rolling(60, min_periods=20).mean().shift(1).to_numpy()
        sigma = history.rolling(60, min_periods=20).std().shift(1).to_numpy()
        ok = np.isfinite(mean) & np.isfinite(sigma) & (sigma > 1e-10)
        scaled[ok, j] = (returns[ok, j] - mean[ok]) / sigma[ok]
    return scaled


def window_bounds(scaled: np.ndarray, window: int = WINDOW,
                  stride: int = WINDOW_STRIDE) -> list[tuple[int, int]]:
    """Índices (inicio, fin) sobre el array de retornos de las ventanas válidas."""
    return [(stop - window, stop)
            for stop in range(window, len(scaled) + 1, stride)
            if np.isfinite(scaled[stop - window:stop]).all()]


def grid_step_score(price_windows: np.ndarray) -> np.ndarray:
    """Control de rejilla: paso de malla más grande compatible con la ventana.

    Devuelve el paso en dólares, así que un valor alto indica truncación. Opera
    sobre **precios**, que es justamente lo que los otros cuatro detectores no ven.

    Solo mira la **serie objetivo** (columna 0). Mezclar los pares arruina el
    control: cada serie del panel tiene su propia precisión nativa y el residuo
    conjunto queda dominado por la más fina, de modo que ninguna malla encaja.
    """
    target = price_windows[:, :, 0] if price_windows.ndim == 3 else price_windows
    scores = np.zeros(len(target), dtype=float)
    for i, prices in enumerate(target):
        tolerance = 1e-6 * max(1.0, float(np.max(np.abs(prices))))
        best = 0.0
        for step in GRID_LADDER:
            if np.max(np.abs(prices - step * np.round(prices / step))) <= tolerance:
                best = step
        scores[i] = best
    return scores


def quantize_prices(prices: np.ndarray, lo: int, hi: int, step: float) -> np.ndarray:
    """Trunca la serie objetivo a una rejilla de `step` en el tramo [lo, hi).

    Fuera del tramo la serie queda intacta: el defecto arranca en una fecha, como
    haría un cambio de configuración del feed.
    """
    out = prices.copy()
    out[lo:hi, 0] = step * np.round(out[lo:hi, 0] / step)
    return out


def build(panel_path: Path, seeds: tuple[int, ...] = gate.SEEDS) -> dict:
    prices, dates = read_prices(panel_path)
    clean_scaled = normalize(prices)
    return_dates = dates[1:]
    bounds = window_bounds(clean_scaled)

    starts = pd.DatetimeIndex([return_dates[a] for a, _ in bounds])
    ends = pd.DatetimeIndex([return_dates[b - 1] for _, b in bounds])
    is_train = ends <= FIT_END
    is_val = (starts > FIT_END) & (ends <= VAL_END)
    is_test = starts > VAL_END

    clean_z = np.asarray([clean_scaled[a:b] for a, b in bounds], dtype=np.float32)
    # Los precios de la ventana son los que generan sus retornos: [a, b] inclusive.
    clean_p = np.asarray([prices[a:b + 1] for a, b in bounds], dtype=float)

    train_z, val_z = clean_z[is_train], clean_z[is_val]
    test_z, test_p = clean_z[is_test], clean_p[is_test]
    test_bounds = [bd for bd, keep in zip(bounds, is_test) if keep]

    # Inyección fiel: truncar precios y RECALCULAR retornos y normalización.
    injected_z: dict[float, np.ndarray] = {}
    injected_p: dict[float, np.ndarray] = {}
    for step in INJECTED_STEPS:
        zs, ps = [], []
        for a, b in test_bounds:
            corrupted = quantize_prices(prices, a, b + 1, step)
            zs.append(normalize(corrupted)[a:b])
            ps.append(corrupted[a:b + 1])
        injected_z[step] = np.asarray(zs, dtype=np.float32)
        injected_p[step] = np.asarray(ps, dtype=float)

    return {
        "train_z": train_z, "val_z": val_z, "test_z": test_z, "test_p": test_p,
        "injected_z": injected_z, "injected_p": injected_p,
        "n": {"train": int(is_train.sum()), "validation": int(is_val.sum()),
              "test": int(is_test.sum())},
        "test_start": str(starts[is_test][0].date()),
        "seeds": list(seeds),
    }


def run(panel_path: Path, output_dir: Path, seeds: tuple[int, ...] = gate.SEEDS) -> dict:
    data = build(panel_path, seeds)
    train_z, val_z, test_z = data["train_z"], data["val_z"], data["test_z"]

    # El control de rejilla no se entrena: una sola evaluación basta.
    price_results = {}
    for step, inj_p in data["injected_p"].items():
        price_results[f"{step:.2f}"] = gate.matched_fpr_recall(
            grid_step_score, data["test_p"], inj_p, FP_TARGET)

    # Los cuatro detectores del arnés original, sobre la MISMA inyección fiel.
    z_results: dict[str, dict[str, list[float]]] = {}
    for seed in seeds:
        cnn = base.fit_cnn(train_z, val_z, seed=seed)
        detectors = {
            "cnn_1d": lambda x, m=cnn: base.score_cnn(m, x),
            "cross_asset_1_minus_r2": base.score_cross_asset,
            "3sigma_vol_normalizada": base.score_3sigma,
            "vol_ratio_vs_pares": gate.volatility_ratio_score,
        }
        for name, scorer in detectors.items():
            for step, inj_z in data["injected_z"].items():
                z_results.setdefault(name, {}).setdefault(f"{step:.2f}", []).append(
                    gate.matched_fpr_recall(scorer, test_z, inj_z, FP_TARGET))

    output = {
        "protocol": {
            "source": str(panel_path),
            "question": "el hueco de `quantize` en dq_conformal_gate, ¿es de representación o de método?",
            "injection": "truncación de los PRECIOS crudos del tramo de la ventana; retornos y normalización causal recalculados sobre la serie corrompida",
            "previous_injection": "en dq_conformal_gate se redondeaba el retorno YA normalizado, lo que difumina la rejilla",
            "grid_ladder_usd": list(GRID_LADDER),
            "injected_steps_usd": list(INJECTED_STEPS),
            "native_tick_usd": 0.01,
            "target_false_positive_rate": FP_TARGET,
            "n_windows": data["n"],
            "test_start": data["test_start"],
            "seeds": data["seeds"],
        },
        "recall_grid_control_on_prices": price_results,
        "recall_window_detectors_on_recomputed_returns": {
            name: {step: {"mean": float(np.mean(v)), "std": float(np.std(v))}
                   for step, v in steps.items()}
            for name, steps in z_results.items()
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_quantize_price_grid")
    args = parser.parse_args()
    result = run(args.panel, args.output)

    steps = [f"{s:.2f}" for s in INJECTED_STEPS]
    print(f"\nRecall a FPR emparejada ({FP_TARGET:.0%}); azar ~{FP_TARGET:.3f}. "
          f"Truncación del precio a paso (tick nativo 0,01 $):")
    header = f"  {'detector':26s} " + " ".join(f"{'$' + s:>9s}" for s in steps)
    print(header)
    grid = result["recall_grid_control_on_prices"]
    print(f"  {'grid_control (PRECIOS)':26s} " + " ".join(f"{grid[s]:9.3f}" for s in steps))
    for name, by_step in result["recall_window_detectors_on_recomputed_returns"].items():
        print(f"  {name:26s} " + " ".join(f"{by_step[s]['mean']:9.3f}" for s in steps))
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
