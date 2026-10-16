#!/usr/bin/env python3
"""Gate operativo con calibración rodante POR CLASE DE CONTROL.

El gate anterior aplicaba un único esquema de calibración a los nueve controles
y se descalibraba fuera de muestra: 0,774 de falsas alarmas sobre un objetivo
nominal del 5 %. El diagnóstico de
`docs/hallazgos/2026-10-07-A-dq-discriminacion-vs-calibracion.md` identificó dos
causas, y las dos se corrigen aquí.

**1 · Hay dos clases de control y no admiten la misma calibración.**

- *Estadísticos* (3σ, cross-asset, CNN, los de canal): su puntuación limpia es
  continua, hay una cola que estimar y se calibran por **cuantil rodante** sobre
  el flujo observado. Sin etiquetas: solo entra la puntuación de cada ventana que
  llega, así que es desplegable.
- *Deterministas* (vintage, retícula): su puntuación limpia es **constante** —la
  discrepancia con el snapshot es cero, la retícula es el tick nativo— y no hay
  cola que estimar. El umbral correcto es **semántico**: cualquier valor distinto
  del nominal es una alerta. Estimarles un cuantil es un error de categoría, y
  medido: la recalibración rodante le sube la FPR a vintage de 0,000 a 0,129.

**2 · El presupuesto de falsas alarmas solo lo reparten quienes lo gastan.**

Repartir α entre los nueve controles pedía estimar cuantiles de 0,0056 con 59
ventanas de calibración, tres veces más fino que la resolución de la muestra: el
umbral colapsaba al máximo empírico. Como los deterministas no consumen
presupuesto —su FPR limpia es cero por construcción—, α se reparte **solo entre
los estadísticos**, lo que relaja la exigencia sobre la muestra.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
ALPHA = 0.05
#: La ventana debe poder resolver el share por control: con 7 estadísticos el
#: share es 0,00714 y una ventana de 60 solo resuelve 1/60 = 0,0167, tres veces
#: más grueso. Medido, pasar de 60 a 236 baja la suma de FPR individuales de
#: 0,282 a 0,129. Lo que queda por encima del nominal ya es deriva, no resolución.
ROLLING_WINDOW = 236
SEEDS = (42, 71, 123)

#: La clase se declara a mano, por conocimiento del control, y se **verifica**
#: contra los datos en `assert_degenerate`. Detectarla automáticamente invitaría
#: a clasificar mal un control estadístico que por azar parezca degenerado.
CONTROL_CLASS = {
    "canal_coherencia": "estadistico",
    "canal_ruptura": "estadistico",
    "canal_geometria": "estadistico",
    "canal_oscilacion": "estadistico",
    "retorno_cnn": "estadistico",
    "retorno_cross_asset": "estadistico",
    "retorno_3sigma": "estadistico",
    "precio_reticula": "determinista",
    "vintage_discrepancia": "determinista",
}

#: Holgura relativa sobre el valor nominal de un control determinista. Absorbe
#: ruido numérico sin admitir una desviación real: la discrepancia de vintage
#: limpia es ~1e-14 y la inyectada del orden de 1e-2.
TOLERANCE = 1e-6


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stack = _load("dq_representation_stack")
pricelab, base, channel = stack.pricelab, stack.base, stack.channel


def assert_degenerate(scores: np.ndarray, name: str) -> float:
    """Comprueba que un control declarado determinista lo es, y da su nominal.

    Si su puntuación limpia tuviera dispersión real, tratarlo como semántico
    produciría falsas alarmas silenciosas. Mejor romper que calibrar mal.
    """
    nominal = float(np.median(scores))
    spread = float(np.max(scores) - np.min(scores))
    scale = max(abs(nominal), 1e-12)
    if spread > TOLERANCE * max(scale, 1.0):
        raise ValueError(
            f"{name} está declarado determinista pero su puntuación limpia varía "
            f"(rango {spread:.3g} sobre nominal {nominal:.3g}). Reclasifícalo como "
            "estadístico o revisa el control.")
    return nominal


def semantic_flags(calibration: np.ndarray, evaluated: np.ndarray,
                   name: str) -> np.ndarray:
    """Alerta si el valor se aparta del nominal observado en calibración."""
    nominal = assert_degenerate(calibration, name)
    return evaluated > nominal * (1.0 + TOLERANCE) + TOLERANCE


def rolling_flags(calibration: np.ndarray, observed: np.ndarray,
                  evaluated: np.ndarray, alpha: float = ALPHA,
                  window: int = ROLLING_WINDOW) -> np.ndarray:
    """Cuantil rodante sobre el flujo observado. Causal y sin etiquetas."""
    history = list(calibration)
    flags = np.empty(len(evaluated), dtype=bool)
    for t in range(len(evaluated)):
        flags[t] = evaluated[t] > np.quantile(np.asarray(history[-window:]), 1 - alpha)
        history.append(float(observed[t]))
    return flags


def gate_flags(calibration: np.ndarray, observed: np.ndarray,
               evaluated: np.ndarray, features: tuple[str, ...]) -> np.ndarray:
    """Unión de los controles, cada uno calibrado según su clase.

    El presupuesto `ALPHA` se reparte solo entre los estadísticos: los
    deterministas no gastan falsas alarmas, así que incluirlos en el reparto solo
    serviría para exigirle a la muestra de calibración una resolución que no tiene.
    """
    statistical = [n for n in features if CONTROL_CLASS[n] == "estadistico"]
    share = ALPHA / len(statistical)
    fired = np.zeros(len(evaluated), dtype=bool)
    for j, name in enumerate(features):
        if CONTROL_CLASS[name] == "determinista":
            fired |= semantic_flags(calibration[:, j], evaluated[:, j], name)
        else:
            fired |= rolling_flags(calibration[:, j], observed[:, j],
                                   evaluated[:, j], alpha=share)
    return fired


def run(panel: Path, output_dir: Path, seeds=SEEDS) -> dict:
    prices, _ = pricelab.read_prices(panel)
    scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(scaled)
    data = pricelab.build(panel, seeds)
    n_tr, n_va, n_te = (data["n"][k] for k in ("train", "validation", "test"))
    val_bounds = bounds[n_tr:n_tr + n_va]
    test_bounds = bounds[n_tr + n_va:n_tr + n_va + n_te]
    families = list(channel.PRICE_FAMILIES)
    modes = ("restated", "fresh")
    keys = [f"{f}|{m}" for f in families for m in modes]

    por_clase: dict = {}
    congelado: dict = {}
    for seed in seeds:
        cnn = base.fit_cnn(data["train_z"], data["val_z"], seed=seed)
        rng = np.random.default_rng(seed)
        val = stack.build_block(prices, val_bounds, scaled, cnn, families, modes, rng)
        test = stack.build_block(prices, test_bounds, scaled, cnn, families, modes, rng)
        cal, clean = val["clean"], test["clean"]

        por_clase.setdefault("false_positive_rate", []).append(
            float(np.mean(gate_flags(cal, clean, clean, stack.FEATURES))))
        # Referencia: el esquema anterior, un único cuantil congelado para todos
        # y el presupuesto repartido entre los nueve.
        share = ALPHA / len(stack.FEATURES)
        frozen_thr = np.quantile(cal, 1 - share, axis=0)
        congelado.setdefault("false_positive_rate", []).append(
            float(np.mean((clean > frozen_thr).any(axis=1))))
        for key in keys:
            por_clase.setdefault(key, []).append(
                float(np.mean(gate_flags(cal, clean, test[key], stack.FEATURES))))
            congelado.setdefault(key, []).append(
                float(np.mean((test[key] > frozen_thr).any(axis=1))))

    mean = lambda d: {k: float(np.mean(v)) for k, v in d.items()}
    output = {
        "protocol": {
            "source": str(panel), "seeds": list(seeds),
            "target_false_positive_rate": ALPHA,
            "rolling_window": ROLLING_WINDOW,
            "control_class": CONTROL_CLASS,
            "statistical_share": ALPHA / sum(
                1 for c in CONTROL_CLASS.values() if c == "estadistico"),
            "rationale": "los deterministas no consumen presupuesto de falsas alarmas, "
                         "así que alpha se reparte solo entre los estadísticos",
            "n_windows": data["n"], "families": families, "modes": list(modes),
        },
        "gate_por_clase_rodante": mean(por_clase),
        "gate_umbral_congelado_uniforme": mean(congelado),
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
                        default=ROOT / "results" / "reports" / "dq_rolling_gate")
    args = parser.parse_args()
    r = run(args.panel, args.output)
    keys = [f"{f}|{m}" for f in r["protocol"]["families"] for m in r["protocol"]["modes"]]
    a, b = r["gate_umbral_congelado_uniforme"], r["gate_por_clase_rodante"]
    avg = lambda d: float(np.mean([d[k] for k in keys]))

    print(f"\nGATE OPERATIVO · objetivo nominal de falsas alarmas {ALPHA:.0%}\n")
    print(f"  {'protocolo':34s} {'FPR OOS':>9s} {'recall medio':>13s} {'peor':>8s}")
    for nombre, d in (("umbral congelado, uniforme", a),
                      ("rodante por clase de control", b)):
        v = [d[k] for k in keys]
        print(f"  {nombre:34s} {d['false_positive_rate']:9.3f} "
              f"{np.mean(v):13.3f} {min(v):8.3f}")
    print(f"\n  {'familia · modo':28s} {'congelado':>10s} {'por clase':>10s}")
    for k in keys:
        print(f"  {k:28s} {a[k]:10.3f} {b[k]:10.3f}")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
