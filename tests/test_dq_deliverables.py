import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "code" / "applications" / "experiments" / "dq_deliverables.py"
SPEC = importlib.util.spec_from_file_location("dq_deliverables", MODULE_PATH)
deliv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deliv)

REPORTS = ROOT / "results" / "reports"


def _texto():
    return " ".join(campo for fila in deliv.load_downstream(REPORTS) for campo in fila)


def test_las_cifras_proceden_de_los_manifiestos_y_no_estan_escritas_a_mano():
    """Si una línea de riesgo se re-ejecuta, el entregable debe seguirla.

    Se comprueba contra la fuente, no contra un valor literal del test: así el
    test tampoco puede divergir.
    """
    var = json.loads((REPORTS / "portfolio_var_manifest.json").read_text(encoding="utf-8"))
    sup = json.loads((REPORTS / "part2_channel_survival_validacion.json").read_text(encoding="utf-8"))
    det = json.loads((REPORTS / "detector_solo_precio.json").read_text(encoding="utf-8"))
    bt = json.loads((REPORTS / "backtest_canal_dsr_pbo.json").read_text(encoding="utf-8"))
    fhs = var["metrics"]["backtests"]["fhs_ewma"]

    esperado = {
        "Kupiec FHS": (fhs["kupiec"]["p_value"], 3),
        "Christoffersen FHS": (fhs["christoffersen"]["p_value"], 3),
        "Christoffersen histórico": (
            var["metrics"]["backtests"]["historical"]["christoffersen"]["p_value"], 4),
        "C-index XGB-AFT": (
            sup["metrics"]["walkforward"]["summary"]["q2_xgb_aft"]["c_index_mean"], 3),
        "AUC canal ascendente": (det["ascending_channel"]["auc"], 3),
        "PBO": (bt["pbo"]["pbo"], 3),
        "Sharpe buy&hold": (bt["buy_and_hold"]["sharpe_annual"], 3),
    }
    texto = _texto()
    for nombre, (valor, decimales) in esperado.items():
        formateado = f"{valor:.{decimales}f}".replace(".", ",")
        assert formateado in texto, f"{nombre}: no aparece '{formateado}' en el entregable"


def test_los_decimales_usan_coma_y_no_quedan_numeros_con_punto():
    """Un `replace` global sobre la frase convertía las comas decimales en puntos.

    En español el punto es separador de MILES, así que `1.393` es correcto. Un
    punto decimal se reconoce porque va precedido de `0`, o porque el grupo que
    le sigue no tiene exactamente tres cifras.
    """
    sospechosos = [
        bruto for bruto in re.findall(r"\d+\.\d+", _texto())
        if bruto.startswith("0.") or len(bruto.split(".")[1]) != 3
    ]
    assert not sospechosos, (
        f"cifras con punto decimal en vez de coma: {sospechosos}. "
        "Alguna sustitución está tocando la frase entera.")


def test_el_contraste_del_var_historico_sigue_presente():
    """El 'por qué pasa' del VaR depende de que el histórico FALLE la independencia."""
    var = json.loads((REPORTS / "portfolio_var_manifest.json").read_text(encoding="utf-8"))
    historico = var["metrics"]["backtests"]["historical"]["christoffersen"]["p_value"]
    fhs = var["metrics"]["backtests"]["fhs_ewma"]["christoffersen"]["p_value"]
    assert historico < 0.05 < fhs, (
        "el argumento era que el histórico agrupa excepciones y el FHS-EWMA no; "
        "si eso deja de cumplirse hay que reescribir la explicación, no el número")


def test_falla_ruidosamente_si_falta_un_manifiesto(tmp_path):
    try:
        deliv.load_downstream(tmp_path)
    except FileNotFoundError as exc:
        assert "manifiesto" in str(exc)
        return
    raise AssertionError("se esperaba FileNotFoundError en vez de cifras por defecto")


def test_falla_ruidosamente_si_un_manifiesto_cambia_de_forma(tmp_path):
    for nombre in deliv.FUENTES_AGUAS_ABAJO.values():
        (tmp_path / nombre).write_text("{}", encoding="utf-8")
    try:
        deliv.load_downstream(tmp_path)
    except KeyError as exc:
        assert "manifiesto ha cambiado" in str(exc)
        return
    raise AssertionError("se esperaba KeyError describiendo la ruta que falta")


def test_no_se_reportan_cifras_de_capital():
    texto = _texto()
    assert "capital evitado" not in texto.lower()
    # «capital» puede aparecer como concepto, pero nunca con un porcentaje pegado.
    assert not re.search(r"capital[^.]{0,40}\d+,\d+\s*%", texto, re.I)
