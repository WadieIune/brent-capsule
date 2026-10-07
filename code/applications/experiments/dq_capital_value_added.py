#!/usr/bin/env python3
"""Error de capital EVITADO por cada capa del banco de controles.

Enlaza la línea de detección (`dq_representation_stack`) con la de capital
(`dq_capital_impact`, C7). C7 estableció que consumir dato sucio mueve el capital
`k · VaR`; aquella medición comparaba panel crudo contra panel depurado. Aquí se
responde la pregunta siguiente, que es la del objetivo del paper:

    De ese error de capital, ¿**cuánto evita** cada capa de control, y cuánto
    añade específicamente la capa de IA sobre los controles estadísticos?

Métrica. Para cada familia de defecto se corrompe un episodio de la serie
objetivo, se recalcula el capital de una **cartera estándar** y se obtiene el
error que ese defecto introduciría si pasara el gate:

    error_residual(gate) = media_familias [ (1 - recall_gate(familia)) x |Δcapital(familia)| ]

Un gate que detecta la familia hace que el episodio se sanee y se recalcule, así
que su error no llega al capital; lo que no detecta, pasa. La diferencia entre
`error_residual` de dos gates anidados es el **valor añadido** del que los
separa. Los gates de `GATE_SUBSETS` están anidados a propósito: `solo_3sigma` ⊂
`sin_ia` ⊂ `con_cnn`, de modo que la última diferencia **es** la aportación del
deep learning, aislada.

Alcance, deliberadamente superficial (instrucción del MASTER). Cartera estándar
equiponderada sobre los cinco activos del panel, VaR histórico y `k · VaR` con el
multiplicador del semáforo de Basilea reutilizado de `portfolio_var`. Una cartera
de CIB tiene muchas más capas —correlaciones entre factores, diversificación
entre mesas, específico y default, PLA por mesa, NMRF, suelo SA— y ninguna está
aquí. Las cifras van en **base 100** de notional y no son una estimación del
impacto real: lo que se compara entre gates es la **proporción de error evitado**,
que es robusta a la escala, no el nivel absoluto.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
_APP = str(Path(__file__).resolve().parents[1])
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from experiments.portfolio_var import basel_multiplier  # noqa: E402


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pricelab = _load("dq_quantize_price_grid")
channel = _load("dq_channel_representation")
stack = _load("dq_representation_stack")

BASE = 100.0          # notional en base 100
ALPHA = 0.99          # nivel del VaR
VAR_WINDOW = 250      # ventana del VaR histórico
EPISODES = 40         # posiciones del episodio corrupto, para promediar
SEED = 20261007


def portfolio_capital(prices: np.ndarray, lo: int, hi: int) -> float:
    """Capital `k · VaR` en base 100 de una cartera estándar equiponderada.

    Mismo esquema que `dq_capital_impact`: VaR histórico rodante y multiplicador
    del semáforo de Basilea según excepciones por 250 días, de modo que las
    excepciones de backtesting también consumen capital.
    """
    # WTI liquidó a -37,63 USD el 2020-04-20: el logaritmo no está definido ahí.
    # Se aplica la misma convención que `dq_capital_impact.sanitize`, que excluye
    # precios no positivos en lugar de recortarlos o imputarlos.
    usable = prices.copy()
    usable[usable <= 0] = np.nan
    weights = np.full(usable.shape[1], 1.0 / usable.shape[1])
    with np.errstate(invalid="ignore"):
        returns = np.diff(np.log(usable), axis=0) @ weights
    var = np.full(len(returns), np.nan)
    for t in range(VAR_WINDOW, len(returns)):
        var[t] = -float(np.quantile(returns[t - VAR_WINDOW:t], 1.0 - ALPHA))
    window = slice(max(lo, VAR_WINDOW), hi)
    r, v = returns[window], var[window]
    keep = ~np.isnan(v) & ~np.isnan(r)
    r, v = r[keep], v[keep]
    if len(r) < 100:
        raise ValueError("tramo insuficiente para evaluar capital")
    if not (np.isfinite(r).all() and np.isfinite(v).all()):
        raise ValueError("quedan no-finitos en el tramo evaluado")
    exceptions_250 = float((r < -v).sum()) * (250.0 / len(r))
    k, _ = basel_multiplier(exceptions_250)
    return float(k * np.mean(v) * BASE)


def capital_errors(panel_path: Path) -> dict[str, float]:
    """|Δcapital| en base 100 que introduciría cada familia si pasara el gate."""
    prices, _ = pricelab.read_prices(panel_path)
    scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(scaled)
    data = pricelab.build(panel_path, stack.SEEDS)
    n_tr, n_va, n_te = (data["n"]["train"], data["n"]["validation"], data["n"]["test"])
    test_bounds = bounds[n_tr + n_va:n_tr + n_va + n_te]
    lo, hi = test_bounds[0][0], test_bounds[-1][1]

    clean = portfolio_capital(prices, lo, hi)
    rng = np.random.default_rng(SEED)
    episodes = [test_bounds[i] for i in
                np.linspace(0, len(test_bounds) - 1, EPISODES).astype(int)]

    out = {"__clean__": clean}
    for family in channel.PRICE_FAMILIES:
        for mode in ("restated", "fresh"):
            deltas = []
            for a, b in episodes:
                corrupted, _ = stack._inject(prices, a, b, family, mode, rng)
                deltas.append(abs(portfolio_capital(corrupted, lo, hi) - clean))
            out[f"{family}|{mode}"] = float(np.mean(deltas))
    return out


def run(panel_path: Path, stack_summary: Path, output_dir: Path) -> dict:
    if not stack_summary.exists():
        raise FileNotFoundError(
            f"Falta {stack_summary}. Ejecuta antes dq_representation_stack.py: "
            "los recalls por familia salen de ahí y no se re-estiman aquí.")
    detection = json.loads(stack_summary.read_text(encoding="utf-8"))
    errors = capital_errors(panel_path)
    clean = errors.pop("__clean__")
    keys = sorted(errors)
    total = float(np.mean([errors[k] for k in keys]))

    gates = {"sin_control": {k: 0.0 for k in keys}}
    gates.update({name: block for name, block
                  in detection["gate_subsets_conformal_aci"].items()})
    gates["combinador_xgboost"] = detection["combiner_conformal_aci"]

    rows = []
    for name, recalls in gates.items():
        residual = float(np.mean([(1.0 - recalls.get(k, 0.0)) * errors[k] for k in keys]))
        rows.append({
            "gate": name,
            "fpr_realizada": round(recalls.get("false_positive_rate", 0.0), 4),
            "error_capital_residual_base100": round(residual, 4),
            "error_residual_pct_del_capital_limpio": round(100.0 * residual / clean, 3),
            "error_evitado_pct": round(100.0 * (total - residual) / total, 1),
        })

    # Desglose por control individual. Recall alto no implica valor: un control
    # perfecto en una familia que no mueve capital no evita error. Esto separa
    # "detecta bien" de "evita error de capital", que no es lo mismo.
    per_control = []
    for name, recalls in detection["single_controls_conformal_aci"].items():
        residual = float(np.mean([(1.0 - recalls.get(k, 0.0)) * errors[k] for k in keys]))
        per_control.append({
            "control": name,
            "recall_medio": round(float(np.mean([recalls[k] for k in keys])), 3),
            "error_evitado_pct": round(100.0 * (total - residual) / total, 1),
        })
    per_control.sort(key=lambda r: -r["error_evitado_pct"])

    by_name = {r["gate"]: r for r in rows}
    value_added = {
        "banco_de_controles_sobre_3sigma_pp": round(
            by_name["sin_ia"]["error_evitado_pct"]
            - by_name["solo_3sigma"]["error_evitado_pct"], 1),
        "cnn_sobre_el_banco_pp": round(
            by_name["con_cnn"]["error_evitado_pct"]
            - by_name["sin_ia"]["error_evitado_pct"], 1),
        "combinador_sobre_el_banco_pp": round(
            by_name["combinador_xgboost"]["error_evitado_pct"]
            - by_name["con_cnn"]["error_evitado_pct"], 1),
    }

    output = {
        "aviso": ("Análisis superficial con cartera estándar equiponderada. Las "
                  "cifras en base 100 NO estiman el impacto real de capital; lo "
                  "comparable entre gates es la PROPORCIÓN de error evitado."),
        "enlace": {
            "deteccion": str(stack_summary),
            "capital": "esquema k*VaR de dq_capital_impact (C7), multiplicador de portfolio_var",
        },
        "fuera_del_alcance": [
            "correlaciones entre factores y diversificación entre mesas",
            "riesgo específico y de default",
            "P&L attribution por mesa y NMRF",
            "suelo del método estándar",
        ],
        "protocolo": {
            "cartera": "equiponderada sobre los cinco activos del panel",
            "var": f"histórico {ALPHA:.0%}, ventana {VAR_WINDOW} sesiones",
            "capital": "k * VaR con k del semáforo de Basilea",
            "episodios_por_familia": EPISODES,
            "metrica": "error_residual = media_f [(1 - recall_gate(f)) * |delta capital(f)|]",
            "gates_anidados": "solo_3sigma ⊂ sin_ia ⊂ con_cnn; la diferencia aísla cada capa",
        },
        "capital_cartera_limpia_base100": round(clean, 4),
        "error_capital_sin_ningun_control_base100": round(total, 4),
        "delta_capital_por_familia_base100": {k: round(errors[k], 4) for k in keys},
        "gates": rows,
        "por_control_individual": per_control,
        "valor_anadido": value_added,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--stack-summary", type=Path,
                        default=ROOT / "results" / "reports" / "dq_representation_stack" / "summary.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_capital_value_added")
    args = parser.parse_args()
    r = run(args.panel, args.stack_summary, args.output)

    print("\nERROR DE CAPITAL EVITADO POR CADA CAPA — cartera estándar, base 100.")
    print("Análisis superficial; la proporción evitada es lo comparable, no el nivel.\n")
    print(f"  Capital de la cartera limpia: {r['capital_cartera_limpia_base100']:.2f}")
    print(f"  Error de capital si no hay control alguno: "
          f"{r['error_capital_sin_ningun_control_base100']:.3f}\n")
    print(f"  {'gate':22s} {'FPR':>6s} {'error residual':>15s} {'evitado':>9s}")
    for row in r["gates"]:
        print(f"  {row['gate']:22s} {row['fpr_realizada']:6.3f} "
              f"{row['error_capital_residual_base100']:15.3f} "
              f"{row['error_evitado_pct']:8.1f}%")
    print(f"\n  {'control individual':24s} {'recall medio':>13s} {'evitado':>9s}")
    for row in r["por_control_individual"]:
        print(f"  {row['control']:24s} {row['recall_medio']:13.3f} "
              f"{row['error_evitado_pct']:8.1f}%")
    print("\n  Valor añadido de cada capa (puntos porcentuales de error evitado):")
    for k, v in r["valor_anadido"].items():
        print(f"    {k:38s} {v:+6.1f} pp")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
