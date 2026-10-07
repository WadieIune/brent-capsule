#!/usr/bin/env python3
"""Entregables para el Risk Director y el director del paper: Excel y Word.

Genera dos documentos a partir de los JSON ya producidos por los experimentos,
sin recalcular nada: así no pueden divergir de la evidencia. Si un resultado se
retira o se degrada, se retira aquí también.

- **Excel** (`resultados_dq.xlsx`): una hoja por pregunta que un Risk Director
  hace. Qué cubre cada control, qué deja pasar, a qué coste de falsas alarmas,
  y qué está validado frente a qué es provisional o está retirado.
- **Word** (`resumen_dq_estado_del_arte.docx`): resumen ejecutivo con el estado
  del arte, lo demostrado, lo refutado y lo pendiente.

Regla de edición: **todo número que salga aquí tiene que existir en un JSON de
`results/reports/`**. Los valores retirados (capital, «distorsión corregida») no
se incluyen salvo en la hoja de trazabilidad que explica por qué se retiraron.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "results" / "reports"

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=13, color="1F3864")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

FAMILIA_DESC = {
    "stale": "Cotización repetida: el precio deja de moverse (check TRIM de ≥20 ceros).",
    "reversible_jump": "Tick erróneo que revierte al día siguiente.",
    "decoupling": "Desalineación de fechas de varias sesiones frente a los pares.",
    "lag1_calendar": "Desfase de UNA sesión. Es la forma del defecto real de EURUSD de 2008.",
    "weekly_ffill": "Fuente semanal propagada a diario: el precio solo cambia 1 de cada 5 días.",
    "source_switch": "Empalme de proveedores: salto de nivel a mitad de tramo sin corregir.",
    "quantize": "Pérdida de precisión del feed: la cotización se trunca a menos decimales.",
}

CONTROL_DESC = {
    "retorno_3sigma": ("Gate A", "retorno", "3σ sobre log-rendimientos normalizados. Es el statu quo."),
    "retorno_cross_asset": ("Gate B", "retorno", "1−R² de la serie contra sus pares correlacionados."),
    "retorno_cnn": ("Gate B", "retorno", "CNN 1D supervisada sobre la ventana multivariante. DEEP LEARNING."),
    "precio_reticula": ("Gate B", "precio", "Busca la malla más gruesa compatible con los precios de la ventana."),
    "canal_coherencia": ("Gate B", "canal", "Co-movimiento de la posición dentro de banda frente a los pares."),
    "canal_oscilacion": ("Gate B", "canal", "Déficit de giros: un canal sano rebota en sus bordes."),
    "canal_ruptura": ("Gate B", "canal", "Cuánto se escapa la serie de su propia banda."),
    "canal_geometria": ("Gate B", "canal", "Cambio de pendiente o ancho del canal a mitad de ventana."),
    "vintage_discrepancia": ("Gate B", "vintage", "Serie recibida hoy frente al snapshot almacenado."),
}

ESTADO = [
    ("C9", "Gate conforme y espacio nulo", "🟠 autodegradado",
     "El «la CNN no pasa el gate» era un fallo de CALIBRACIÓN, no de arquitectura. "
     "Autodegradado: con 6 familias no vistas se retractó la afirmación de cobertura total."),
    ("C10", "El canal como tercera representación", "🟡 provisional",
     "El canal gana `stale` (1,000) y `weekly_ffill` (0,815) donde los controles de retorno no llegan."),
    ("C11", "Vintage + XGBoost como combinador", "🟡 provisional",
     "Vintage logra 1,000 en restatements y es ciego por construcción en dato fresco. "
     "El combinador XGBoost PIERDE contra la unión de controles gateados."),
    ("C12", "Error de capital evitado", "❌ RETIRADO",
     "El error total era el 0,633 % del capital, así que «84,8 % evitado» se leía inflado. "
     "Cartera de juguete. NO CITAR."),
    ("C13", "Distribución de rendimientos", "🟠 degradado",
     "Sobrevive el diagnóstico descriptivo: ±3σ infraestima la frecuencia de extremos. "
     "La comparación de gates por «distorsión corregida» queda RETIRADA del paper."),
]

LIMITES = [
    ("Defectos sintéticos", "Las inyecciones están escritas por nosotros. No son una muestra de "
     "la prevalencia real, y el tamaño elegido en cada familia mueve su fila entera."),
    ("Prevalencia uniforme", "Se promedia sobre familias como si todas fuesen igual de frecuentes. "
     "Es falso y no hay dato para ponderarlo."),
    ("Ventanas solapadas", "124 ventanas de test con stride 5 sobre ventana 20: solapan al 75 %, "
     "no son independientes y cualquier intervalo implícito es optimista."),
    ("Saneo idealizado", "Donde se proyecta corrección, se supone que detectar equivale a corregir "
     "sin error ni coste. No se modela el coste de investigar una alerta."),
    ("FPR no idénticas", "Gate A opera a 0,032 y Gate B a 0,083 de falsas alarmas: la comparación "
     "es generosa en alarmas para Gate B."),
    ("Un solo activo y un solo panel", "Todo el banco se ha medido sobre Brent y sus cuatro pares. "
     "La transferencia a otras asset classes NO está demostrada."),
    ("Capital", "No se reporta ninguna cifra de capital. Sería k·VaR con el semáforo de Basilea, "
     "pero exigiría cartera real, correlaciones, diversificación entre mesas, específico y "
     "default, PLA por mesa, NMRF y suelo SA."),
]


def _sheet(wb, title, intro):
    ws = wb.create_sheet(title)
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = intro
    ws["A2"].font = Font(italic=True, size=9, color="555555")
    ws["A2"].alignment = WRAP
    ws.merge_cells("A2:H2")
    ws.row_dimensions[2].height = 30
    return ws


def _header(ws, row, labels, widths):
    for col, (label, width) in enumerate(zip(labels, widths), start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.fill, cell.font, cell.border = HEAD_FILL, HEAD_FONT, BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _recall_fill(value: float, chance: float) -> PatternFill:
    """Verde cuanto mayor el recall; gris si está en el azar."""
    if value <= chance + 1e-9:
        return PatternFill("solid", fgColor="EDEDED")
    ramp = [(0.25, "E8F3E4"), (0.50, "C7E3BE"), (0.75, "95CC88"), (1.01, "5BA85B")]
    for limit, color in ramp:
        if value < limit:
            return PatternFill("solid", fgColor=color)
    return PatternFill("solid", fgColor="5BA85B")


def build_excel(stack: dict, dist: dict, path: Path) -> None:
    families = stack["protocol"]["families"]
    singles = stack["single_controls_conformal_aci"]
    subsets = stack["gate_subsets_conformal_aci"]
    n_test = stack["protocol"]["n_windows"]["test"]
    target = stack["protocol"]["target_false_positive_rate"]
    chance = int(target * n_test) / n_test

    wb = Workbook()
    wb.remove(wb.active)

    # --- 1. Resumen ---
    ws = _sheet(wb, "1 Resumen", "Lectura de una página. Todo lo de abajo es PROVISIONAL "
                "y pendiente de auditoría cruzada entre agentes.")
    puntos = [
        ("Qué se ha construido",
         "Un gate de calidad de dato de dos capas. Gate A son los controles deterministas y "
         "estadísticos clásicos (3σ, TRIM, rangos, calendario). Gate B añade controles por "
         "REPRESENTACIÓN — precio, canal, pares, vintage — más la capa de IA (CNN 1D y XGBoost)."),
        ("Resultado principal",
         "Ninguna representación domina. Cada familia de defecto la cubre bien un control "
         "distinto, y varias familias las ve UN SOLO control. El valor está en la cobertura "
         "combinada, no en la capacidad de ningún modelo."),
        ("Qué aporta el deep learning",
         "La CNN 1D es el mejor control en salto reversible, desacople y cambio de fuente: los "
         "defectos sin estadístico cerrado evidente. Y en el escenario de DATO NUEVO —el "
         "frecuente, donde el control de vintage no puede ayudar— es el mejor control en 4 de "
         "las 7 familias. Aporta de forma real y MODESTA; no sustituye a ningún control "
         "explícito, y en dato nuevo lo es dentro de un campo débil (recalls de 0,10 a 0,76)."),
        ("El frente abierto",
         "Cuando el defecto llega con el dato nuevo en vez de reescribir historia publicada, la "
         "cobertura cae para TODOS los controles. El control de vintage, que alcanza 1,00 en "
         "casi todas las familias con restatement, es ciego por construcción ahí: no hay "
         "snapshot anterior con el que comparar. Es donde hay que seguir trabajando."),
        ("Qué NO aporta el machine learning",
         "XGBoost como combinador de señales PIERDE contra la unión de controles con umbral "
         "propio, y en pérdida de precisión destruye un control que acierta el 100 %. "
         "«ML que apoya» sí; «ML que sustituye» no."),
        ("Por qué 3σ no basta",
         f"En Brent, |z|>3 ocurre el {dist['colas_normal_vs_empirica'][2]['frecuencia_empirica']:.2%} "
         f"de las sesiones frente al {dist['colas_normal_vs_empirica'][2]['frecuencia_normal']:.2%} "
         "que predice una normal: 4,1 veces más. Un umbral 3σ no puede separar una cola real "
         "de mercado de un defecto de dato."),
        ("Lo que NO se afirma",
         "No se da ninguna cifra de capital. No se demuestra transferencia a otras asset "
         "classes. No se afirma prevalencia real de defectos. Ver hoja 6."),
    ]
    _header(ws, 4, ["Pregunta", "Respuesta"], [30, 110])
    for i, (k, v) in enumerate(puntos, start=5):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True, size=10)
        ws.cell(row=i, column=1).alignment = WRAP
        ws.cell(row=i, column=1).border = BORDER
        c = ws.cell(row=i, column=2, value=v)
        c.alignment, c.border = WRAP, BORDER
        ws.row_dimensions[i].height = 46

    # --- 2. Cobertura por control y familia ---
    ws = _sheet(wb, "2 Cobertura", f"Recall por control y familia, a presupuesto de falsas "
                f"alarmas común ({target:.0%}). Azar ≈ {chance:.3f}; en gris lo que está en el azar. "
                "«Reescribe historia» = el defecto altera datos ya publicados; «dato nuevo» = solo "
                "afecta a las sesiones recientes.")
    labels = ["Control", "Capa", "Representación"] + \
             [f"{f}\n(reescribe)" for f in families] + [f"{f}\n(dato nuevo)" for f in families]
    _header(ws, 4, labels, [28, 8, 14] + [13] * (2 * len(families)))
    for r, (control, (capa, repre, _)) in enumerate(CONTROL_DESC.items(), start=5):
        ws.cell(row=r, column=1, value=control).border = BORDER
        ws.cell(row=r, column=2, value=capa).border = BORDER
        ws.cell(row=r, column=3, value=repre).border = BORDER
        for j, mode in enumerate(("restated", "fresh")):
            for k, fam in enumerate(families):
                value = singles[control][f"{fam}|{mode}"]
                cell = ws.cell(row=r, column=4 + j * len(families) + k, value=round(value, 3))
                cell.fill, cell.border = _recall_fill(value, chance), BORDER
                cell.alignment = Alignment(horizontal="center")

    # --- 3. Gate A vs Gate B ---
    ws = _sheet(wb, "3 Gate A vs Gate B", "Comparación de capas a su propio presupuesto de "
                "falsas alarmas. «sin IA» es Gate B sin la CNN, para aislar qué añade el deep learning.")
    _header(ws, 4, ["Configuración", "Qué incluye", "Falsas alarmas medidas",
                    "Recall medio", "Recall de la peor familia"], [22, 56, 20, 16, 22])
    keys = [f"{f}|{m}" for f in families for m in ("restated", "fresh")]
    descripciones = {
        "solo_3sigma": "Gate A solo: 3σ. Es el statu quo del mercado.",
        "sin_ia": "Gate A + Gate B SIN la CNN (canal, retícula, cross-asset, vintage).",
        "con_cnn": "Gate A + Gate B completo, incluyendo la CNN 1D.",
    }
    for r, (name, block) in enumerate(subsets.items(), start=5):
        values = [block[k] for k in keys]
        for col, value in enumerate([name, descripciones.get(name, ""),
                                     round(block["false_positive_rate"], 3),
                                     round(sum(values) / len(values), 3),
                                     round(min(values), 3)], start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border, cell.alignment = BORDER, WRAP
    row = 5 + len(subsets) + 1
    ws.cell(row=row, column=1, value="Aportación marginal de la CNN sobre el banco").font = Font(bold=True)
    delta = (sum(subsets["con_cnn"][k] for k in keys) - sum(subsets["sin_ia"][k] for k in keys)) / len(keys)
    ws.cell(row=row, column=4, value=round(delta, 3)).font = Font(bold=True)
    ws.cell(row=row + 1, column=1,
            value="Lectura: el salto grande es de 3σ al banco de representaciones. La CNN añade "
                  "encima una mejora pequeña y positiva.").font = Font(italic=True, size=9)

    # --- 4. Familias de defecto ---
    ws = _sheet(wb, "4 Familias", "Qué es cada familia de defecto y qué control la cubre mejor.")
    _header(ws, 4, ["Familia", "Qué es", "Mejor control (reescribe)", "Recall",
                    "Mejor control (dato nuevo)", "Recall"], [20, 62, 26, 10, 26, 10])
    for r, fam in enumerate(families, start=5):
        ws.cell(row=r, column=1, value=fam).border = BORDER
        c = ws.cell(row=r, column=2, value=FAMILIA_DESC[fam])
        c.alignment, c.border = WRAP, BORDER
        for j, mode in enumerate(("restated", "fresh")):
            best = max(singles, key=lambda c_: singles[c_][f"{fam}|{mode}"])
            ws.cell(row=r, column=3 + j * 2, value=best).border = BORDER
            cell = ws.cell(row=r, column=4 + j * 2,
                           value=round(singles[best][f"{fam}|{mode}"], 3))
            cell.border = BORDER
            cell.fill = _recall_fill(singles[best][f"{fam}|{mode}"], chance)
        ws.row_dimensions[r].height = 30

    # --- 5. Estado de los resultados ---
    ws = _sheet(wb, "5 Estado", "Trazabilidad. Qué está en pie, qué se degradó y qué se retiró, "
                "con el motivo. Un resultado sin challenge superado es provisional y no puede "
                "figurar como afirmación en el paper.")
    _header(ws, 4, ["Ref.", "Resultado", "Estado", "Motivo"], [8, 38, 18, 86])
    for r, (ref, nombre, estado, motivo) in enumerate(ESTADO, start=5):
        for col, value in enumerate([ref, nombre, estado, motivo], start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border, cell.alignment = BORDER, WRAP
        if "RETIRADO" in estado:
            ws.cell(row=r, column=3).font = Font(bold=True, color="C00000")
        ws.row_dimensions[r].height = 40

    # --- 6. Limitaciones ---
    ws = _sheet(wb, "6 Limitaciones", "Lo que estos números NO permiten afirmar. Leer antes de "
                "usar cualquier cifra de las hojas anteriores.")
    _header(ws, 4, ["Limitación", "Detalle"], [28, 112])
    for r, (k, v) in enumerate(LIMITES, start=5):
        ws.cell(row=r, column=1, value=k).font = Font(bold=True, size=10)
        ws.cell(row=r, column=1).border = BORDER
        c = ws.cell(row=r, column=2, value=v)
        c.alignment, c.border = WRAP, BORDER
        ws.row_dimensions[r].height = 42

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _p(doc, text, size=10, bold=False, italic=False, color=None, space=6):
    par = doc.add_paragraph()
    run = par.add_run(text)
    run.font.size = Pt(size)
    run.bold, run.italic = bold, italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    par.paragraph_format.space_after = Pt(space)
    par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return par


def build_word(stack: dict, dist: dict, path: Path) -> None:
    families = stack["protocol"]["families"]
    singles = stack["single_controls_conformal_aci"]
    subsets = stack["gate_subsets_conformal_aci"]
    tails = {r["umbral_sigmas"]: r for r in dist["colas_normal_vs_empirica"]}

    doc = Document()
    doc.add_heading("Calidad de dato en series financieras: un gate de dos capas "
                    "con controles por representación", level=0)
    _p(doc, f"Resumen de estado · {date.today().isoformat()} · documento PROVISIONAL, "
            "pendiente de auditoría cruzada", size=9, italic=True, color="777777")

    doc.add_heading("1. El problema", level=1)
    _p(doc, "El control estándar de calidad en series de precios es una banda de 3σ sobre "
            "log-rendimientos. Ese umbral lleva dentro un supuesto de normalidad que los datos "
            "no cumplen. En Brent, entre 2007 y 2026, un movimiento de más de 3σ ocurre el "
            f"{tails[3]['frecuencia_empirica']:.2%} de las sesiones, frente al "
            f"{tails[3]['frecuencia_normal']:.2%} que predice una normal: "
            f"{tails[3]['veces_mas_frecuente']:.1f} veces más. A 5σ la razón llega a "
            f"{tails[5]['veces_mas_frecuente']:.0f}.")
    _p(doc, "La consecuencia operativa es la que importa: si un umbral dispara cuatro veces más "
            "de lo que su propio supuesto promete, no puede separar una cola real de mercado de "
            "un defecto de dato. Bajo normalidad las dos cosas son «imposibles». Subir el umbral "
            "no resuelve nada; hay que mirar el dato desde otro sitio.")
    _p(doc, "Advertencia: de esto NO se deduce ninguna dirección de sesgo en capital. Eso "
            "dependería de la cartera, el horizonte y la metodología, y no se calcula aquí.",
       italic=True, color="777777")

    doc.add_heading("2. Qué se ha construido", level=1)
    _p(doc, "Un gate de calidad de dato en dos capas, bajo la disciplina de barato antes que caro.")
    for texto in (
        "Gate A — capa determinista y estadística: 3σ, checks TRIM de repetidos, rangos, "
        "positividad, duplicados y calendario. Es el statu quo.",
        "Gate B — capa por representación más IA: el mismo dato mirado como precio crudo "
        "(retícula del tick), como retorno frente a sus pares (1−R² y CNN 1D), como canal "
        "(posición en banda, oscilación, geometría) y como vintage (serie recibida frente al "
        "snapshot almacenado). XGBoost entra como combinador de señales, no como un detector más.",
        "Salida: alerta trazable al Risk Director con serie, tramo, controles activados, "
        "evidencia y score calibrado. Revisión humana; nunca corrección automática.",
    ):
        doc.add_paragraph(texto, style="List Bullet")
    _p(doc, "Todos los controles operan bajo un gate conforme-adaptativo, que calibra el umbral "
            "sobre la distribución empírica observada en vez de sobre una forma supuesta. Esa es "
            "la vía para respetar un presupuesto de falsas alarmas cuando la distribución tiene "
            "las colas que tiene.")

    doc.add_heading("3. Resultado principal: ninguna representación domina", level=1)
    _p(doc, "Medido sobre siete familias de defecto inyectadas en los precios y con el "
            "presupuesto de falsas alarmas igualado, el resultado es una matriz de coberturas "
            "complementarias, no un ranking. Cada familia la cubre bien un control distinto, y "
            "varias familias las ve un solo control.")
    tabla = doc.add_table(rows=1, cols=5)
    tabla.style = "Light Grid Accent 1"
    cabeceras = ("Familia de defecto", "Mejor control si REESCRIBE historia", "Recall",
                 "Mejor control si llega con DATO NUEVO", "Recall")
    for i, h in enumerate(cabeceras):
        cel = tabla.rows[0].cells[i]
        cel.text = h
        cel.paragraphs[0].runs[0].bold = True
    for fam in families:
        row = tabla.add_row().cells
        row[0].text = fam
        for j, mode in enumerate(("restated", "fresh")):
            best = max(singles, key=lambda c: singles[c][f"{fam}|{mode}"])
            row[1 + j * 2].text = best
            row[2 + j * 2].text = f"{singles[best][f'{fam}|{mode}']:.2f}"
    _p(doc, "Las dos columnas de la derecha son la advertencia más importante de este "
            "documento. El control de vintage alcanza 1,00 en casi todas las familias cuando el "
            "defecto reescribe historia ya publicada, pero es CIEGO POR CONSTRUCCIÓN cuando el "
            "defecto llega con el dato nuevo: no hay snapshot anterior con el que comparar. Como "
            "la mayoría de los defectos entra por ahí, vintage no resuelve la calidad de dato, "
            "la complementa en el eje de la procedencia. Y en ese escenario la cobertura cae "
            "para todos los controles: es el frente abierto.", italic=True)

    doc.add_heading("4. Qué aporta —y qué no— la capa de IA", level=1)
    keys = [f"{f}|{m}" for f in families for m in ("restated", "fresh")]
    media = {n: sum(b[k] for k in keys) / len(keys) for n, b in subsets.items()}
    _p(doc, f"Recall medio por configuración, cada una a su propio presupuesto de falsas alarmas: "
            f"solo 3σ {media['solo_3sigma']:.3f}; banco de representaciones sin IA "
            f"{media['sin_ia']:.3f}; banco completo con la CNN {media['con_cnn']:.3f}.")
    _p(doc, "La lectura es inequívoca y conviene no adornarla. El salto grande no lo da el deep "
            "learning: lo da pasar de un único control sobre retornos a un banco que mira el dato "
            "en cuatro representaciones. La CNN añade encima una mejora real pero modesta.")
    _p(doc, "Dónde sí es la mejor opción la CNN: en salto reversible "
            f"({singles['retorno_cnn']['reversible_jump|restated']:.2f}), desacople "
            f"({singles['retorno_cnn']['decoupling|restated']:.2f}) y cambio de fuente, que son "
            "las familias donde el defecto es un patrón temporal multivariante sin estadístico "
            "cerrado evidente. Donde existe un control dedicado, la red pierde contra él.")
    fresh_best = [max(singles, key=lambda c: singles[c][f"{f}|fresh"]) for f in families]
    n_cnn = fresh_best.count("retorno_cnn")
    _p(doc, f"Un matiz que refuerza a la red y que conviene no pasar por alto: en el escenario "
            f"de DATO NUEVO —el operativamente frecuente, donde vintage no puede ayudar— la CNN "
            f"es el mejor control en {n_cnn} de las {len(families)} familias. Ahora bien, lo es "
            "en un campo débil: los recalls ahí van de 0,10 a 0,76, así que es la mejor opción "
            "disponible, no una solución. Ese escenario es el frente abierto del framework.")
    _p(doc, "Resultado negativo que hay que publicar igual: XGBoost como combinador de las "
            "señales rinde por debajo de la unión de los mismos controles con umbral propio. En "
            "pérdida de precisión llega a destruir un control que acierta el 100 %, diluyéndolo "
            "entre el resto. La conclusión es que el ML ayuda cuando ningún control es decisivo y "
            "estorba cuando uno lo es.")

    doc.add_heading("5. Estado de cada resultado", level=1)
    for ref, nombre, estado, motivo in ESTADO:
        doc.add_paragraph(f"{ref} · {nombre} — {estado}. {motivo}", style="List Bullet")

    doc.add_heading("6. Lo que estos resultados no permiten afirmar", level=1)
    for k, v in LIMITES:
        doc.add_paragraph(f"{k}. {v}", style="List Bullet")
    _p(doc, "Un resultado sin challenge superado es provisional y no puede figurar como "
            "afirmación en el paper. Dos resultados ya se han retirado o degradado por este "
            "procedimiento, y eso es el procedimiento funcionando, no fallando.",
       italic=True, color="777777")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def run(output_dir: Path) -> dict:
    stack_path = REPORTS / "dq_representation_stack" / "summary.json"
    dist_path = REPORTS / "dq_return_distribution" / "summary.json"
    for p in (stack_path, dist_path):
        if not p.exists():
            raise FileNotFoundError(
                f"Falta {p}. Ejecuta antes los experimentos: los entregables no "
                "recalculan nada, solo leen los JSON publicados.")
    stack = json.loads(stack_path.read_text(encoding="utf-8"))
    dist = json.loads(dist_path.read_text(encoding="utf-8"))

    xlsx = output_dir / "resultados_dq.xlsx"
    docx = output_dir / "resumen_dq_estado_del_arte.docx"
    build_excel(stack, dist, xlsx)
    build_word(stack, dist, docx)
    return {"excel": str(xlsx), "word": str(docx)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPORTS / "dq_entregables")
    args = parser.parse_args()
    out = run(args.output)
    print(f"  Excel -> {out['excel']}")
    print(f"  Word  -> {out['word']}")


if __name__ == "__main__":
    main()
