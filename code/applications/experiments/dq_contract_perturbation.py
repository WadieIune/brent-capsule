#!/usr/bin/env python3
"""¿Gastan presupuesto los controles deterministas ante contratos perturbados?

El gate reparte el presupuesto de falsas alarmas **solo entre los controles
estadísticos**, apoyándose en que los deterministas —vintage y retícula— tienen
puntuación limpia constante y por tanto no gastan. B señaló, con razón, que esa
propiedad es **condicional al contrato de la serie, no universal**
(`docs/auditorias/2026-10-16-B-challenge-dq-calibracion-por-clase.md`, punto 5):
un tick mal declarado, un cambio legítimo de convención o una revisión rutinaria
de snapshot sí pueden hacerlos saltar.

Aquí se mide eso. Cada escenario es una **operación legítima del contrato**, no
un defecto de dato, así que **cualquier alerta es una falsa alarma por
construcción** y la tasa observada es directamente la FPR del control.

Si alguno gasta presupuesto de forma apreciable, el reparto de α entre los siete
estadísticos deja de ser correcto y hay que rehacer el gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("dq_rolling_gate")
stack, pricelab = gate.stack, gate.pricelab

DETERMINISTAS = [n for n, c in gate.CONTROL_CLASS.items() if c == "determinista"]


# --------------------------------------------------------------------------
# Perturbaciones de CONTRATO. Ninguna es un defecto: son cambios legítimos que
# el sistema debe tolerar sin alertar.
# --------------------------------------------------------------------------

def tick_ampliado(prices, lo, hi, rng):
    """El mercado amplía el tick de 0,01 a 0,05. Decisión del contrato.

    La serie sigue siendo correcta; lo que cambia es la granularidad declarada.
    """
    out = prices.copy()
    out[lo:hi, 0] = 0.05 * np.round(out[lo:hi, 0] / 0.05)
    return out, prices[lo:hi + 1] if hi < len(prices) else prices[lo:]


def ajuste_corporativo(prices, lo, hi, rng):
    """Reajuste hacia atrás por operación societaria, anunciado y correcto.

    La serie recibida hoy difiere de la almacenada en todo el histórico, pero la
    nueva es la buena. Vintage ve discrepancia donde no hay defecto.
    """
    factor = 1.0 / 4.0
    recibido = prices.copy()
    recibido[:hi, 0] *= factor
    return recibido, prices[lo:hi + 1]


def settlement_tardio(prices, lo, hi, rng):
    """El snapshot se tomó antes del settlement definitivo.

    El cierre final difiere del provisional por un ajuste pequeño y legítimo.
    """
    recibido = prices.copy()
    n = hi - lo
    recibido[lo:hi, 0] *= 1.0 + rng.normal(0, 0.0005, size=n)
    return recibido, prices[lo:hi + 1]


def redenominacion(prices, lo, hi, rng):
    """Cambio de unidad de cotización, por ejemplo de dólares a centavos."""
    out = prices.copy()
    out[lo:hi, 0] *= 100.0
    return out, prices[lo:hi + 1]


ESCENARIOS = {
    "tick ampliado por el mercado": tick_ampliado,
    "ajuste corporativo retroactivo": ajuste_corporativo,
    "settlement tardío": settlement_tardio,
    "redenominación de unidad": redenominacion,
}


def run(panel: Path, output_dir: Path) -> dict:
    prices, _ = pricelab.read_prices(panel)
    scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(scaled)
    data = pricelab.build(panel, gate.SEEDS)
    n_tr, n_va, n_te = (data["n"][k] for k in ("train", "validation", "test"))
    val_bounds = bounds[n_tr:n_tr + n_va]
    test_bounds = bounds[n_tr + n_va:n_tr + n_va + n_te]

    # Nominal de cada control determinista, aprendido en calibración limpia.
    cal_p = np.asarray([prices[a:b + 1] for a, b in val_bounds], dtype=float)
    nominales = {
        "precio_reticula": pricelab.grid_step_score(cal_p),
        "vintage_discrepancia": stack.vintage_discrepancy(cal_p, cal_p),
    }

    rng = np.random.default_rng(20261016)
    resultados: dict[str, dict[str, float]] = {}
    for etiqueta, perturbar in ESCENARIOS.items():
        recibidos, almacenados = [], []
        for a, b in test_bounds:
            recibido, _ = perturbar(prices, a, b + 1, rng)
            recibidos.append(recibido[a:b + 1])
            almacenados.append(prices[a:b + 1])
        recibidos = np.asarray(recibidos, dtype=float)
        almacenados = np.asarray(almacenados, dtype=float)

        scores = {
            "precio_reticula": pricelab.grid_step_score(recibidos),
            "vintage_discrepancia": stack.vintage_discrepancy(recibidos, almacenados),
        }
        resultados[etiqueta] = {
            name: float(np.mean(gate.semantic_flags(nominales[name], scores[name], name)))
            for name in DETERMINISTAS
        }

    peor = max(max(v.values()) for v in resultados.values())
    output = {
        "protocol": {
            "source": str(panel),
            "pregunta": "¿los controles deterministas gastan presupuesto de falsas alarmas "
                        "ante operaciones legítimas del contrato de la serie?",
            "interpretacion": "cada escenario es una operación LEGÍTIMA, no un defecto, "
                              "así que toda alerta es una falsa alarma por construcción",
            "origen": "punto 5 del challenge de B del 2026-10-16",
            "escenarios": list(ESCENARIOS),
            "controles": DETERMINISTAS,
            "n_ventanas_test": len(test_bounds),
            "n_ventanas_calibracion": len(val_bounds),
        },
        "fpr_por_escenario": resultados,
        "peor_fpr_observada": peor,
        "veredicto": (
            "La premisa «los deterministas no consumen presupuesto» NO es universal: "
            f"alcanzan {peor:.3f} de falsas alarmas ante contratos perturbados. El reparto "
            "de alpha solo entre los estadísticos vale mientras el contrato se mantenga, "
            "y exige vigilar el contrato como parte del gate."
            if peor > 0.01 else
            "Los deterministas no gastan presupuesto apreciable ni con contratos perturbados."),
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
                        default=ROOT / "results" / "reports" / "dq_contract_perturbation")
    args = parser.parse_args()
    r = run(args.panel, args.output)

    print("\nFPR DE LOS CONTROLES DETERMINISTAS ANTE CONTRATOS PERTURBADOS")
    print("Cada escenario es una operación LEGÍTIMA: toda alerta es falsa alarma.\n")
    print(f"  {'escenario':34s} " + " ".join(f"{n[:20]:>22s}" for n in DETERMINISTAS))
    for etiqueta, fila in r["fpr_por_escenario"].items():
        print(f"  {etiqueta:34s} " + " ".join(f"{fila[n]:22.3f}" for n in DETERMINISTAS))
    print(f"\n  peor FPR observada: {r['peor_fpr_observada']:.3f}")
    print(f"\n  {r['veredicto']}")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
