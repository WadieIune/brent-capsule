#!/usr/bin/env python3
"""Separa DISCRIMINACIÓN de CALIBRACIÓN en el banco de controles DQ.

Medir las dos cosas en el mismo número es lo que llevaba a concluir que la IA no
aportaba. Son preguntas distintas y aquí se responden por separado:

1. **Discriminación** — ¿ve el control el defecto? Se mide a FPR **idéntica**,
   imponiendo el 5 % sobre las puntuaciones limpias de test. Es un **oráculo**:
   no es desplegable y no debe presentarse como rendimiento operativo. Sirve para
   atribuir mérito, no para prometer nada.
2. **Calibración** — ¿conserva el control su presupuesto de falsas alarmas al
   cambiar de periodo? Se mide con umbral congelado en validación y, como
   alternativa desplegable, con recalibración rodante sobre el flujo **observado**
   (sin etiquetas, a diferencia del gate adaptativo que se retiró por usar el
   conocimiento de qué ventana era limpia).

Incluye el **leave-one-family-out del combinador**, que es el control capaz de
tumbar su ventaja: se reentrena sin la familia que luego se le mide.

Detalle y lectura: `docs/hallazgos/2026-10-07-A-dq-discriminacion-vs-calibracion.md`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
ALPHA = 0.05
ROLLING_WINDOW = 60
CONTAMINATION = 0.10
SEEDS = (42, 71, 123)


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stack = _load("dq_representation_stack")
pricelab, base, channel = stack.pricelab, stack.base, stack.channel


def rolling_flags(calibration: np.ndarray, observed: np.ndarray,
                  evaluated: np.ndarray, window: int = ROLLING_WINDOW,
                  alpha: float = ALPHA) -> np.ndarray:
    """Umbral = cuantil rodante de los últimos scores OBSERVADOS. Causal.

    Usa solo lo que existe en producción —la puntuación de cada ventana que
    llega—, nunca la etiqueta de si esa ventana estaba limpia. Esa es la
    diferencia con el gate adaptativo retirado, y es lo que lo hace desplegable.
    """
    history = list(calibration)
    flags = np.empty(len(evaluated), dtype=bool)
    for t in range(len(evaluated)):
        flags[t] = evaluated[t] > np.quantile(np.asarray(history[-window:]), 1 - alpha)
        history.append(float(observed[t]))
    return flags


def _blocks(panel: Path):
    prices, _ = pricelab.read_prices(panel)
    scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(scaled)
    data = pricelab.build(panel, SEEDS)
    n_tr, n_va, n_te = (data["n"][k] for k in ("train", "validation", "test"))
    return (prices, scaled, data,
            bounds[n_tr:n_tr + n_va],
            bounds[n_tr + n_va:n_tr + n_va + n_te])


def run(panel: Path, output_dir: Path, seeds=SEEDS) -> dict:
    prices, scaled, data, val_bounds, test_bounds = _blocks(panel)
    families = list(channel.PRICE_FAMILIES)
    modes = ("restated", "fresh")
    keys = [f"{f}|{m}" for f in families for m in modes]

    matched: dict = {}
    frozen: dict = {}
    rolling: dict = {}
    contaminated: dict = {}
    combiner_in: dict = {}
    combiner_out: dict = {}

    for seed in seeds:
        cnn = base.fit_cnn(data["train_z"], data["val_z"], seed=seed)
        rng = np.random.default_rng(seed)
        val = stack.build_block(prices, val_bounds, scaled, cnn, families, modes, rng)
        test = stack.build_block(prices, test_bounds, scaled, cnn, families, modes, rng)

        for j, name in enumerate(stack.FEATURES):
            cal, clean = val["clean"][:, j], test["clean"][:, j]
            oracle = np.quantile(clean, 1 - ALPHA)
            frozen_thr = np.quantile(cal, 1 - ALPHA)

            frozen.setdefault(name, {}).setdefault("fpr", []).append(
                float(np.mean(clean > frozen_thr)))
            rolling.setdefault(name, {}).setdefault("fpr", []).append(
                float(np.mean(rolling_flags(cal, clean, clean))))
            # Flujo de calibración con defectos mezclados: en producción no se
            # recalibra sobre datos garantizados limpios.
            dirty = clean.copy()
            idx = rng.choice(len(dirty), max(1, int(CONTAMINATION * len(dirty))),
                             replace=False)
            dirty[idx] = test[keys[0]][idx, j]
            contaminated.setdefault(name, {}).setdefault("fpr", []).append(
                float(np.mean(rolling_flags(cal, dirty, clean))))

            for key in keys:
                evaluated = test[key][:, j]
                matched.setdefault(name, {}).setdefault(key, []).append(
                    float(np.mean(evaluated > oracle)))
                frozen[name].setdefault(key, []).append(
                    float(np.mean(evaluated > frozen_thr)))
                rolling[name].setdefault(key, []).append(
                    float(np.mean(rolling_flags(cal, clean, evaluated))))

        # --- combinador y su leave-one-family-out ---
        def fit(selected):
            x = np.vstack([val["clean"]] + [val[k] for k in selected])
            y = np.r_[np.zeros(len(val["clean"])),
                      np.ones(len(selected) * len(val["clean"]))]
            return stack._combiner(seed).fit(x, y)

        full = fit(keys)
        score = full.predict_proba(test["clean"])[:, 1]
        threshold = np.quantile(score, 1 - ALPHA)
        for key in keys:
            combiner_in.setdefault(key, []).append(
                float(np.mean(full.predict_proba(test[key])[:, 1] > threshold)))
        for held in families:
            partial = fit([k for k in keys if not k.startswith(f"{held}|")])
            partial_clean = partial.predict_proba(test["clean"])[:, 1]
            partial_thr = np.quantile(partial_clean, 1 - ALPHA)
            for mode in modes:
                key = f"{held}|{mode}"
                combiner_out.setdefault(key, []).append(float(np.mean(
                    partial.predict_proba(test[key])[:, 1] > partial_thr)))

    mean = lambda values: float(np.mean(values))
    summarize = lambda block: {
        name: {k: mean(v) for k, v in entry.items()} for name, entry in block.items()}
    chance = int(ALPHA * len(test_bounds)) / len(test_bounds)

    output = {
        "protocol": {
            "source": str(panel), "seeds": list(seeds),
            "target_false_positive_rate": ALPHA,
            "approx_chance_recall": chance,
            "rolling_window": ROLLING_WINDOW,
            "contamination_tested": CONTAMINATION,
            "matched_protocol": "ORÁCULO: umbral = cuantil (1-alpha) del limpio de TEST. "
                                "Aísla discriminación; NO es desplegable ni es rendimiento operativo.",
            "frozen_protocol": "umbral congelado en validación; es el protocolo desplegable de referencia",
            "rolling_protocol": "cuantil rodante sobre el flujo OBSERVADO, sin etiquetas; desplegable",
            "n_windows": data["n"], "families": families, "modes": list(modes),
        },
        "discriminacion_fpr_identica": summarize(matched),
        "calibracion_umbral_congelado": summarize(frozen),
        "calibracion_rodante": summarize(rolling),
        "calibracion_rodante_contaminada": summarize(contaminated),
        "combinador_dentro_de_distribucion": {k: mean(v) for k, v in combiner_in.items()},
        "combinador_leave_one_family_out": {k: mean(v) for k, v in combiner_out.items()},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_discrimination_vs_calibration")
    args = parser.parse_args()
    r = run(args.panel, args.output)
    keys = [f"{f}|{m}" for f in r["protocol"]["families"] for m in r["protocol"]["modes"]]
    avg = lambda d: float(np.mean([d[k] for k in keys]))

    print(f"\n1 · DISCRIMINACIÓN a FPR idéntica {ALPHA:.0%} (oráculo; azar "
          f"{r['protocol']['approx_chance_recall']:.3f})")
    print(f"  {'control':24s} {'recall medio':>12s} {'peor familia':>13s}")
    disc = r["discriminacion_fpr_identica"]
    for name in sorted(disc, key=lambda n: -avg(disc[n])):
        v = [disc[name][k] for k in keys]
        print(f"  {name:24s} {np.mean(v):12.3f} {min(v):13.3f}")
    print(f"  {'combinador_xgboost':24s} {avg(r['combinador_dentro_de_distribucion']):12.3f}"
          f" {min(r['combinador_dentro_de_distribucion'].values()):13.3f}")
    print(f"  {'  └ leave-one-family-out':24s} {avg(r['combinador_leave_one_family_out']):12.3f}"
          f" {min(r['combinador_leave_one_family_out'].values()):13.3f}")

    print(f"\n2 · CALIBRACIÓN: FPR fuera de muestra (objetivo nominal {ALPHA:.0%})")
    print(f"  {'control':24s} {'congelado':>10s} {'rodante':>9s} {'rodante+contam.':>16s}")
    for name in stack.FEATURES:
        print(f"  {name:24s} {r['calibracion_umbral_congelado'][name]['fpr']:10.3f}"
              f" {r['calibracion_rodante'][name]['fpr']:9.3f}"
              f" {r['calibracion_rodante_contaminada'][name]['fpr']:16.3f}")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
