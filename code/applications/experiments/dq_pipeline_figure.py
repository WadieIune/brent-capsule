#!/usr/bin/env python3
"""Figura de cierre: el pipeline DQ de dos puertas y su cobertura medida.

**Gate A** es la capa 1 del framework —controles deterministas y estadísticos
clásicos: 3σ, TRIM, rangos, calendario, duplicados—. **Gate B** es la capa 2:
controles por representación (precio, canal, pares, vintage) más la capa de IA
(CNN 1D y XGBoost como combinador). La disciplina es *barato antes que caro*: una
serie solo llega a Gate B si Gate A no la ha resuelto, y Gate B solo se justifica
donde añade cobertura a presupuesto de falsas alarmas común.

**Nomenclatura.** A y B son las dos capas **dentro** del Gate 1 de calidad de
dato. El Gate 2 del diagrama de arquitectura es la detección de canal, que es ya
un modelo de riesgo aguas abajo y se valida con backtest, no con este arnés.

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
            "El Gate 1 de calidad de dato se despliega en dos capas: A, determinista y "
            "estadística, y B, por representación y con IA. Lo que esta figura detalla es el "
            "interior de ese Gate 1;\nla serie que sale de aquí alimenta los modelos de riesgo. "
            "·IA marca las piezas de machine y deep learning.",
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


def encaje(path: Path, subsets: dict, singles: dict) -> None:
    """Arquitectura del sistema: del dato crudo al Risk Director.

    El Gate 1 de calidad de dato se despliega en dos capas, A y B, y entrega una
    serie validada a los modelos de riesgo aguas abajo. Cada modelo aguas abajo
    lleva su propia evidencia de validación, porque el backtest les aplica a
    ellos —miden riesgo— y no al gate de calidad, que mide detección.

    No se reportan cifras de impacto en capital: quedan fuera del alcance de
    esta entrega hasta disponer de posiciones, notional y metodología de cartera
    aprobados.
    """
    sns.set_theme(style="white", context="notebook")
    fig, ax = plt.subplots(figsize=(14, 8.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    top = 0.735
    cadena = (
        (0.010, 0.100, "Dato\ncrudo", "#EEEEEE", "#999999"),
        (0.130, 0.165, "GATE 1\nCalidad de dato\n(capas A y B)", "#F6D9C4", "#C0703A"),
        (0.325, 0.105, "Serie\nvalidada", "#EEEEEE", "#999999"),
        (0.450, 0.165, "GATE 2 · Detección de canal\nCNN EfficientNet\n\n"
         "AUC 0,97 como clasificador\nse usa como contexto de régimen,\nno como señal de trading:\n"
         "la estrategia derivada no pasa\nel backtest (DSR 0,00 · PBO 0,38)",
         "#DCE4F2", "#4C72B0"),
        (0.645, 0.165, "VaR FHS-EWMA\ncondicional a volatilidad\n\n"
         "Kupiec p 0,985 · cobertura correcta\nChristoffersen p 0,128 · sin\nagrupamiento de excepciones\n"
         "Basilea zona verde, k = 3,0\n14 excepciones en 1.393 días",
         "#D6E8D2", "#3A7D52"),
        (0.840, 0.150, "Supervivencia XGB-AFT\nvida del canal\n\n"
         "C-index 0,664 ± 0,007\nwalk-forward purgado\ncon embargo",
         "#D6E8D2", "#3A7D52"),
    )
    for x, w, text, face, edge in cadena:
        _box(ax, x, top - 0.115, w, 0.23, text, face, edge, 7.4)
    for i in range(len(cadena) - 1):
        _arrow(ax, cadena[i][0] + cadena[i][1], top, cadena[i + 1][0], top)

    ax.text(0.5, 0.995, "Arquitectura del sistema: del dato crudo al Risk Director",
            ha="center", va="top", fontsize=12, weight="bold")
    ax.text(0.5, 0.955,
            "El Gate 1 valida la serie y la entrega a los modelos de riesgo. Cada modelo aguas "
            "abajo lleva su propia evidencia de validación, porque el backtest —walk-forward "
            "purgado · DSR · PBO/CSCV · Kupiec · Christoffersen · semáforo de Basilea—\nse aplica "
            "a quien MIDE RIESGO, no al gate de calidad, que mide DETECCIÓN y se valida con "
            "defectos de verdad conocida. Las cifras de impacto en capital quedan fuera de esta entrega.",
            ha="center", va="top", fontsize=8, color="#555555")
    ax.text(0.7275, top - 0.128,
            "El VaR condicional a volatilidad es el que supera el backtest: un VaR histórico "
            "simple sobre la misma serie\nfalla la prueba de independencia (Christoffersen "
            "p 0,0011), porque agrupa las excepciones en los episodios de estrés.",
            ha="center", va="top", fontsize=7.2, style="italic", color="#3A7D52")

    # Despliegue del Gate 1
    ax.plot([0.130, 0.055], [top - 0.115, 0.470], color="#C0703A", lw=1.2, ls=":")
    ax.plot([0.295, 0.945], [top - 0.115, 0.470], color="#C0703A", lw=1.2, ls=":")
    _box(ax, 0.045, 0.040, 0.910, 0.430, "", "#FDFBF8", "#C0703A", 8)
    ax.text(0.500, 0.437, "GATE 1 · CALIDAD DE DATO — dos capas sobre cuatro representaciones",
            ha="center", va="center", fontsize=10, weight="bold", color="#C0703A")

    keys = [f"{f}|{m}" for f in FAMILIAS for m in ("restated", "fresh")]
    media = {n: sum(b[k] for k in keys) / len(keys) for n, b in subsets.items()}
    _box(ax, 0.075, 0.125, 0.385, 0.272,
         "CAPA A · determinista y estadística\n\n"
         "3σ sobre log-rendimientos · TRIM (≥20 ceros)\nrangos · positividad · duplicados · calendario\n\n"
         "Resuelve los defectos de forma cerrada y barata.\n"
         f"Recall medio {media['solo_3sigma']:.2f} · FPR {subsets['solo_3sigma']['false_positive_rate']:.3f}",
         "#F2E2D2", "#937860", 8.4)
    _box(ax, 0.540, 0.125, 0.385, 0.272,
         "CAPA B · por representación, con IA\n\n"
         "precio → retícula del tick\nretorno → cross-asset 1−R² · CNN 1D ·IA\n"
         "canal → banda · oscilación · geometría\nvintage → recibido frente a almacenado\n\n"
         f"Recall medio {media['con_cnn']:.2f} · FPR {subsets['con_cnn']['false_positive_rate']:.3f}",
         "#DCEAD9", "#55A868", 8.4)
    _arrow(ax, 0.460, 0.261, 0.540, 0.261)
    ax.text(0.500, 0.286, "lo no resuelto", ha="center", va="bottom",
            fontsize=7, style="italic", color="#666666")

    mejor_fresh = max(singles, key=lambda c: sum(singles[c][f"{f}|fresh"] for f in FAMILIAS))
    ax.text(0.500, 0.082,
            f"La cobertura conjunta alcanza {media['con_cnn']:.2f} de recall medio frente a "
            f"{media['solo_3sigma']:.2f} del control estándar por sí solo, a carga de alarmas "
            "comparable. Ninguna representación domina:\ncada familia de defecto la cubre bien "
            f"una distinta, y cuando el defecto llega con el dato nuevo el control que más cubre "
            f"es «{mejor_fresh}». Detalle por familia en la figura de cobertura y en el Excel.",
            ha="center", va="center", fontsize=8, color="#444444")

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), format="pdf", bbox_inches="tight")
    plt.close(fig)


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

    encaje_path = figure_path.with_name("dq_encaje_produccion.png")
    encaje(encaje_path, subsets, singles)
    return {"png": str(figure_path), "pdf": str(figure_path.with_suffix(".pdf")),
            "encaje_png": str(encaje_path),
            "encaje_pdf": str(encaje_path.with_suffix(".pdf"))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-summary", type=Path,
                        default=ROOT / "results" / "reports" / "dq_representation_stack" / "summary.json")
    parser.add_argument("--figure", type=Path,
                        default=ROOT / "docs" / "figuras" / "dq_pipeline_gate_a_b.png")
    args = parser.parse_args()
    out = run(args.stack_summary, args.figure)
    for k, v in out.items():
        print(f"  {k:12s} -> {v}")


if __name__ == "__main__":
    main()
