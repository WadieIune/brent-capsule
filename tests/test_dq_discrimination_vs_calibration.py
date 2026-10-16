import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "code" / "applications" / "experiments" / "dq_discrimination_vs_calibration.py"
SPEC = importlib.util.spec_from_file_location("dq_discrimination_vs_calibration", MODULE)
dvc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dvc)


def test_el_umbral_rodante_es_causal():
    """El futuro del flujo evaluado no puede cambiar una alerta ya emitida."""
    rng = np.random.default_rng(0)
    calibration = rng.normal(size=120)
    observed = rng.normal(size=80)
    evaluated = rng.normal(size=80)
    first = dvc.rolling_flags(calibration, observed, evaluated)
    altered = evaluated.copy()
    altered[50:] += 40.0
    np.testing.assert_array_equal(first[:50],
                                  dvc.rolling_flags(calibration, observed, altered)[:50])


def test_el_umbral_rodante_no_usa_etiquetas_de_limpieza():
    """Diferencia con el gate adaptativo retirado: solo entra el score observado.

    Si el flujo observado cambia, el umbral cambia; pero nada en la firma permite
    decirle qué ventanas eran limpias, que era lo que hacía indesplegable al ACI.
    """
    rng = np.random.default_rng(1)
    calibration = rng.normal(size=120)
    evaluated = rng.normal(size=60)
    tranquilo = dvc.rolling_flags(calibration, np.zeros(60), evaluated)
    agitado = dvc.rolling_flags(calibration, rng.normal(0, 5, size=60), evaluated)
    assert tranquilo.sum() >= agitado.sum(), (
        "un flujo observado más disperso debe elevar el umbral y alertar menos")


def test_el_umbral_rodante_sigue_una_deriva_de_nivel():
    """Es la razón de ser del protocolo: el congelado se descalibra, este no."""
    rng = np.random.default_rng(2)
    calibration = rng.normal(0, 1, size=200)
    derivado = rng.normal(3.0, 1, size=300)
    congelado = float(np.mean(derivado > np.quantile(calibration, 1 - dvc.ALPHA)))
    rodante = float(np.mean(dvc.rolling_flags(calibration, derivado, derivado)))
    assert congelado > 0.5
    assert rodante < 0.20


def test_la_ventana_rodante_limita_la_memoria():
    """Solo los últimos `window` scores pesan; si no, no habría adaptación."""
    rng = np.random.default_rng(3)
    calibration = rng.normal(0, 1, size=500)
    stream = rng.normal(5.0, 1, size=400)
    corta = np.mean(dvc.rolling_flags(calibration, stream, stream, window=30))
    larga = np.mean(dvc.rolling_flags(calibration, stream, stream, window=400))
    assert corta < larga, "una ventana corta debe adaptarse antes a la deriva"


def test_el_protocolo_de_oraculo_queda_declarado_como_no_desplegable():
    """La medida a FPR idéntica fija el umbral sobre el test: hay que decirlo.

    Es el tipo de advertencia que, si se pierde, convierte un diagnóstico de
    atribución en una promesa de rendimiento.
    """
    import inspect
    fuente = inspect.getsource(dvc)
    assert "ORÁCULO" in fuente or "oráculo" in fuente.lower()
    assert "no es desplegable" in fuente.lower() or "NO es desplegable" in fuente
