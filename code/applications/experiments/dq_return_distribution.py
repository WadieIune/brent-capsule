#!/usr/bin/env python3
"""La distribución de rendimientos, no el capital: por qué 3σ está mal calibrado.

Sustituye el encuadre de `dq_capital_value_added`, que expresaba el valor del
banco de controles como «porcentaje de error de capital evitado». Aquel número
era engañoso: el error total sobre el capital era del **0,63 %**, de modo que
«evitar el 84,8 %» era el 84,8 % de una cantidad diminuta y se leía como si fuese
una fracción del capital. Aquí no se dan cifras de capital (ver `DISCLAIMER`).

El encuadre correcto es la **distribución de rendimientos**:

  1. Un control 3σ es implícitamente un supuesto de **normalidad**: bajo una
     normal, |z| > 3 ocurre el 0,27 % de las veces. La distribución de los
     activos es **leptocúrtica**, así que ese umbral no significa lo que se cree.
  2. Por tanto 3σ **no puede separar** una cola real de mercado de un defecto de
     dato: ambas cosas le parecen «imposibles». Ese es el argumento de fondo del
     framework por representaciones.
  3. Un gate **conforme** se calibra sobre la distribución empírica en vez de
     sobre una forma supuesta. Esa es la vía para alcanzar el presupuesto de
     falsas alarmas, pero la garantía NO es incondicional: depende de la
     dependencia entre ventanas, del drift y del tamaño de calibración.

**Alcance tras el challenge** de
`docs/auditorias/2026-10-07-A-challenge-dq-return-distribution.md`: este módulo
entrega solo el **diagnóstico descriptivo** (paneles A-D de la figura y las
métricas de forma). La comparación de gates por «distorsión corregida» se
degradó a proyección no validada —multiplicaba agregados no pareados y suponía
corrección perfecta—, así que se calcula pero se publica marcada como tal, bajo
`proyeccion_no_validada`, y **no** aparece en la figura ni debe citarse.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import seaborn as sns  # noqa: E402
from scipy import stats  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

DISCLAIMER = (
    "No se reportan cifras de capital. El capital por modelo interno sería "
    "k·VaR con k del semáforo de Basilea, y una traducción honesta exigiría la "
    "cartera real, correlaciones entre factores, diversificación entre mesas, "
    "riesgo específico y de default, PLA por mesa, NMRF y suelo SA. Con una "
    "cartera de juguete esas cifras salen infladas o irrelevantes, así que este "
    "experimento se queda en la distribución de rendimientos, que es donde el "
    "efecto es directamente observable y comparable entre controles."
)


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pricelab = _load("dq_quantize_price_grid")
channel = _load("dq_channel_representation")
stack = _load("dq_representation_stack")

SIGMA_LEVELS = (1, 2, 3, 4, 5)
EPISODES = 40
SEED = 20261007


def standardized_returns(prices: np.ndarray, column: int = 0) -> np.ndarray:
    r = np.diff(np.log(prices[:, column]))
    return (r - r.mean()) / r.std(ddof=1)


def tail_table(z: np.ndarray) -> list[dict]:
    """Frecuencia observada de |z| > k frente a la que predice una normal."""
    rows = []
    for k in SIGMA_LEVELS:
        empirical = float(np.mean(np.abs(z) > k))
        normal = float(2 * stats.norm.sf(k))
        rows.append({
            "umbral_sigmas": k,
            "frecuencia_normal": normal,
            "frecuencia_empirica": empirical,
            "veces_mas_frecuente": round(empirical / normal, 1) if normal > 0 else None,
        })
    return rows


def shape_stats(z: np.ndarray) -> dict:
    return {
        "curtosis_exceso": float(stats.kurtosis(z)),
        "asimetria": float(stats.skew(z)),
        "cuantil_99": float(np.quantile(z, 0.99)),
        "cuantil_01": float(np.quantile(z, 0.01)),
    }


def shape_distortion(clean: np.ndarray, dirty: np.ndarray) -> float:
    """Distorsión de la forma de la distribución: distancia de Wasserstein.

    Se prefiere a |Δcurtosis| porque la curtosis la domina un puñado de
    observaciones y es inestable; la distancia de Wasserstein usa la
    distribución entera y está en unidades de sigma, que son interpretables.
    """
    return float(stats.wasserstein_distance(clean, dirty))


def kurtosis_sensitivity(z: np.ndarray) -> list[dict]:
    """La curtosis la dominan unos pocos días; conviene declararlo."""
    order = np.argsort(-np.abs(z))
    return [{"excluidos": n,
             "curtosis_exceso": round(float(stats.kurtosis(np.delete(z, order[:n]))), 1)}
            for n in (0, 1, 3, 10)]


def figure(z: np.ndarray, tails: list[dict], gates: list[dict], path: Path) -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    grid = np.linspace(-8, 8, 600)

    ax = axes[0, 0]
    sns.histplot(z, bins=260, stat="density", color="#4C72B0", alpha=0.55,
                 edgecolor=None, ax=ax, label="Brent, empírica")
    ax.plot(grid, stats.norm.pdf(grid), color="#C44E52", lw=2,
            label="Normal ajustada")
    ax.set_yscale("log")
    ax.set_xlim(-8, 8)
    ax.set_ylim(1e-5, 1)
    ax.set_title("A · Distribución de rendimientos (escala log)\n"
                 "las colas empíricas sobresalen muy por encima de la normal")
    ax.set_xlabel("rendimiento estandarizado (sigmas)")
    ax.legend()

    ax = axes[0, 1]
    theoretical = stats.norm.ppf((np.arange(len(z)) + 0.5) / len(z))
    ax.scatter(theoretical, np.sort(z), s=6, color="#4C72B0", alpha=0.5)
    lim = [-6, 6]
    ax.plot(lim, lim, color="#C44E52", lw=2, label="normalidad perfecta")
    ax.set_xlim(lim)
    ax.set_title("B · QQ frente a la normal\n"
                 "la curva se despega en ambas colas: no es normal")
    ax.set_xlabel("cuantiles normales")
    ax.set_ylabel("cuantiles observados")
    ax.legend()

    ax = axes[1, 0]
    ks = [r["umbral_sigmas"] for r in tails]
    width = 0.38
    ax.bar([k - width / 2 for k in ks], [r["frecuencia_normal"] for r in tails],
           width, label="predice la normal", color="#C44E52")
    ax.bar([k + width / 2 for k in ks], [r["frecuencia_empirica"] for r in tails],
           width, label="ocurre de verdad", color="#4C72B0")
    ax.set_yscale("log")
    ax.set_xticks(ks)
    ax.set_xticklabels([f"{k}σ" for k in ks])
    for row in tails:
        if row["umbral_sigmas"] >= 3:
            ax.annotate(f"×{row['veces_mas_frecuente']:.0f}",
                        (row["umbral_sigmas"] + width / 2, row["frecuencia_empirica"]),
                        textcoords="offset points", xytext=(0, 5),
                        ha="center", fontsize=9, color="#4C72B0", weight="bold")
    ax.set_title("C · Frecuencia de superar k sigmas\n"
                 "menos masa en los hombros (1-2σ) y mucha más en las colas (3σ+)")
    ax.set_ylabel("frecuencia")
    ax.legend()

    # Panel D: el de comparación de gates se retiró tras el challenge de
    # `docs/auditorias/2026-10-07-A-challenge-dq-return-distribution.md`, porque
    # multiplicaba agregados no pareados. Se sustituye por un diagnóstico
    # puramente descriptivo y sin proyección: de cuántos días depende la cola.
    ax = axes[1, 1]
    sens = kurtosis_sensitivity(z)
    excluded = [r["excluidos"] for r in sens]
    values = [r["curtosis_exceso"] for r in sens]
    sns.barplot(x=[str(e) for e in excluded], y=values, color="#4C72B0", ax=ax)
    for i, v in enumerate(values):
        ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
    ax.set_title("D · De cuántos días depende la cola\n"
                 "curtosis tras excluir los N días más extremos (todos reales)")
    ax.set_xlabel("días extremos excluidos")
    ax.set_ylabel("curtosis de exceso")
    ax.set_ylim(0, max(values) * 1.18)

    fig.suptitle("Calidad de dato y forma de la distribución de rendimientos — "
                 "Brent, 2007-2026", fontsize=13, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(panel_path: Path, stack_summary: Path, output_dir: Path,
        figure_path: Path) -> dict:
    if not stack_summary.exists():
        raise FileNotFoundError(
            f"Falta {stack_summary}; ejecuta antes dq_representation_stack.py")
    detection = json.loads(stack_summary.read_text(encoding="utf-8"))

    prices, _ = pricelab.read_prices(panel_path)
    scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(scaled)
    data = pricelab.build(panel_path, stack.SEEDS)
    n_tr, n_va, n_te = (data["n"]["train"], data["n"]["validation"], data["n"]["test"])
    test_bounds = bounds[n_tr + n_va:n_tr + n_va + n_te]
    lo, hi = test_bounds[0][0], test_bounds[-1][1]

    z_full = standardized_returns(prices)
    clean_window = standardized_returns(prices[lo:hi + 1])

    rng = np.random.default_rng(SEED)
    episodes = [test_bounds[i] for i in
                np.linspace(0, len(test_bounds) - 1, EPISODES).astype(int)]
    distortion = {}
    for family in channel.PRICE_FAMILIES:
        for mode in ("restated", "fresh"):
            values = []
            for a, b in episodes:
                corrupted, _ = stack._inject(prices, a, b, family, mode, rng)
                values.append(shape_distortion(
                    clean_window, standardized_returns(corrupted[lo:hi + 1])))
            distortion[f"{family}|{mode}"] = float(np.mean(values))

    keys = sorted(distortion)
    total = float(np.mean([distortion[k] for k in keys]))
    gate_recalls = {"sin_control": {k: 0.0 for k in keys}}
    gate_recalls.update(detection["gate_subsets_conformal_aci"])
    gate_recalls["combinador_xgboost"] = detection["combiner_conformal_aci"]

    gates = []
    for name, recalls in gate_recalls.items():
        residual = float(np.mean([(1.0 - recalls.get(k, 0.0)) * distortion[k]
                                  for k in keys]))
        gates.append({
            "gate": name,
            "fpr_realizada": round(recalls.get("false_positive_rate", 0.0), 4),
            "distorsion_residual": round(residual, 5),
            "distorsion_corregida_pct": round(100.0 * (total - residual) / total, 1),
        })

    tails = tail_table(z_full)
    figure(z_full, tails, gates, figure_path)

    by = {g["gate"]: g for g in gates}
    output = {
        "disclaimer_capital": DISCLAIMER,
        "por_que_este_encuadre": (
            "Un control 3σ es un supuesto de normalidad encubierto. Si la "
            "distribución es leptocúrtica, el umbral no significa lo que se cree "
            "y el control no puede separar una cola real de mercado de un "
            "defecto de dato."
        ),
        "forma_de_la_distribucion": shape_stats(z_full),
        "curtosis_sensibilidad": kurtosis_sensitivity(z_full),
        "nota_curtosis": (
            "La curtosis la dominan unos pocos días de abril de 2020, que son "
            "movimientos REALES de mercado, no defectos. Al excluirlos sigue "
            "siendo fuertemente leptocúrtica, así que la conclusión no depende "
            "de ellos — pero conviene declarar la sensibilidad."
        ),
        "colas_normal_vs_empirica": tails,
        "distorsion_por_familia": {k: round(distortion[k], 5) for k in keys},
        "escala_absoluta": {
            "distorsion_total_sin_control_sigmas": round(total, 5),
            "aviso": (
                "La distorsión total sin control es de "
                f"{total:.4f} sigmas, o sea ~{100 * total:.1f} % de una "
                "desviación típica. Los porcentajes de 'distorsión corregida' "
                "son fracciones de ESA cantidad pequeña, no de la distribución. "
                "Es el mismo cuidado que obligó a retirar las cifras de capital: "
                "un porcentaje alto sobre una base diminuta se lee inflado. Lo "
                "que estos porcentajes permiten es ORDENAR gates entre sí, no "
                "afirmar magnitud de impacto."
            ),
            "por_que_es_pequena": (
                "Cada defecto se inyecta en un episodio de 20 sesiones dentro de "
                "una ventana de test de ~670, así que su huella sobre la "
                "distribución completa es necesariamente limitada. Lo relevante "
                "es la comparación entre gates sobre la misma base."
            ),
        },
        "proyeccion_no_validada": {
            "aviso": (
                "NO CITAR. Proyección bajo corrección perfecta, no una mejora "
                "medida. Degradada por el challenge de 2026-10-07: multiplica "
                "agregados NO pareados (la distorsión se promedia sobre 40 "
                "episodios con un RNG y el recall sobre 124 ventanas con otro), "
                "supone que detectar equivale a corregir sin error, compara "
                "gates a FPR distintas y usa estandarización con look-ahead. "
                "Para reabrirlo hace falta test temporal no solapado, "
                "prevalencia prefijada, las MISMAS inyecciones en ambos lados, "
                "FPR emparejada con incertidumbre y una política de corrección "
                "explícita con su error residual."
            ),
            "gates": gates,
            "diferencias_pp": {
            "banco_sobre_3sigma_pp": round(
                by["sin_ia"]["distorsion_corregida_pct"]
                - by["solo_3sigma"]["distorsion_corregida_pct"], 1),
            "cnn_sobre_el_banco_pp": round(
                by["con_cnn"]["distorsion_corregida_pct"]
                - by["sin_ia"]["distorsion_corregida_pct"], 1),
            "combinador_sobre_el_banco_pp": round(
                by["combinador_xgboost"]["distorsion_corregida_pct"]
                - by["con_cnn"]["distorsion_corregida_pct"], 1),
            },
        },
        "figura": str(figure_path),
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
                        default=ROOT / "results" / "reports" / "dq_return_distribution")
    parser.add_argument("--figure", type=Path,
                        default=ROOT / "docs" / "figuras" / "dq_distribucion_rendimientos.png")
    args = parser.parse_args()
    r = run(args.panel, args.stack_summary, args.output, args.figure)

    s = r["forma_de_la_distribucion"]
    print("\nFORMA DE LA DISTRIBUCION DE RENDIMIENTOS — Brent")
    print(f"  curtosis de exceso {s['curtosis_exceso']:.1f} (normal = 0), "
          f"asimetria {s['asimetria']:.2f}")
    print("  sensibilidad de la curtosis a los dias mas extremos:")
    for row in r["curtosis_sensibilidad"]:
        print(f"    excluidos {row['excluidos']:2d} dias -> {row['curtosis_exceso']:6.1f}")
    print(f"\n  {'umbral':>7s} {'predice la normal':>18s} {'ocurre':>10s} {'ratio':>8s}")
    for row in r["colas_normal_vs_empirica"]:
        ratio = row["veces_mas_frecuente"]
        print(f"  {row['umbral_sigmas']:6d}σ {row['frecuencia_normal']:18.4%} "
              f"{row['frecuencia_empirica']:10.4%} {ratio:7.1f}x")

    print("\nComparacion de gates: DEGRADADA a proyeccion no validada por el")
    print("challenge del 2026-10-07; se guarda en el JSON bajo")
    print("'proyeccion_no_validada' y NO debe citarse. Motivo principal: multiplica")
    print("agregados no pareados y supone correccion perfecta tras cada alerta.")
    print(f"\n  figura -> {args.figure}")
    print(f"  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
