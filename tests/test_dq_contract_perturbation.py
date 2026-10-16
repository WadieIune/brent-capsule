import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "code" / "applications" / "experiments" / "dq_contract_perturbation.py"
SPEC = importlib.util.spec_from_file_location("dq_contract_perturbation", MODULE)
cp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cp)


def _precios(rng, filas=21, activos=5, tick=0.01):
    nivel = 80.0 + np.cumsum(rng.normal(0, 1.0, size=(filas, activos)), axis=0)
    return np.round(nivel / tick) * tick


def test_las_perturbaciones_son_legitimas_no_defectos():
    """Si alguna rompiera la serie, su alerta sería un acierto y no una falsa alarma.

    La premisa del experimento es que toda alerta cuenta como falsa, así que las
    perturbaciones tienen que preservar la información: reescalados, cambios de
    granularidad o ajustes pequeños, nunca pérdida de contenido.
    """
    rng = np.random.default_rng(0)
    precios = _precios(rng, filas=60)
    for nombre, perturbar in cp.ESCENARIOS.items():
        recibido, _ = perturbar(precios, 10, 40, np.random.default_rng(1))
        objetivo = recibido[10:40, 0]
        assert np.isfinite(objetivo).all(), f"{nombre} produjo valores no finitos"
        assert (objetivo > 0).all(), f"{nombre} produjo precios no positivos"
        assert len(np.unique(objetivo)) > 1, (
            f"{nombre} dejó la serie plana: eso sería un defecto, no un cambio de contrato")


def test_la_perturbacion_de_contrato_no_toca_a_los_pares():
    """El contrato que cambia es el de la serie objetivo, no el del panel entero."""
    rng = np.random.default_rng(2)
    precios = _precios(rng, filas=60)
    for nombre, perturbar in cp.ESCENARIOS.items():
        recibido, _ = perturbar(precios, 10, 40, np.random.default_rng(3))
        np.testing.assert_array_equal(recibido[:, 1:], precios[:, 1:],
                                      err_msg=f"{nombre} tocó los pares")


def test_un_cambio_legitimo_de_tick_dispara_la_reticula():
    """Es el resultado que invalida la premisa: el control no distingue el
    cambio de contrato del defecto."""
    rng = np.random.default_rng(4)
    precios = _precios(rng, filas=40)
    nominal = cp.pricelab.grid_step_score(precios[None, :, :])
    ampliado, _ = cp.tick_ampliado(precios, 0, len(precios), rng)
    score = cp.pricelab.grid_step_score(ampliado[None, :, :])
    assert cp.gate.semantic_flags(nominal, score, "precio_reticula").all()


def test_un_ajuste_de_settlement_minusculo_ya_dispara_vintage():
    """Tolerancia de ruido numérico, no de materialidad: 0,05 % ya alerta.

    Es el defecto de diseño que destapa el experimento. Un control de vintage
    desplegable necesita umbral de MATERIALIDAD, no de ruido de coma flotante.
    """
    rng = np.random.default_rng(5)
    precios = _precios(rng, filas=40)
    almacenado = precios[None, :, :]
    recibido = precios.copy()
    recibido[:, 0] *= 1.0005
    score = cp.stack.vintage_discrepancy(recibido[None, :, :], almacenado)
    nominal = cp.stack.vintage_discrepancy(almacenado, almacenado)
    assert cp.gate.semantic_flags(nominal, score, "vintage_discrepancia").all()


def test_el_veredicto_publicado_no_afirma_que_no_gasten_presupuesto():
    """El JSON no puede quedarse con la premisa que este experimento refuta."""
    ruta = ROOT / "results" / "reports" / "dq_contract_perturbation" / "summary.json"
    if not ruta.exists():
        return
    import json
    payload = json.loads(ruta.read_text(encoding="utf-8"))
    if payload["peor_fpr_observada"] > 0.01:
        assert "NO es universal" in payload["veredicto"]
