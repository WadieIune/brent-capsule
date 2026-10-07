#!/usr/bin/env python3
"""Gate DQ conforme-adaptativo: reevalúa CNN 1D vs controles baratos a presupuesto
de falsas alarmas REALMENTE impuesto.

Motivación (challenge a `dq_cnn1d_supervised`): aquel experimento calibró el umbral
sobre la validación 2019-2023 y lo congeló para el test 2024-2026. La deriva de
distribución hizo que la CNN operase al 19,9 % de FPR frente al 9,7 % del control
cross-asset, y el veredicto ("la CNN no pasa el gate") comparó detectores en puntos
de operación distintos. Este módulo separa las dos preguntas:

  1. **Poder discriminante** — recall a FPR realizada emparejada y AUC-ROC/AUC-PR.
  2. **Calibración** — un gate conforme-adaptativo (ACI, Gibbs & Candès 2021) que
     ajusta el umbral en línea y mantiene la tasa de falsas alarmas en el objetivo
     bajo deriva, en vez de congelar un cuantil de validación.

Añade además los dos controles que el experimento original no hacía:

  - **leave-one-family-out**: la CNN se entrenaba con las mismas tres familias que
    se le inyectaban en test, así que su ventaja estaba inflada por estar dentro de
    distribución. Aquí se mide el recall sobre la familia retenida.
  - **seis familias no vistas** (`UNSEEN_FAMILIES`): reescalado, inversión de signo,
    desfase de calendario de una sesión, fuente semanal propagada con forward-fill,
    empalme de proveedores y pérdida de precisión. Ninguna entra en el
    entrenamiento, así que miden cobertura de lo **no anticipado** — que es lo que
    de verdad se le pide a una capa de DQ. En `rescale` y `sign_flip`, `1 - R²` es
    **analíticamente invariante** —al reajustar la pendiente, R² no cambia—, de modo
    que el control barato tiene ahí un espacio nulo demostrable, no una simple
    pérdida de potencia.

Solo inyecciones sintéticas: no se afirma nada sobre prevalencia real de defectos.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def _load_base():
    """Carga el experimento original como módulo hermano.

    Se hace por ruta explícita (y no con un `import` normal) porque estos scripts de
    DQ no están registrados en `__init__.py` y se ejecutan tanto como script como
    desde los tests, que los cargan por ruta.
    """
    path = Path(__file__).resolve().parent / "dq_cnn1d_supervised.py"
    spec = importlib.util.spec_from_file_location("dq_cnn1d_supervised", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()
FAMILIES = base.FAMILIES
FIT_END = base.FIT_END
VAL_END = base.VAL_END
FP_TARGET = base.FP_TARGET
fit_cnn = base.fit_cnn
inject = base.inject
load_windows = base.load_windows
score_cnn = base.score_cnn
score_cross_asset = base.score_cross_asset
score_3sigma = base.score_3sigma

SEEDS = (42, 71, 123, 7, 2024)
ACI_GAMMA = 0.02
ACI_WINDOW = 236


def inject_rescale(window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Familia NO vista en entrenamiento: error de unidad/factor de ajuste.

    Reescala la serie objetivo entre 1,3x y 1,6x, con signo aleatorio. No es un
    salto puntual, ni una racha estancada, ni un desfase de fechas.

    Nota de auditoría: incluye un componente de signo. `inject_sign_flip` lo
    aísla; `1 - R²` es invariante a ambos por el mismo argumento (R² no depende
    del factor `c` en `y → c·y`, tampoco de su signo).
    """
    out = window.copy()
    out[:, 0] *= float(rng.uniform(1.3, 1.6)) * float(rng.choice([-1.0, 1.0]))
    return out


