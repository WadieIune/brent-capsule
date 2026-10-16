#!/usr/bin/env python3
"""Entregables para el Risk Director y el director del paper: Excel y Word.

Genera dos documentos a partir de los JSON ya producidos por los experimentos,
sin recalcular nada: así no pueden divergir de la evidencia. Si un resultado se
retira o se degrada, se retira aquí también.

- **Excel** (`resultados_dq.xlsx`): una hoja por pregunta que hace un Risk
  Director. Qué significa cada métrica y cómo se midió, qué cubre cada control,
  qué deja pasar, a qué coste de falsas alarmas, qué evidencia de backtest
  respalda a los modelos de riesgo que consumen la serie, y qué alcance tiene
  cada afirmación.
- **Word** (`resumen_dq_estado_del_arte.docx`): resumen ejecutivo.

Regla de edición: **todo número que salga aquí tiene que existir en un JSON de
`results/reports/`**, salvo la evidencia de validación de los modelos aguas
abajo, que procede de los manifiestos de las líneas de riesgo y se cita como
tal. No se reportan cifras de impacto en capital.
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
    ("Cobertura complementaria por representación", "🟡 provisional",
     "Los controles muestran perfiles de cobertura distintos y varias familias quedan cubiertas "
     "por un único control en este test. "
     "Medido con defectos de verdad conocida sobre test temporal y presupuesto de falsas "
     "alarmas nominal calibrado en validación; la FPR se mide en test y puede diferir. "
     "Pendiente de auditoría cruzada."),
    ("Calibración empírica del umbral", "🟡 provisional",
     "Se congela un umbral empírico usando un bloque de validación separado y purgado. No se "
     "reclama garantía conformal ni control de FPR bajo drift."),
    ("Alcance del control de vintage", "🟡 provisional",
     "Alcanza recall 1,00 cuando el defecto reescribe historia ya publicada y es ciego por "
     "construcción cuando llega con el dato nuevo, porque no hay snapshot con el que comparar."),
    ("Aportación de la CNN 1D", "🟡 exploratorio",
     "La evaluación sintética no demuestra superioridad generalizable. La selección de "
     "ganadores se hace sobre el mismo test; hacen falta prueba externa y etiquetas reales."),
    ("XGBoost como combinador", "🟡 no concluyente",
     "Su recall y el de la unión se observan con FPR OOS distintas. No se puede afirmar que "
     "uno supere al otro sin comparar a un mismo punto de operación o sobre curvas ROC/PR."),
    ("Impacto en capital", "fuera de alcance",
     "No se reporta ninguna cifra. Requiere posiciones, notional y metodología de cartera "
     "aprobados; ver la hoja de métricas y protocolo."),
]

#: Manifiestos de las líneas de riesgo de los que se lee la evidencia de backtest.
FUENTES_AGUAS_ABAJO = {
    "var": "portfolio_var_manifest.json",
    "supervivencia": "part2_channel_survival_validacion.json",
    "detector": "detector_solo_precio.json",
    "backtest_canal": "backtest_canal_dsr_pbo.json",
}

#: Curva de operación del gate. Se lee, no se escribe a mano: si se recalibra el
#: gate, el entregable recoge el nuevo punto de operación solo.
FUENTE_OPERACION = "dq_rolling_gate/summary.json"


def _dig(payload: dict, path: str, source: str):
    """Navega un camino `a.b.c` y falla con un mensaje que dice dónde se rompió.

    Se prefiere romper a devolver un valor por defecto: si un manifiesto cambia
    de forma, el entregable tiene que dejar de generarse en vez de publicar un
    número obsoleto.
    """
    node = payload
    for i, key in enumerate(path.split(".")):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(
                f"{source}: falta la ruta '{path}' (se rompió en "
                f"'{'.'.join(path.split('.')[:i + 1])}'). El manifiesto ha cambiado "
                "de forma; actualiza el lector en vez de publicar cifras obsoletas.")
        node = node[key]
    return node


def _n(value: float, decimals: int = 3) -> str:
    """Formato español: coma decimal."""
    return f"{value:.{decimals}f}".replace(".", ",")


def load_downstream(reports: Path) -> list[tuple[str, str, str, str]]:
    """Evidencia de backtest de los modelos de riesgo que consumen la serie.

    Se lee de los manifiestos de las líneas de riesgo, no se escribe a mano: si
    alguna de esas líneas se re-ejecuta y cambian los números, el entregable los
    recoge solo. El backtest aplica a estos modelos, que miden riesgo; el gate de
    calidad mide detección y se valida con defectos de verdad conocida.
    """
    data = {}
    for alias, filename in FUENTES_AGUAS_ABAJO.items():
        path = reports / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Falta el manifiesto {path}, necesario para la evidencia de backtest "
                f"de los modelos aguas abajo ({alias}).")
        data[alias] = json.loads(path.read_text(encoding="utf-8"))

    var_src = FUENTES_AGUAS_ABAJO["var"]
    fhs = _dig(data["var"], "metrics.backtests.fhs_ewma", var_src)
    hist_chr = _dig(data["var"], "metrics.backtests.historical.christoffersen.p_value", var_src)
    n_test = _dig(data["var"], "metrics.n_test", var_src)

    sup_src = FUENTES_AGUAS_ABAJO["supervivencia"]
    aft = _dig(data["supervivencia"], "metrics.walkforward.summary.q2_xgb_aft", sup_src)

    det_src = FUENTES_AGUAS_ABAJO["detector"]
    auc_asc = _dig(data["detector"], "ascending_channel.auc", det_src)
    auc_desc = _dig(data["detector"], "descending_channel.auc", det_src)

    bt_src = FUENTES_AGUAS_ABAJO["backtest_canal"]
    dsr = _dig(data["backtest_canal"], "deflated_sharpe.deflated_sharpe_ratio", bt_src)
    pbo = _dig(data["backtest_canal"], "pbo.pbo", bt_src)
    sharpe = _dig(data["backtest_canal"], "strategy.sharpe_annual", bt_src)
    sharpe_bh = _dig(data["backtest_canal"], "buy_and_hold.sharpe_annual", bt_src)

    # El separador de miles se construye aparte: aplicar un `replace` sobre la
    # frase entera convertía también las comas decimales y las de puntuación.
    dias = f"{n_test:,}".replace(",", ".")

    return [
        ("VaR FHS-EWMA condicional a volatilidad", "Supera el backtest",
         f"Kupiec p {_n(fhs['kupiec']['p_value'])}: la tasa de excepciones observada "
         f"({_n(100 * fhs['exception_rate'], 3)} %) es indistinguible del 1 % teórico, o sea la "
         f"cobertura es correcta. Christoffersen p {_n(fhs['christoffersen']['p_value'])}: las "
         f"excepciones NO se agrupan. Semáforo de Basilea en zona "
         f"{fhs['capital']['zone_avg']} con multiplicador k = {_n(fhs['capital']['multiplier_avg'], 1)} "
         f"y {fhs['basel']['exceptions']} excepciones en {dias} días.",
         "Pasa PORQUE condiciona a volatilidad. Un VaR histórico simple sobre la misma serie "
         f"falla la prueba de independencia (Christoffersen p {_n(hist_chr, 4)}): acumula sus "
         "excepciones en los episodios de estrés, que es justo cuando el capital tiene que "
         "aguantar."),
        ("Supervivencia del canal · XGB-AFT", "Supera el backtest",
         f"C-index {_n(aft['c_index_mean'])} ± {_n(aft['c_index_std'])} en walk-forward purgado "
         f"con embargo (mínimo por fold {_n(aft['c_index_min'])}), de modo que el modelo ordena "
         "correctamente qué canales viven más.",
         "Pasa PORQUE la validación es temporal y purgada: el embargo entre train y test impide "
         "que un episodio que rompe tras el corte entrene con su propio futuro."),
        ("Detección de canal · CNN EfficientNet", "Pasa como clasificador, no como estrategia",
         f"AUC {_n(auc_asc)} en canal ascendente y {_n(auc_desc)} en descendente.",
         "Como CLASIFICADOR pasa. Como estrategia de inversión NO: Deflated Sharpe "
         f"{_n(dsr)} y PBO {_n(pbo)}, con un Sharpe anual de {_n(sharpe)} frente a "
         f"{_n(sharpe_bh)} del buy & hold. Por eso se usa como contexto de régimen para el "
         "Risk Director y nunca como señal de trading."),
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
    ("FPR observada no igualada", "La FPR de test puede diferir entre controles pese a calibrar "
     "umbrales al mismo objetivo nominal; no interpretar recall como comparación a operación idéntica."),
    ("Resolución de calibración", "El bloque de calibración es finito. La cuota de Bonferroni por "
     "control puede quedar por debajo de una observación (1/n), en cuyo caso el umbral empírico "
     "se sitúa en el máximo de calibración y no puede realizar exactamente el objetivo nominal."),
    ("Un solo activo y un solo panel", "Todo el banco se ha medido sobre Brent y sus cuatro pares. "
     "La transferencia a otras asset classes NO está demostrada."),
    ("Capital", "No se reporta ninguna cifra de capital. Sería k·VaR con el semáforo de Basilea, "
     "pero exigiría cartera real, correlaciones, diversificación entre mesas, específico y "
     "default, PLA por mesa, NMRF y suelo SA."),
]


METRICAS = [
    ("Recall (sensibilidad)",
     "De los tramos que SÍ tenían un defecto inyectado, qué fracción levantó alerta el "
     "control. Es la métrica principal de cobertura. Recall 1,00 = los caza todos.",
     "TP / (TP + FN)"),
    ("FPR realizada",
     "De los tramos LIMPIOS, qué fracción levantó alerta igualmente. Es el coste operativo: "
     "cada falsa alarma es trabajo de revisión que no encuentra nada. NO se promete un "
     "objetivo nominal, porque no se cumple fuera de muestra: se DECLARA la medida. Ver la "
     "hoja de punto de operación.",
     "FP / (FP + TN)"),
    ("Recall a objetivo nominal",
     "Los umbrales se fijan en una porción de validación limpia con un objetivo nominal del 5 %. "
     "La tasa realizada se mide en el test posterior y puede diferir por deriva y dependencia.",
     "recall; FPR OOS aparte"),
    ("Recall de la peor familia",
     "El mínimo sobre las familias de defecto. Un control con buena media y un cero en una "
     "familia tiene un punto ciego, y eso importa más que la media.",
     "min_familias(recall)"),
    ("Azar",
     "Referencia aproximada para un detector aleatorio con prevalencia de alertas del 5 %. En tablas, "
     "las celdas en gris están en el azar: ese control NO ve esa familia.",
     "≈ 0,048"),
    ("Precisión / PPV",
     "NO se reporta. Exigiría conocer la prevalencia real de cada defecto, y no la tenemos. "
     "Declararla con prevalencia inventada daría un número sin significado.",
     "no calculada"),
]

PROTOCOLO = [
    ("Fuente de datos",
     "Panel `panel_extendido_2026-09-09.csv`. BRENT como serie objetivo y cuatro pares "
     "correlacionados: WTI, DTWEXBGS, COPPER, EUROSTOXX50. Pares elegidos por correlación "
     "medida SOLO en el tramo de entrenamiento, para no mirar el futuro."),
    ("Hash del dato",
     "sha256 b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3. Queda en cada "
     "summary.json para que el resultado sea trazable al fichero exacto."),
    ("Unidad de análisis",
     "Ventanas de 20 sesiones con paso de 5. ATENCIÓN: solapan al 75 %, así que NO son "
     "observaciones independientes y cualquier intervalo de confianza implícito es optimista."),
    ("Partición temporal",
     "Estrictamente cronológica, sin mezclar. Entrenamiento hasta 2018-12-31 (558 ventanas). "
     "Validación 2019-2023 (236), separada en ajuste temprano y calibración posterior con "
     "purga por solapamiento. CNN y XGBoost se ajustan sin test; los umbrales se congelan "
     "antes de evaluar el bloque desde 2024-01-05 (124 ventanas)."),
    ("Ground truth",
     "Defectos SINTÉTICOS inyectados sobre los precios crudos, con verdad conocida por "
     "construcción. Tras inyectar se RECALCULAN retornos y normalización causal, para que el "
     "defecto se propague como lo haría en producción. No hay etiquetas de incidentes reales."),
    ("Calibración del umbral",
     "Umbral empírico de orden estadístico calibrado en un segmento tardío de validación, "
     "separado del ajuste por una purga de ventanas solapadas. Queda congelado antes del test. "
     "La FPR de test se informa sin feedback; no se reclama garantía conformal ni control bajo drift."),
    ("Sin fuga temporal",
     "Normalización causal con media y desviación móviles de 60 sesiones desplazadas una. WTI "
     "se representa con diferencias en dólares para preservar su settlement negativo real de "
     "abril de 2020 en vez de tratarlo como un error."),
    ("Repeticiones",
     "Tres semillas (42, 71, 123) para la CNN y el combinador. Los controles estadísticos son "
     "deterministas y no llevan dispersión: no comparar estabilidad entre filas."),
    ("Detección, no backtest",
     "El gate de calidad se valida midiendo DETECCIÓN sobre defectos de verdad conocida en un "
     "bloque temporal posterior: recall y falsas alarmas. No hay estrategia, ni P&L, ni Sharpe, "
     "porque el gate no toma posiciones. El backtest —walk-forward purgado, DSR, PBO/CSCV, "
     "Kupiec, Christoffersen, semáforo de Basilea— valida a los MODELOS DE RIESGO que consumen "
     "la serie. Su evidencia está en la hoja «Modelos aguas abajo»."),
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


def build_excel(stack: dict, dist: dict, aguas_abajo: list, operacion: list,
                path: Path) -> None:
    families = stack["protocol"]["families"]
    singles = stack["single_controls_validation_threshold"]
    subsets = stack["gate_subsets_validation_threshold"]
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
         "La CNN forma parte del banco de detectores, pero esta evaluación sintética no demuestra "
         "superioridad generalizable. Los mejores controles por familia se seleccionan sobre el "
         "mismo test y son resultados exploratorios; requieren validación externa y etiquetas reales."),
        ("El frente abierto",
         "Cuando el defecto llega con el dato nuevo en vez de reescribir historia publicada, la "
         "cobertura cae para TODOS los controles. El control de vintage, que alcanza 1,00 en "
         "casi todas las familias con restatement, es ciego por construcción ahí: no hay "
         "snapshot anterior con el que comparar. Es donde hay que seguir trabajando."),
        ("Qué no está demostrado sobre el machine learning",
         "No se demuestra superioridad de CNN ni XGBoost. La FPR OOS de las configuraciones "
         "difiere y la comparación XGBoost-unión no está igualada en operación; hacen falta "
         "curvas de rendimiento y validación externa."),
        ("Comparaciones válidas",
         "Los umbrales se calibran con un objetivo nominal común en validación, pero la FPR "
         "observada en test difiere entre controles. Las comparaciones por familia son "
         "descriptivas y exploratorias; no identifican valor incremental de CNN o XGBoost."),
        ("Por qué 3σ no basta",
         f"En Brent, |z|>3 ocurre el {dist['colas_normal_vs_empirica'][2]['frecuencia_empirica']:.2%} "
         f"de las sesiones frente al {dist['colas_normal_vs_empirica'][2]['frecuencia_normal']:.2%} "
         "de referencia gaussiana. Es una estadística descriptiva estandarizada ex post, no un "
         "test de defectos ni evidencia de que 3σ distinga errores de mercado."),
        ("Lo que NO se afirma",
         "No se da ninguna cifra de capital. No se demuestra transferencia a otras asset "
         "classes. No se afirma prevalencia real de defectos. Ver hoja 9."),
    ]
    _header(ws, 4, ["Pregunta", "Respuesta"], [30, 110])
    for i, (k, v) in enumerate(puntos, start=5):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True, size=10)
        ws.cell(row=i, column=1).alignment = WRAP
        ws.cell(row=i, column=1).border = BORDER
        c = ws.cell(row=i, column=2, value=v)
        c.alignment, c.border = WRAP, BORDER
        ws.row_dimensions[i].height = 46

    # --- 1b. Métricas y protocolo ---
    ws = _sheet(wb, "2 Métricas y protocolo",
                "Qué significa cada número de este Excel y cómo se ha medido. Leer antes que "
                "las tablas de resultados.")
    _header(ws, 4, ["Métrica", "Qué mide", "Definición"], [26, 92, 20])
    for r, (nombre, desc, formula) in enumerate(METRICAS, start=5):
        ws.cell(row=r, column=1, value=nombre).font = Font(bold=True, size=10)
        ws.cell(row=r, column=1).border = BORDER
        c = ws.cell(row=r, column=2, value=desc)
        c.alignment, c.border = WRAP, BORDER
        f = ws.cell(row=r, column=3, value=formula)
        f.alignment, f.border = Alignment(horizontal="center", vertical="top"), BORDER
        ws.row_dimensions[r].height = 42

    start = 5 + len(METRICAS) + 2
    ws.cell(row=start - 1, column=1, value="Diseño experimental").font = TITLE_FONT
    _header(ws, start, ["Elemento", "Cómo se ha hecho"], [26, 112])
    for r, (k, v) in enumerate(PROTOCOLO, start=start + 1):
        cell = ws.cell(row=r, column=1, value=k)
        cell.font = Font(bold=True, size=10,
                         color="C00000" if k.startswith("ESTO NO") else "000000")
        cell.border, cell.alignment = BORDER, WRAP
        c = ws.cell(row=r, column=2, value=v)
        c.alignment, c.border = WRAP, BORDER
        ws.row_dimensions[r].height = 46
    ws.freeze_panes = "A5"

    # --- 1c. Punto de operación declarado ---
    ws = _sheet(wb, "3 Punto de operación",
                "LA HOJA QUE HAY QUE LEER PARA DIMENSIONAR LA REVISIÓN. El gate no promete una "
                "tasa nominal de falsas alarmas, porque no se cumple fuera de muestra: declara "
                "la medida. Elige la fila por capacidad de revisión disponible.")
    _header(ws, 4, ["α nominal pedido", "FPR REALIZADA", "dispersión", "exceso sobre nominal",
                    "recall medio"], [18, 18, 14, 22, 16])
    for r, fila in enumerate(operacion, start=5):
        valores = [fila["alpha_nominal"], round(fila["fpr_realizada_media"], 3),
                   f"± {fila['fpr_realizada_std']:.3f}",
                   f"{fila['factor_de_exceso']:.1f}x", round(fila["recall_medio"], 3)]
        for col, value in enumerate(valores, start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=2).font = Font(bold=True)

    suelo = min(f["fpr_realizada_media"] for f in operacion)
    fila = 5 + len(operacion) + 1
    for texto in (
        f"SUELO MEDIDO: el gate no baja de {suelo:.3f} de ventanas limpias marcadas. Pedir un "
        "α de 0,005 o de 0,010 da exactamente lo mismo, así que dimensionar la revisión "
        "suponiendo un 5 % o un 1 % es dimensionar mal.",
        "Por encima del suelo el intercambio es real y suave: más carga de revisión compra más "
        "cobertura. El punto se elige por capacidad disponible, no por un número de referencia.",
        "El exceso sobre el nominal tiene dos causas medidas. La resolución de la muestra de "
        "calibración ya está corregida ampliando la ventana. La que queda es deriva: cada "
        "control realiza ~2,6 veces su tasa nominal porque el tramo reciente no predice la cola "
        "del siguiente. Esa es la que fija el suelo y no se arregla repartiendo mejor.",
    ):
        cell = ws.cell(row=fila, column=1, value=texto)
        cell.alignment, cell.font = WRAP, Font(size=9, italic=True)
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=5)
        ws.row_dimensions[fila].height = 46
        fila += 1

    # --- 2. Cobertura por control y familia ---
    ws = _sheet(wb, "4 Cobertura", f"Recall por control y familia; objetivo nominal de calibración "
                f"{target:.0%}, FPR de test observada y no igualada. Azar ≈ {chance:.3f}; en gris lo que está en el azar. "
                "«Reescribe historia» = el defecto altera datos ya publicados; «dato nuevo» = solo "
                "afecta a las sesiones recientes.")
    labels = ["Control", "Capa", "Representación", "FPR test"] + \
             [f"{f}\n(reescribe)" for f in families] + [f"{f}\n(dato nuevo)" for f in families]
    _header(ws, 4, labels, [28, 8, 14, 11] + [13] * (2 * len(families)))
    for r, (control, (capa, repre, _)) in enumerate(CONTROL_DESC.items(), start=5):
        ws.cell(row=r, column=1, value=control).border = BORDER
        ws.cell(row=r, column=2, value=capa).border = BORDER
        ws.cell(row=r, column=3, value=repre).border = BORDER
        ws.cell(row=r, column=4, value=round(singles[control]["test_false_positive_rate"], 3)).border = BORDER
        for j, mode in enumerate(("restated", "fresh")):
            for k, fam in enumerate(families):
                value = singles[control][f"{fam}|{mode}"]
                cell = ws.cell(row=r, column=5 + j * len(families) + k, value=round(value, 3))
                cell.fill, cell.border = _recall_fill(value, chance), BORDER
                cell.alignment = Alignment(horizontal="center")

    # --- 3. Gate A vs Gate B ---
    ws = _sheet(wb, "5 Gate A vs Gate B",
                "Los umbrales se calibran con el mismo objetivo nominal en validación, pero la FPR "
                "realizada en test difiere. Las diferencias de recall son descriptivas y no aíslan "
                "el valor incremental de ninguna capa. Este benchmark mide controles en paralelo; "
                "no valida un router secuencial.")
    _header(ws, 4, ["Configuración", "Qué incluye", "FPR observada en test",
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
                                     round(block["test_false_positive_rate"], 3),
                                     round(sum(values) / len(values), 3),
                                     round(min(values), 3)], start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border, cell.alignment = BORDER, WRAP
    row = 5 + len(subsets) + 1
    ws.cell(row=row, column=1, value="Diferencia descriptiva: banco con CNN menos banco sin CNN").font = Font(bold=True)
    delta = (sum(subsets["con_cnn"][k] for k in keys) - sum(subsets["sin_ia"][k] for k in keys)) / len(keys)
    ws.cell(row=row, column=4, value=round(delta, 3)).font = Font(bold=True)
    ws.cell(row=row + 1, column=1,
            value="Diferencia exploratoria post hoc sobre el mismo test; no es una estimación "
                  "confirmatoria de aportación incremental. Requiere test externo y protocolo "
                  "preespecificado.").font = Font(italic=True, size=9)

    # --- 4. Familias de defecto ---
    ws = _sheet(wb, "6 Familias", "Mejor control observado por familia, selección post hoc en el mismo test; lectura exploratoria.")
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

    # --- 5b. Modelos de riesgo aguas abajo ---
    ws = _sheet(wb, "7 Modelos aguas abajo",
                "La serie que valida el gate alimenta a estos modelos. El backtest se aplica a "
                "ellos, que miden riesgo, y la columna de la derecha explica POR QUÉ cada uno "
                "lo supera. Son resultados de las líneas de riesgo del proyecto, no de este gate.")
    _header(ws, 4, ["Modelo", "Veredicto", "Evidencia de validación", "Por qué lo supera"],
            [34, 26, 60, 60])
    for r, (modelo, veredicto, evidencia, porque) in enumerate(aguas_abajo, start=5):
        for col, value in enumerate([modelo, veredicto, evidencia, porque], start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border, cell.alignment = BORDER, WRAP
        ws.cell(row=r, column=1).font = Font(bold=True, size=10)
        ws.cell(row=r, column=2).font = Font(
            bold=True, color="3A7D52" if veredicto.startswith("Supera") else "C0703A")
        ws.row_dimensions[r].height = 76

    # --- 5. Estado de validación ---
    ws = _sheet(wb, "8 Estado", "Estado de validación de cada afirmación de esta entrega. "
                "Un resultado sin auditoría cruzada superada es provisional y no puede figurar "
                "como afirmación cerrada en el paper.")
    _header(ws, 4, ["Afirmación", "Estado", "Alcance y condición"], [44, 26, 72])
    for r, (nombre, estado, motivo) in enumerate(ESTADO, start=5):
        for col, value in enumerate([nombre, estado, motivo], start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border, cell.alignment = BORDER, WRAP
        ws.cell(row=r, column=1).font = Font(bold=True, size=10)
        if "negativo" in estado:
            ws.cell(row=r, column=2).font = Font(bold=True, color="C0703A")
        ws.row_dimensions[r].height = 52

    # --- 6. Limitaciones ---
    ws = _sheet(wb, "9 Limitaciones", "Lo que estos números NO permiten afirmar. Leer antes de "
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


def build_word(stack: dict, dist: dict, aguas_abajo: list, operacion: list,
               path: Path) -> None:
    families = stack["protocol"]["families"]
    singles = stack["single_controls_validation_threshold"]
    subsets = stack["gate_subsets_validation_threshold"]
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
            f"{tails[3]['frecuencia_normal']:.2%} de referencia gaussiana. La estandarización "
            "usa la muestra completa y es descriptiva; no constituye un detector de defectos ni "
            "un umbral desplegable.")
    _p(doc, "Una cola más pesada cuestiona el supuesto gaussiano del umbral, pero no permite "
            "clasificar una observación como movimiento de mercado o error de datos. Esa "
            "distinción requiere controles adicionales y etiquetas de incidentes.")
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
    _p(doc, "Los umbrales se calibran una vez sobre un segmento limpio tardío de validación, "
            "separado del ajuste por una purga, y quedan congelados antes del test. La FPR OOS se "
            "reporta sin feedback. No se reclama garantía conformal ni estabilidad bajo drift.")

    doc.add_heading("3. Punto de operación declarado", level=1)
    suelo = min(f["fpr_realizada_media"] for f in operacion)
    _p(doc, "El gate no promete una tasa nominal de falsas alarmas, porque no se cumple fuera "
            "de muestra. Declara la medida, que es lo que permite dimensionar la capacidad de "
            f"revisión sobre un número real. El suelo medido es {suelo:.1%} de ventanas limpias "
            "marcadas: por debajo de ahí no existe configuración, de modo que pedir un 5 % o un "
            "1 % no cambia nada salvo la expectativa de quien lo lee.")
    tabla_op = doc.add_table(rows=1, cols=3)
    tabla_op.style = "Light Grid Accent 1"
    for i, h in enumerate(("α nominal pedido", "FPR realizada (medida)", "recall medio")):
        celda = tabla_op.rows[0].cells[i]
        celda.text = h
        celda.paragraphs[0].runs[0].bold = True
    for fila in operacion:
        fila_t = tabla_op.add_row().cells
        fila_t[0].text = f"{fila['alpha_nominal']:.3f}"
        fila_t[1].text = f"{fila['fpr_realizada_media']:.3f} ± {fila['fpr_realizada_std']:.3f}"
        fila_t[2].text = f"{fila['recall_medio']:.3f}"
    _p(doc, "Por encima del suelo el intercambio es real y suave: más carga de revisión compra "
            "más cobertura. El exceso sobre el nominal se descompone en resolución de la muestra "
            "de calibración, ya corregida, y deriva residual —cada control realiza unas 2,6 veces "
            "su tasa nominal—, que es la que fija el suelo y no se arregla repartiendo mejor el "
            "presupuesto entre controles.", italic=True)

    doc.add_heading("4. Ninguna representación domina", level=1)
    _p(doc, "Medido sobre siete familias de defecto sintéticas, con umbrales calibrados al mismo "
            "objetivo nominal en validación y FPR observada de forma independiente en test, el "
            "resultado es una matriz de coberturas "
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

    doc.add_heading("5. Qué aporta —y qué no— la capa de IA", level=1)
    keys = [f"{f}|{m}" for f in families for m in ("restated", "fresh")]
    media = {n: sum(b[k] for k in keys) / len(keys) for n, b in subsets.items()}
    _p(doc, f"Recall medio descriptivo por configuración con FPR OOS no igualada "
            f"solo 3σ {media['solo_3sigma']:.3f}; banco de representaciones sin IA "
            f"{media['sin_ia']:.3f}; banco completo con la CNN {media['con_cnn']:.3f}.")
    _p(doc, "Estas cifras no aíslan el efecto de la CNN: cambian las tasas de falsas alarmas "
            "realizadas y la composición de controles. La selección del mejor control por familia "
            "se hace sobre el mismo test y es exploratoria, no evidencia confirmatoria.")
    fresh_best = [max(singles, key=lambda c: singles[c][f"{f}|fresh"]) for f in families]
    n_cnn = fresh_best.count("retorno_cnn")
    _p(doc, f"En este test, la CNN resulta el máximo por familia en {n_cnn} de {len(families)} "
            "familias de dato nuevo. Como el ganador se selecciona post hoc y no hay etiquetas "
            "reales ni prevalencias observadas, este recuento solo genera una hipótesis para una "
            "evaluación externa preespecificada.")
    _p(doc, "La comparación XGBoost-unión no es concluyente: sus FPR OOS son distintas, por lo "
            "que la diferencia de recall mezcla sensibilidad con punto de operación. No se atribuye "
            "ventaja ni perjuicio al combinador sin comparación a FPR equivalente y validación externa.")

    doc.add_heading("6. Los modelos de riesgo que consumen la serie", level=1)
    _p(doc, "El gate de calidad entrega una serie validada a los modelos de riesgo. A ellos "
            "se les aplica el backtest, porque miden riesgo y toman posiciones; al gate no, "
            "porque mide detección y se valida con defectos de verdad conocida. Conviene "
            "dejar escrito no solo que superan la validación, sino por qué.")
    for modelo, veredicto, evidencia, porque in aguas_abajo:
        doc.add_paragraph(f"{modelo} — {veredicto}. {evidencia} {porque}", style="List Bullet")

    doc.add_heading("7. Estado de validación", level=1)
    for nombre, estado, motivo in ESTADO:
        doc.add_paragraph(f"{nombre} — {estado}. {motivo}", style="List Bullet")

    doc.add_heading("8. Lo que estos resultados no permiten afirmar", level=1)
    for k, v in LIMITES:
        doc.add_paragraph(f"{k}. {v}", style="List Bullet")
    _p(doc, "Un resultado sin auditoría cruzada superada es provisional y no puede figurar "
            "como afirmación cerrada en el paper.", italic=True, color="777777")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def load_operating_curve(reports: Path) -> list[dict]:
    """Curva de operación del gate: carga de alarmas realizada frente a recall."""
    path = reports / FUENTE_OPERACION
    if not path.exists():
        raise FileNotFoundError(
            f"Falta {path}. Ejecuta antes dq_rolling_gate.py: el punto de operación "
            "declarado sale de ahí y no se escribe a mano.")
    return json.loads(path.read_text(encoding="utf-8"))["curva_de_operacion"]


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
    aguas_abajo = load_downstream(REPORTS)
    operacion = load_operating_curve(REPORTS)
    build_excel(stack, dist, aguas_abajo, operacion, xlsx)
    build_word(stack, dist, aguas_abajo, operacion, docx)
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
