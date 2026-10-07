#!/usr/bin/env python3
"""Figura de cierre: el pipeline DQ de dos puertas y su cobertura medida.

**Gate A** es la capa 1 del framework —controles deterministas y estadísticos
clásicos: 3σ, TRIM, rangos, calendario, duplicados—. **Gate B** es la capa 2:
controles por representación (precio, canal, pares, vintage) más la capa de IA
(CNN 1D y XGBoost como combinador). La disciplina es *barato antes que caro*: una
serie solo llega a Gate B si Gate A no la ha resuelto, y Gate B solo se justifica
donde añade cobertura a presupuesto de falsas alarmas común.

**Aviso de nomenclatura.** Esta figura usa A/B para las **dos capas del gate de
calidad de dato**. No debe confundirse con el «Gate 1 · Calidad de dato / Gate 2 ·
Detección de canal» de `docs/figuras/sistema_productivo_cnn_gate_capital.svg`,
que son dos etapas **consecutivas del producto**: todo lo de esta figura vive
dentro de aquel Gate 1.

El panel inferior es el contenido real: qué control caza qué familia de defecto,
a presupuesto de falsas alarmas común bajo el gate conforme. Es una **matriz de
coberturas complementarias con huecos declarados**, no un ranking: ninguna
representación domina y varias familias solo las ve una.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

GATE_A = ("retorno_3sigma",)
GATE_B = ("retorno_cross_asset", "retorno_cnn",
          "precio_reticula",
          "canal_coherencia", "canal_oscilacion", "canal_ruptura", "canal_geometria",
          "vintage_discrepancia")

ETIQUETAS = {
    "retorno_3sigma": "3σ  (retorno)",
    "retorno_cross_asset": "cross-asset 1−R²  (retorno)",
    "retorno_cnn": "CNN 1D  (retorno) ·IA",
    "precio_reticula": "retícula  (precio)",
    "canal_coherencia": "coherencia banda  (canal)",
    "canal_oscilacion": "déficit oscilación  (canal)",
    "canal_ruptura": "ruptura banda  (canal)",
    "canal_geometria": "cambio geometría  (canal)",
    "vintage_discrepancia": "discrepancia  (vintage)",
}

FAMILIAS = ("stale", "reversible_jump", "decoupling", "lag1_calendar",
            "weekly_ffill", "source_switch", "quantize")
FAM_CORTO = {"stale": "stale", "reversible_jump": "salto\nreversible",
             "decoupling": "desacople", "lag1_calendar": "desfase\n1 sesión",
             "weekly_ffill": "fuente\nsemanal", "source_switch": "cambio\nfuente",
             "quantize": "pérdida\nprecisión"}


def _box(ax, x, y, w, h, text, face, edge, fontsize=9, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                linewidth=1.4, facecolor=face, edgecolor=edge))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, weight=weight, linespacing=1.45)


def _arrow(ax, x0, y0, x1, y1):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                                 mutation_scale=16, linewidth=1.5,
                                 color="#444444", shrinkA=2, shrinkB=2))


def schematic(ax, fpr_a: float, fpr_b: float) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    mid = 0.56          # eje vertical común de todas las cajas y flechas
    boxes = (
        (0.005, 0.120, "Feeds\n+ metadatos\n+ snapshots\nde procedencia",
         "#EEEEEE", "#999999", 8.5, 0.34),
        (0.150, 0.120, "Contrato de serie\n\nunidad · tick\ncalendario · fuente",
         "#EEEEEE", "#999999", 8.5, 0.34),
        (0.295, 0.180, "GATE A · capa 1\ndeterminista y estadística\n\n"
         "3σ · TRIM (≥20 ceros)\nrangos · positividad\nduplicados · calendario\n\n"
         f"FPR medida {fpr_a:.3f}", "#F2E2D2", "#937860", 8.8, 0.56),
        (0.510, 0.270, "GATE B · capa 2\npor representación + IA\n\n"
         "precio → retícula\nretorno → cross-asset · CNN ·IA\n"
         "canal → banda · oscilación\nvintage → recibido vs almacenado\n\n"
         "XGBoost = combinador ·IA, no un detector más\n\n"
         f"FPR medida {fpr_b:.3f}", "#DCEAD9", "#55A868", 8.8, 0.70),
        (0.805, 0.190, "Alerta trazable al Risk Director\n\n"
         "serie · tramo · controles activados\nevidencia · score calibrado\n\n"
         "revisión humana\nNO corrección automática",
         "#DCE4F2", "#4C72B0", 8.5, 0.52),
    )
    for x, w, text, face, edge, fs, h in boxes:
        _box(ax, x, mid - h / 2, w, h, text, face, edge, fs)

    for x0, x1 in ((0.125, 0.150), (0.270, 0.295), (0.475, 0.510), (0.780, 0.805)):
        _arrow(ax, x0, mid, x1, mid)

    # Las dos notas van FUERA del rango [0,1] del eje para no pisar las cajas;
    # el texto de matplotlib no se recorta salvo que se pida clip explícito.
    ax.text(0.4925, 0.02, "barato antes que caro: solo pasa a Gate B lo que Gate A no resuelve",
            ha="center", va="bottom", fontsize=8, style="italic", color="#666666")
    ax.text(0.5, 1.14,
            "Gate A y Gate B son las dos capas del control de CALIDAD DE DATO. No confundir "
            "con el «Gate 1 · DQ / Gate 2 · Detección de canal» del diagrama de producto:\n"
            "todo lo de esta figura vive dentro de aquel Gate 1.   ·IA marca las piezas de "
            "machine / deep learning.",
            ha="center", va="bottom", fontsize=7.5, color="#555555")


def heatmaps(ax_r, ax_f, singles: dict, chance: float) -> None:
    for ax, mode, title in ((ax_r, "restated", "defecto que REESCRIBE historia publicada"),
                            (ax_f, "fresh", "defecto que llega con el DATO NUEVO")):
        order = list(GATE_A) + list(GATE_B)
        matrix = np.array([[singles[c][f"{fam}|{mode}"] for fam in FAMILIAS]
                           for c in order])
        sns.heatmap(matrix, ax=ax, vmin=0, vmax=1, cmap="YlGnBu",
                    annot=True, fmt=".2f", annot_kws={"fontsize": 7.5},
                    cbar=False, linewidths=0.6, linecolor="white",
                    xticklabels=[FAM_CORTO[f] for f in FAMILIAS],
                    yticklabels=[ETIQUETAS[c] for c in order])
        ax.set_title(f"{title}\n(recall; sombreado claro ≈ azar {chance:.2f}; "
                     "etiqueta marrón = Gate A, verde = Gate B)", fontsize=9)
        ax.tick_params(axis="x", labelsize=7.5, rotation=0)
        ax.tick_params(axis="y", labelsize=7.5, rotation=0)
        ax.axhline(len(GATE_A), color="#C44E52", linewidth=2.2)
        # La pertenencia a Gate A / Gate B se marca coloreando la etiqueta, no
        # con un rótulo al margen: ahí chocaba con los nombres de los controles.
        for tick, control in zip(ax.get_yticklabels(), order):
            tick.set_color("#937860" if control in GATE_A else "#3A7D52")
            tick.set_weight("bold" if control in GATE_A else "normal")


def run(stack_summary: Path, figure_path: Path) -> dict:
    if not stack_summary.exists():
        raise FileNotFoundError(
            f"Falta {stack_summary}; ejecuta antes dq_representation_stack.py")
    data = json.loads(stack_summary.read_text(encoding="utf-8"))
    singles = data["single_controls_conformal_aci"]
    subsets = data["gate_subsets_conformal_aci"]
    n_test = data["protocol"]["n_windows"]["test"]
    chance = np.floor(data["protocol"]["target_false_positive_rate"] * n_test) / n_test

    sns.set_theme(style="white", context="notebook")
    fig = plt.figure(figsize=(14, 12.5))
    gs = fig.add_gridspec(2, 2, height_ratios=[0.78, 1.6], hspace=0.14, wspace=0.40)
    schematic(fig.add_subplot(gs[0, :]),
              subsets["solo_3sigma"]["false_positive_rate"],
              subsets["con_cnn"]["false_positive_rate"])
    heatmaps(fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1]), singles, chance)

    fig.suptitle("Pipeline DQ de dos puertas y cobertura medida por control y familia",
                 fontsize=14, weight="bold", y=0.975)
    fig.text(0.5, 0.012,
             f"Inyecciones sintéticas, {n_test} ventanas de test solapadas al 75 %, "
             "gate conforme-adaptativo a presupuesto común. Resultado PROVISIONAL "
             "pendiente de challenge. Ninguna representación domina:\nvarias familias "
             "las ve un solo control, y en `fresh` la cobertura cae para todos — "
             "vintage es ciego ahí por construcción, no por falta de potencia.",
             ha="center", fontsize=8, color="#555555")

    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=150, bbox_inches="tight")
    fig.savefig(figure_path.with_suffix(".pdf"), format="pdf", bbox_inches="tight")
    plt.close(fig)
    return {"png": str(figure_path), "pdf": str(figure_path.with_suffix(".pdf"))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-summary", type=Path,
                        default=ROOT / "results" / "reports" / "dq_representation_stack" / "summary.json")
    parser.add_argument("--figure", type=Path,
                        default=ROOT / "docs" / "figuras" / "dq_pipeline_gate_a_b.png")
    args = parser.parse_args()
    out = run(args.stack_summary, args.figure)
    print(f"  figura PNG -> {out['png']}")
    print(f"  figura PDF -> {out['pdf']}")


if __name__ == "__main__":
    main()
