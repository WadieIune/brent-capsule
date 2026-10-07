#!/usr/bin/env python3
"""El canal como TERCERA representación para control de calidad de dato.

Las dos representaciones ya medidas comparten un sesgo: `dq_conformal_gate` mira
**retornos normalizados por volatilidad** (y allí los cuatro detectores comparten
un espacio nulo entero) y `dq_quantize_price_grid` mira la **retícula del precio**.
Falta la que el proyecto ya tiene construida para la pata de riesgo: la geometría
del **canal** —recta central, ancho de banda y oscilación— y la coherencia de la
posición dentro de banda entre activos correlacionados.

No se busca rentabilidad: el canal se usa aquí **solo** como representación de
control. La pregunta es si cubre familias de defecto que las otras dos no ven,
para no infra/sobre-estimar capital por una serie sucia que pasó el gate.

Dos diferencias de diseño frente a los experimentos anteriores:

  1. **Las inyecciones son en espacio de PRECIO**, no sobre retornos ya
     normalizados. Retornos y normalización causal se recalculan sobre la serie
     corrompida, así que las tres representaciones ven el mismo defecto.
  2. La definición de canal **se reutiliza** de `part2_channel_survival`
     (`_linear_fit_metrics`, `find_turning_points`), no se inventa aquí.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "part2_channel_survival"))
from patterns_min import _linear_fit_metrics, find_turning_points  # noqa: E402


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load("dq_cnn1d_supervised")
gate = _load("dq_conformal_gate")
pricelab = _load("dq_quantize_price_grid")

FP_TARGET = base.FP_TARGET
EPS = 1e-12


# --------------------------------------------------------------------------
# Inyecciones en espacio de PRECIO. Todas tocan solo la serie objetivo.
# --------------------------------------------------------------------------

def p_stale(prices, lo, hi, rng):
    """Cotización repetida: el defecto TRIM real (≥20 sesiones sin movimiento)."""
    out = prices.copy()
    out[lo:hi, 0] = out[lo, 0]
    return out


def p_reversible_jump(prices, lo, hi, rng):
    """Pico que vuelve: un tick erróneo corregido al día siguiente."""
    out = prices.copy()
    t = int(rng.integers(lo + 1, hi - 1))
    out[t, 0] *= 1.0 + float(rng.choice([-1.0, 1.0])) * float(rng.uniform(0.08, 0.15))
    return out


def p_decoupling(prices, lo, hi, rng):
    """Desalineación de fechas de varias sesiones frente a los pares."""
    out = prices.copy()
    shift = int(rng.integers(2, max(3, (hi - lo) - 1)))
    out[lo:hi, 0] = np.roll(out[lo:hi, 0], shift)
    return out


def p_lag1(prices, lo, hi, rng):
    """Desfase de UNA sesión: la forma del defecto real de EURUSD de 2008."""
    out = prices.copy()
    out[lo:hi, 0] = np.roll(out[lo:hi, 0], 1)
    return out


def p_weekly_ffill(prices, lo, hi, rng):
    """Fuente semanal propagada a diario: el precio solo cambia un día de cada cinco."""
    out = prices.copy()
    offset = int(rng.integers(0, 5))
    for start in range(lo + offset, hi, 5):
        out[start:min(start + 5, hi), 0] = out[start, 0]
    return out


def p_source_switch(prices, lo, hi, rng):
    """Empalme de proveedores: salto de nivel a mitad de ventana sin corregir."""
    out = prices.copy()
    cut = int(rng.integers(lo + (hi - lo) // 3, lo + 2 * (hi - lo) // 3))
    out[cut:hi, 0] *= float(rng.uniform(1.04, 1.10))
    return out


def p_quantize(prices, lo, hi, rng):
    """Pérdida de precisión del feed: truncación del tick."""
    step = float(rng.choice([0.10, 0.25, 0.50, 1.00]))
    out = prices.copy()
    out[lo:hi, 0] = step * np.round(out[lo:hi, 0] / step)
    return out


PRICE_FAMILIES = {
    "stale": p_stale,
    "reversible_jump": p_reversible_jump,
    "decoupling": p_decoupling,
    "lag1_calendar": p_lag1,
    "weekly_ffill": p_weekly_ffill,
    "source_switch": p_source_switch,
    "quantize": p_quantize,
}


# --------------------------------------------------------------------------
# Representación de CANAL. Definición reutilizada de part2_channel_survival.
# --------------------------------------------------------------------------

def band_position(price_windows: np.ndarray) -> np.ndarray:
    """Posición dentro de banda de cada activo: residuo sobre la recta central,
    escalado por el ancho del canal.

    Es scale-free y trend-free por construcción: lo que queda es *dónde* está el
    precio dentro de su propio canal, no su nivel ni su pendiente.
    """
    out = np.zeros_like(price_windows, dtype=float)
    for i, window in enumerate(price_windows):
        for j in range(window.shape[1]):
            values = window[:, j]
            x = np.arange(len(values), dtype=float)
            slope, intercept = np.polyfit(x, values, 1)
            residual = values - (slope * x + intercept)
            out[i, :, j] = residual / (np.std(residual) + EPS)
    return out


def channel_coherence_score(price_windows: np.ndarray) -> np.ndarray:
    """Coherencia de posición-en-banda entre la objetivo y sus pares.

    Si los activos correlacionados se mueven en la misma dirección, sus posiciones
    dentro de banda deben co-moverse. Es la pregunta del MASTER: entender el
    rendimiento que se obtiene frente a *asset classes* correlacionadas.

    Distinto del `1-R²` de `dq_conformal_gate`: aquél regresa **retornos**
    normalizados por volatilidad; éste regresa **posición dentro del canal**.
    """
    positions = band_position(price_windows)
    scores = np.zeros(len(positions))
    for i, pos in enumerate(positions):
        y, x = pos[:, 0], pos[:, 1:]
        design = np.column_stack([np.ones(len(y)), x])
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual = y - design @ beta
        total = float(np.sum((y - y.mean()) ** 2))
        scores[i] = 1.0 if total <= EPS else float(np.sum(residual ** 2) / total)
    return scores


def channel_breach_score(price_windows: np.ndarray) -> np.ndarray:
    """Cuánto se escapa la objetivo de su propia banda."""
    return np.max(np.abs(band_position(price_windows)[:, :, 0]), axis=1)


def channel_geometry_shift_score(price_windows: np.ndarray) -> np.ndarray:
    """Cambio de geometría del canal entre la primera y la segunda mitad.

    Un empalme de fuentes o un cambio de escala rompe el ancho o la pendiente a
    mitad de ventana sin producir ningún retorno atípico aislado.
    """
    scores = np.zeros(len(price_windows))
    for i, window in enumerate(price_windows):
        target = window[:, 0]
        half = len(target) // 2
        slope_a, _, width_a = _linear_fit_metrics(target[:half])
        slope_b, _, width_b = _linear_fit_metrics(target[half:])
        level = np.mean(np.abs(target)) + EPS
        width = abs(np.log((width_b + EPS) / (width_a + EPS)))
        slope = abs(slope_b - slope_a) / level
        scores[i] = width + slope
    return scores


def channel_oscillation_score(price_windows: np.ndarray) -> np.ndarray:
    """Déficit de oscilación: un canal sano rebota en sus bordes.

    Una serie estancada o propagada con forward-fill deja de girar, y eso es
    invisible para un control de magnitud de retorno.
    """
    scores = np.zeros(len(price_windows))
    for i, window in enumerate(price_windows):
        maxima, minima = find_turning_points(window[:, 0])
        scores[i] = 1.0 / (1.0 + len(maxima) + len(minima))
    return scores


CHANNEL_CONTROLS = {
    "canal_coherencia_banda": channel_coherence_score,
    "canal_ruptura_banda": channel_breach_score,
    "canal_cambio_geometria": channel_geometry_shift_score,
    "canal_deficit_oscilacion": channel_oscillation_score,
}


# --------------------------------------------------------------------------

def run(panel_path: Path, output_dir: Path, seeds=gate.SEEDS) -> dict:
    prices, _ = pricelab.read_prices(panel_path)
    clean_scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(clean_scaled)

    data = pricelab.build(panel_path, seeds)
    n_train, n_val = data["n"]["train"], data["n"]["validation"]
    val_bounds = bounds[n_train:n_train + n_val]
    test_bounds = bounds[n_train + n_val:][:data["n"]["test"]]

    clean_p = data["test_p"]
    clean_z = data["test_z"]
    # Ventanas de precio de VALIDACIÓN: calibran el gate sin tocar el test.
    val_p = np.asarray([prices[a:b + 1] for a, b in val_bounds], dtype=float)

    rng = np.random.default_rng(20261007)
    injected_p, injected_z = {}, {}
    for name, injector in PRICE_FAMILIES.items():
        ps, zs = [], []
        for a, b in test_bounds:
            corrupted = injector(prices, a, b + 1, rng)
            ps.append(corrupted[a:b + 1])
            zs.append(pricelab.normalize(corrupted)[a:b])
        injected_p[name] = np.asarray(ps, dtype=float)
        injected_z[name] = np.asarray(zs, dtype=np.float32)

    families = list(PRICE_FAMILIES)
    results: dict[str, dict[str, float]] = {}
    conformal: dict[str, dict[str, float]] = {}

    def add_price_control(name, scorer):
        """Mide el control en los DOS protocolos.

        `matched` fija el umbral sobre el test limpio: aísla poder discriminante
        pero no es operativo. `conformal` calibra sobre validación limpia y
        recalibra en línea (ACI), que es el gate real. B pidió explícitamente que
        el segundo acompañe al primero.
        """
        results[name] = {f: gate.matched_fpr_recall(scorer, clean_p, injected_p[f], FP_TARGET)
                         for f in families}
        calibration, clean_stream = scorer(val_p), scorer(clean_p)
        entry = {"false_positive_rate":
                 float(np.mean(gate.aci_flags(calibration, clean_stream, clean_stream)))}
        for f in families:
            entry[f] = float(np.mean(
                gate.aci_flags(calibration, clean_stream, scorer(injected_p[f]))))
        conformal[name] = entry

    for name, scorer in CHANNEL_CONTROLS.items():
        add_price_control(name, scorer)
    add_price_control("reticula_precio", pricelab.grid_step_score)

    # Controles que viven en la representación de RETORNO NORMALIZADO.
    z_acc: dict[str, dict[str, list[float]]] = {}
    z_conf: dict[str, dict[str, list[float]]] = {}
    for seed in seeds:
        cnn = base.fit_cnn(data["train_z"], data["val_z"], seed=seed)
        detectors = {
            "cnn_1d": lambda x, m=cnn: base.score_cnn(m, x),
            "cross_asset_1_minus_r2": base.score_cross_asset,
            "3sigma_vol_normalizada": base.score_3sigma,
        }
        for name, scorer in detectors.items():
            calibration, clean_stream = scorer(data["val_z"]), scorer(clean_z)
            z_conf.setdefault(name, {}).setdefault("false_positive_rate", []).append(
                float(np.mean(gate.aci_flags(calibration, clean_stream, clean_stream))))
            for f in families:
                z_acc.setdefault(name, {}).setdefault(f, []).append(
                    gate.matched_fpr_recall(scorer, clean_z, injected_z[f], FP_TARGET))
                z_conf[name].setdefault(f, []).append(float(np.mean(
                    gate.aci_flags(calibration, clean_stream, scorer(injected_z[f])))))
    for name, by_family in z_acc.items():
        results[name] = {f: float(np.mean(v)) for f, v in by_family.items()}
    for name, by_family in z_conf.items():
        conformal[name] = {k: float(np.mean(v)) for k, v in by_family.items()}

    chance = 1.0 / len(clean_p) * np.floor(FP_TARGET * len(clean_p))
    output = {
        "protocol": {
            "source": str(panel_path),
            "question": "¿el canal cubre familias de defecto que las otras dos representaciones no ven?",
            "injection_space": "PRECIO; retornos y normalización causal recalculados sobre la serie corrompida",
            "channel_definition": "reutilizada de code/part2_channel_survival/patterns_min.py",
            "representations": {
                "canal": list(CHANNEL_CONTROLS),
                "precio": ["reticula_precio"],
                "retorno_normalizado": ["cnn_1d", "cross_asset_1_minus_r2", "3sigma_vol_normalizada"],
            },
            "families": families,
            "target_false_positive_rate": FP_TARGET,
            "approx_chance_recall": float(chance),
            "n_windows": data["n"],
            "seeds": list(seeds),
            "matched_protocol": "umbral = cuantil (1-alpha) del test limpio; aisla poder discriminante, NO es operativo",
            "conformal_protocol": "umbral calibrado en validación limpia y recalibrado en línea (ACI); es el gate operativo",
        },
        "recall_matched_fpr": results,
        "recall_conformal_aci": conformal,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_channel_representation")
    args = parser.parse_args()
    result = run(args.panel, args.output)
    families = result["protocol"]["families"]
    chance = result["protocol"]["approx_chance_recall"]
    groups = result["protocol"]["representations"]

    def table(title, block, show_fpr):
        print(f"\n{title}  (azar ~{chance:.3f}, inyección en espacio de PRECIO)")
        head = f"  {'control':26s} " + (f"{'FPR':>7s} " if show_fpr else "")
        print(head + " ".join(f"{f[:11]:>11s}" for f in families))
        for group, names in groups.items():
            print(f"  --- representación: {group} ---")
            for name in names:
                row = block[name]
                fpr = f"{row['false_positive_rate']:7.3f} " if show_fpr else ""
                cells = " ".join(
                    f"{row[f]:10.3f}" + ("*" if row[f] <= chance + 1e-9 else " ")
                    for f in families)
                print(f"  {name:26s} {fpr}{cells}")

    table(f"A) FPR emparejada por construcción ({FP_TARGET:.0%}) — poder discriminante",
          result["recall_matched_fpr"], show_fpr=False)
    table(f"B) Gate conforme-adaptativo ACI ({FP_TARGET:.0%}) — protocolo OPERATIVO",
          result["recall_conformal_aci"], show_fpr=True)
    print("\n  * = en el azar (ciego). "
          f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
