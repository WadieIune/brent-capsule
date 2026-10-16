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
#: Ventana de recalibración, en número de puntuaciones consecutivas. Ampliarla de
#: 60 a 236 baja la suma de tasas individuales de 0,282 a 0,129, pero **no** deja
#: el share por control dentro de la resolución: ver `effective_sample_size`.
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


def effective_sample_size(window: int = ROLLING_WINDOW) -> int:
    """Puntuaciones INDEPENDIENTES dentro de una ventana de recalibración.

    Las ventanas de análisis son de `WINDOW` sesiones con paso `WINDOW_STRIDE`,
    así que dos puntuaciones consecutivas comparten el 75 % de sus datos. Contar
    las 236 como si fuesen independientes sobreestima la resolución por un factor
    de 4: solo hay una de cada cuatro en fase no solapada.

    Es la corrección del punto 3 del challenge de B
    (`docs/auditorias/2026-10-16-B-challenge-dq-calibracion-por-clase.md`). Y
    sigue siendo optimista: ignora la dependencia serial del propio mercado.
    """
    fases = pricelab.WINDOW // pricelab.WINDOW_STRIDE
    return max(1, window // fases)


def minimum_resolvable_alpha(n_statistical: int, window: int = ROLLING_WINDOW) -> float:
    """Presupuesto conjunto más pequeño que la muestra puede representar.

    Por debajo de este α la petición no es representable: el umbral por control
    cae en el máximo empírico y el gate entrega su suelo, dé igual lo que se pida.
    """
    return n_statistical / effective_sample_size(window)


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
               evaluated: np.ndarray, features: tuple[str, ...],
               alpha: float = ALPHA) -> np.ndarray:
    """Unión de los controles, cada uno calibrado según su clase.

    El presupuesto `alpha` se reparte solo entre los estadísticos: los
    deterministas no gastan falsas alarmas, así que incluirlos en el reparto solo
    serviría para exigirle a la muestra de calibración una resolución que no tiene.
    """
    statistical = [n for n in features if CONTROL_CLASS[n] == "estadistico"]
    share = alpha / len(statistical)
    fired = np.zeros(len(evaluated), dtype=bool)
    for j, name in enumerate(features):
        if CONTROL_CLASS[name] == "determinista":
            fired |= semantic_flags(calibration[:, j], evaluated[:, j], name)
        else:
            fired |= rolling_flags(calibration[:, j], observed[:, j],
                                   evaluated[:, j], alpha=share)
    return fired


#: Objetivos nominales que se barren para construir la curva de operación. El
#: nominal NO se cumple fuera de muestra —ese es el resultado—, así que lo que se
#: publica es la FPR REALIZADA frente al recall, para que el consumidor del gate
#: dimensione su capacidad de revisión sobre un número medido y no prometido.
NOMINAL_SWEEP = (0.005, 0.01, 0.02, 0.05, 0.10)


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
    bloques: dict = {}
    for seed in seeds:
        cnn = base.fit_cnn(data["train_z"], data["val_z"], seed=seed)
        rng = np.random.default_rng(seed)
        val = stack.build_block(prices, val_bounds, scaled, cnn, families, modes, rng)
        test = stack.build_block(prices, test_bounds, scaled, cnn, families, modes, rng)
        cal, clean = val["clean"], test["clean"]
        bloques[seed] = (cal, clean, test)

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

    # --- curva de operación: FPR realizada frente a recall, por nominal ---
    curva = []
    for nominal in NOMINAL_SWEEP:
        fpr_s, rec_s = [], []
        for seed, (cal, clean, test) in bloques.items():
            flags = lambda ev: gate_flags(cal, clean, ev, stack.FEATURES, alpha=nominal)
            fpr_s.append(float(np.mean(flags(clean))))
            rec_s.append(float(np.mean([np.mean(flags(test[k])) for k in keys])))
        curva.append({
            "alpha_nominal": nominal,
            "fpr_realizada_media": float(np.mean(fpr_s)),
            "fpr_realizada_std": float(np.std(fpr_s)),
            "recall_medio": float(np.mean(rec_s)),
            "factor_de_exceso": float(np.mean(fpr_s) / nominal),
        })

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
        "curva_de_operacion": curva,
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
    print("\n  CURVA DE OPERACIÓN · el nominal no se cumple; dimensiona sobre la columna")
    print("  de FPR REALIZADA, que es la carga de revisión que vas a tener de verdad.\n")
    print(f"  {'alpha nominal':>14s} {'FPR realizada':>16s} {'exceso':>8s} {'recall medio':>13s}")
    for row in r["curva_de_operacion"]:
        print(f"  {row['alpha_nominal']:14.3f} "
              f"{row['fpr_realizada_media']:11.3f} ±{row['fpr_realizada_std']:.3f} "
              f"{row['factor_de_exceso']:7.1f}x {row['recall_medio']:13.3f}")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
