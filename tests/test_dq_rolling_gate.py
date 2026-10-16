import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "code" / "applications" / "experiments" / "dq_rolling_gate.py"
SPEC = importlib.util.spec_from_file_location("dq_rolling_gate", MODULE)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_el_presupuesto_solo_lo_reparten_los_estadisticos():
    """Incluir a los deterministas en el reparto exigía a la muestra una
    resolución que no tiene, sin que ellos gasten falsas alarmas."""
    estadisticos = [n for n, c in gate.CONTROL_CLASS.items() if c == "estadistico"]
    assert len(estadisticos) < len(gate.CONTROL_CLASS)
    share = gate.ALPHA / len(estadisticos)
    assert share > gate.ALPHA / len(gate.CONTROL_CLASS)


def test_el_control_determinista_no_gasta_falsas_alarmas():
    """Su puntuación limpia es constante, así que el umbral semántico no dispara."""
    limpio = np.full(80, 0.01)          # el tick nativo
    assert not gate.semantic_flags(limpio, limpio, "precio_reticula").any()


def test_el_control_determinista_caza_cualquier_desviacion():
    limpio = np.full(80, 0.01)
    truncado = np.full(40, 0.25)
    assert gate.semantic_flags(limpio, truncado, "precio_reticula").all()


def test_el_umbral_semantico_tolera_ruido_numerico():
    """La discrepancia de vintage limpia es ~1e-14; no puede ser una alerta."""
    limpio = np.full(60, 0.0)
    ruido = np.full(30, 1e-14)
    assert not gate.semantic_flags(limpio, ruido, "vintage_discrepancia").any()
    assert gate.semantic_flags(limpio, np.full(30, 0.04), "vintage_discrepancia").all()


def test_se_rompe_si_un_control_declarado_determinista_no_lo_es():
    """Clasificar mal un control produciría falsas alarmas silenciosas."""
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="declarado determinista"):
        gate.assert_degenerate(rng.normal(1.0, 0.3, size=60), "control_inventado")


def test_la_ventana_rodante_resuelve_el_share_por_control():
    """Si la ventana no resuelve el share, el umbral colapsa al máximo empírico.

    Es la causa medida de que la unión se disparara: con 60 ventanas no se puede
    estimar un cuantil de 0,0071.
    """
    estadisticos = sum(1 for c in gate.CONTROL_CLASS.values() if c == "estadistico")
    share = gate.ALPHA / estadisticos
    assert 1 / gate.ROLLING_WINDOW <= share, (
        f"ventana {gate.ROLLING_WINDOW} no resuelve un share de {share:.5f}")


def test_el_gate_combina_las_dos_clases():
    """Un defecto que solo ve el determinista debe levantar la alerta igual."""
    features = tuple(gate.stack.FEATURES)
    rng = np.random.default_rng(1)
    cal = rng.normal(size=(240, len(features)))
    for j, name in enumerate(features):
        if gate.CONTROL_CLASS[name] == "determinista":
            cal[:, j] = 0.01
    limpio = cal[:120].copy()
    solo_reticula = limpio.copy()
    solo_reticula[:, features.index("precio_reticula")] = 0.5
    assert gate.gate_flags(cal, limpio, solo_reticula, features).all()