def inject_sign_flip(window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Error de convención: la serie objetivo entra con el signo invertido.

    Caso real frecuente en spreads y en series de posición (largo/corto).
    """
    out = window.copy()
    out[:, 0] *= -1.0
    return out


def inject_lag1(window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Desfase de calendario de UNA sesión.

    Es la forma del defecto real de EURUSD que atravesó el pipeline en 2008
    (`docs/hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md`). Queda
    fuera de `decoupling`, que usa desplazamientos de 2 o más sesiones.
    """
    out = window.copy()
    out[:, 0] = np.roll(out[:, 0], 1)
    return out


def inject_weekly_ffill(window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Fuente semanal propagada a diario con forward-fill.

    Cuatro de cada cinco sesiones quedan sin movimiento y la quinta acumula el
    retorno de la semana. No es `stale` (que anula la ventana entera) ni un salto
    aislado: es un patrón periódico con la varianza total preservada.
    """
    out = window.copy()
    target = out[:, 0].copy()
    out[:, 0] = 0.0
    offset = int(rng.integers(0, 5))
    stops = list(range(offset, len(target), 5))
    # La última semana parcial también publica, si no el retorno de la cola se
    # perdería y la inyección dejaría de conservar el movimiento de la ventana.
    if not stops or stops[-1] != len(target) - 1:
        stops.append(len(target) - 1)
    start = 0
    for stop in stops:
        out[stop, 0] = target[start:stop + 1].sum()
        start = stop + 1
    return out


def inject_source_switch(window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Cambio de proveedor a mitad de ventana: la segunda mitad cambia de escala.

    Simula un empalme mal hecho entre dos fuentes de la misma serie. No hay salto
    puntual: lo que cambia es el régimen de amplitud a partir de un corte.
    """
    out = window.copy()
    cut = int(rng.integers(len(out) // 3, 2 * len(out) // 3))
    out[cut:, 0] *= float(rng.uniform(2.0, 3.0))
    return out


def inject_quantize(window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Pérdida de precisión: el feed trunca la cotización a menos decimales.

    En el espacio de retornos normalizados aparece como una rejilla: los valores
    se apelmazan en múltiplos de un paso. Ni la media ni la escala cambian mucho.
    """
    out = window.copy()
    step = float(rng.uniform(0.8, 1.2))
    out[:, 0] = np.round(out[:, 0] / step) * step
    return out


#: Familias que NINGÚN detector vio en entrenamiento. La CNN se entrena solo con
#: `FAMILIES`; estas miden cobertura de lo no anticipado, que es la afirmación
#: central del hallazgo asociado.
UNSEEN_FAMILIES = {
    "rescale": inject_rescale,
    "sign_flip": inject_sign_flip,
    "lag1_calendar": inject_lag1,
    "weekly_ffill": inject_weekly_ffill,
    "source_switch": inject_source_switch,
    "quantize": inject_quantize,
}


def volatility_ratio_score(windows: np.ndarray) -> np.ndarray:
    """Control simple especializado contra el reescalado (checklist #8).

    Compara la volatilidad de la ventana objetivo con la mediana de la de sus pares.
    Es el competidor honesto de la CNN en la familia no vista.
    """
    target = np.std(windows[:, :, 0], axis=1)
    peers = np.median(np.std(windows[:, :, 1:], axis=1), axis=1)
    return np.abs(np.log((target + 1e-12) / (peers + 1e-12)))


def aci_flags(calibration: np.ndarray, clean_stream: np.ndarray, evaluated: np.ndarray,
              target: float = FP_TARGET, gamma: float = ACI_GAMMA,
              window: int = ACI_WINDOW) -> np.ndarray:
    """Adaptive Conformal Inference sobre un flujo causal.

    En cada paso el umbral es el cuantil ``1 - alpha_t`` de las puntuaciones limpias
    más recientes; ``alpha_t`` se corrige con la falsa alarma efectivamente observada
    en el flujo limpio. ``evaluated`` se puntúa en ese mismo punto de operación, de
    modo que recall y FPR son comparables entre detectores.
    """
    if len(clean_stream) != len(evaluated):
        raise ValueError("El flujo limpio y el evaluado deben tener la misma longitud")
    history = list(calibration)
    alpha = target
    flags = np.empty(len(evaluated), dtype=bool)
    for t in range(len(evaluated)):
        level = float(np.clip(alpha, 1e-3, 0.5))
        threshold = float(np.quantile(np.asarray(history[-window:]), 1.0 - level))
        flags[t] = evaluated[t] > threshold
        alpha += gamma * (target - (1.0 if clean_stream[t] > threshold else 0.0))
        history.append(float(clean_stream[t]))
    return flags


def matched_fpr_recall(scorer, clean: np.ndarray, injected: np.ndarray,
                       target: float = FP_TARGET) -> float:
    """Recall con el presupuesto de falsas alarmas impuesto por construcción."""
    threshold = float(np.quantile(scorer(clean), 1.0 - target))
    return float(np.mean(scorer(injected) > threshold))


def _split(panel_path: Path):
    windows, starts, ends, data_hash = load_windows(panel_path)
    train = windows[ends <= FIT_END]
    validation = windows[(starts > FIT_END) & (ends <= VAL_END)]
    test = windows[starts > VAL_END]
    if min(len(train), len(validation), len(test)) < 20:
        raise ValueError("Insuficientes ventanas en uno de los bloques temporales")
    return train, validation, test, data_hash


def _inject_all(test: np.ndarray, rng: np.random.Generator) -> dict[str, np.ndarray]:
    injected = {f: np.asarray([inject(x, f, rng) for x in test], dtype=np.float32)
                for f in FAMILIES}
    for name, injector in UNSEEN_FAMILIES.items():
        injected[name] = np.asarray([injector(x, rng) for x in test], dtype=np.float32)
    return injected


def _mean_std(values: list[float]) -> dict[str, float]:
    return {"mean": float(np.mean(values)), "std": float(np.std(values))}


def run(panel_path: Path, output_dir: Path, seeds: tuple[int, ...] = SEEDS) -> dict:
    train, validation, test, data_hash = _split(panel_path)
    all_families = list(FAMILIES) + list(UNSEEN_FAMILIES)

    matched: dict[str, dict[str, list[float]]] = {}
    conformal: dict[str, dict[str, list[float]]] = {}
    lofo: dict[str, list[float]] = {}

    for seed in seeds:
        cnn = fit_cnn(train, validation, seed=seed)
        rng = np.random.default_rng(seed + 2)
        injected = _inject_all(test, rng)
        detectors = {
            "cnn_1d": lambda x, model=cnn: score_cnn(model, x),
            "cross_asset_1_minus_r2": score_cross_asset,
            "3sigma_vol_normalizada": score_3sigma,
            "vol_ratio_vs_pares": volatility_ratio_score,
        }
        for name, scorer in detectors.items():
            clean_test = scorer(test)
            matched.setdefault(name, {}).setdefault("false_positive_rate", []).append(
                float(np.mean(clean_test > np.quantile(clean_test, 1.0 - FP_TARGET))))
            for family in all_families:
                matched[name].setdefault(family, []).append(
                    matched_fpr_recall(scorer, test, injected[family]))

            calibration = scorer(validation)
            conformal.setdefault(name, {}).setdefault("false_positive_rate", []).append(
                float(np.mean(aci_flags(calibration, clean_test, clean_test))))
            for family in all_families:
                conformal[name].setdefault(family, []).append(
                    float(np.mean(aci_flags(calibration, clean_test,
                                            scorer(injected[family])))))

        # leave-one-family-out: la CNN se reentrena sin la familia que se le mide.
        # `fit_cnn` lee `FAMILIES` del módulo base al etiquetar, así que se restringe
        # ahí temporalmente; el resto del experimento sigue midiendo las cuatro.
        for held_out in FAMILIES:
            original = base.FAMILIES
            base.FAMILIES = tuple(f for f in original if f != held_out)
            try:
                partial = fit_cnn(train, validation, seed=seed)
            finally:
                base.FAMILIES = original
            lofo.setdefault(held_out, []).append(
                matched_fpr_recall(lambda x: score_cnn(partial, x), test,
                                   injected[held_out]))

    output = {
        "protocol": {
            "source": str(panel_path),
            "sha256": data_hash,
            "seeds": list(seeds),
            "n_train_windows": len(train),
            "n_validation_windows": len(validation),
            "n_test_windows": len(test),
            "target_false_positive_rate": FP_TARGET,
            "trained_families": list(FAMILIES),
            "unseen_families": list(UNSEEN_FAMILIES),
            "aci": {"gamma": ACI_GAMMA, "calibration_window": ACI_WINDOW,
                    "reference": "Gibbs & Candes (2021), Adaptive Conformal Inference"},
            "matched_protocol": "umbral = cuantil (1-alpha) de las puntuaciones limpias de test; impone la FPR por construccion y aisla el poder discriminante",
            "conformal_protocol": "umbral causal recalibrado en linea sobre el flujo limpio; es el protocolo operativo",
        },
        "matched_fpr": {d: {k: _mean_std(v) for k, v in fam.items()}
                        for d, fam in matched.items()},
        "conformal_aci": {d: {k: _mean_std(v) for k, v in fam.items()}
                          for d, fam in conformal.items()},
        "cnn_leave_one_family_out": {k: _mean_std(v) for k, v in lofo.items()},
        "interpretation": (
            "Benchmark de defectos sinteticos. El recall de la CNN dentro de sus familias de "
            "entrenamiento esta inflado (ver leave_one_family_out); su resultado defendible es "
            "la cobertura de la familia no vista, donde 1-R^2 es analiticamente ciego."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def _print_table(title: str, block: dict, families: list[str]) -> None:
    print(f"\n{title}")
    header = f"  {'detector':24s} {'FPR':>7s}  " + " ".join(f"{f[:10]:>10s}" for f in families)
    print(header)
    for name, stats in block.items():
        cells = " ".join(f"{stats[f]['mean']:10.3f}" for f in families)
        print(f"  {name:24s} {stats['false_positive_rate']['mean']:7.3f}  {cells}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_conformal_gate")
    args = parser.parse_args()
    result = run(args.panel, args.output)
    families = list(FAMILIES) + list(UNSEEN_FAMILIES)
    _print_table("A) FPR emparejada por construccion (poder discriminante)",
                 result["matched_fpr"], families)
    _print_table("B) Gate conforme-adaptativo ACI (protocolo operativo)",
                 result["conformal_aci"], families)
    print("\nC) CNN leave-one-family-out (recall fuera de distribucion, FPR emparejada)")
    for family, stats in result["cnn_leave_one_family_out"].items():
        inside = result["matched_fpr"]["cnn_1d"][family]["mean"]
        print(f"  {family:24s} dentro={inside:.3f}  retenida={stats['mean']:.3f}")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
