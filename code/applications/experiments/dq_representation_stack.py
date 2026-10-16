#!/usr/bin/env python3
"""Pila de las CUATRO representaciones de control + combinador XGBoost.

Cierra las dos piezas que quedaban abiertas en `dq_channel_representation`:

1. **Vintage como cuarta representación.** Compara la serie *recibida* hoy con la
   *almacenada* en un snapshot anterior. Es el control de B, que ya demostró
   1,000 en back-adjust de splits. Aquí se mide su alcance real separando cada
   familia en dos modos:
     - `restated`: el defecto reescribe historia ya publicada → vintage la ve.
     - `fresh`: el defecto solo afecta a las sesiones posteriores al snapshot →
       vintage es **ciego por construcción**, no hay nada con que comparar.
   Esa separación evita el espejismo de un control que parece dominar: vintage
   domina el subespacio de restatements y no cubre el dato fresco, que es por
   donde entra la mayoría de los defectos.

2. **XGBoost como COMBINADOR, no como detector más.** Toma como features las
   salidas de los controles de las cuatro representaciones y produce un veredicto
   único por ventana con umbral calibrado fuera de test. Es la pieza que convierte la
   matriz de coberturas en una decisión operable.

Separación temporal con purga: la **CNN se ajusta con train y validación temprana**,
el combinador con bloques de tuning y calibración separados, y todo se evalúa en
**test**. Además se reporta leave-one-family-out del combinador, que es
donde se vio antes que el recall dentro de distribución está inflado.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "part2_channel_survival"))


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load("dq_cnn1d_supervised")
gate = _load("dq_conformal_gate")
pricelab = _load("dq_quantize_price_grid")
channel = _load("dq_channel_representation")

FP_TARGET = base.FP_TARGET
ASSETS = base.ASSETS
ROLL = 60
SNAPSHOT_LAG = 5          # sesiones recientes que el snapshot aún no contenía
SEEDS = (42, 71, 123)
EPS = 1e-12


# --------------------------------------------------------------------------
# Renormalización LOCAL: misma salida que `pricelab.normalize`, sin recorrer
# toda la serie. Imprescindible porque aquí se renormalizan ~13.000 ventanas.
# --------------------------------------------------------------------------

def normalize_target_window(prices: np.ndarray, a: int, b: int) -> np.ndarray:
    """Columna objetivo normalizada para la ventana de retornos [a, b).

    El retorno `i` se normaliza con media y desviación de los retornos
    [i-60, i-1], así que basta con precios desde `a - ROLL - 1`. Equivale a
    `pricelab.normalize(prices)[a:b, 0]`; se valida en los tests.
    """
    lo = max(0, a - ROLL - 1)
    segment = prices[lo:b + 1, 0]
    returns = np.diff(np.log(segment))
    # `returns[k]` es el retorno global `lo + k`, así que el retorno `a` está en
    # `a - lo`. Desplazarlo una posición deja la media móvil por debajo de
    # `min_periods` en las primeras ventanas y devuelve NaN.
    offset = a - lo
    series = pd.Series(returns)
    mean = series.rolling(ROLL, min_periods=20).mean().shift(1).to_numpy()
    sigma = series.rolling(ROLL, min_periods=20).std().shift(1).to_numpy()
    out = np.full(b - a, np.nan)
    for k in range(b - a):
        i = offset + k
        if np.isfinite(mean[i]) and np.isfinite(sigma[i]) and sigma[i] > 1e-10:
            out[k] = (returns[i] - mean[i]) / sigma[i]
    return out


# --------------------------------------------------------------------------
# Representación VINTAGE
# --------------------------------------------------------------------------

def vintage_discrepancy(received: np.ndarray, stored: np.ndarray,
                        lag: int = SNAPSHOT_LAG) -> np.ndarray:
    """Máxima discrepancia relativa entre lo recibido hoy y lo almacenado antes.

    Solo se compara el solape: las `lag` sesiones más recientes no estaban en el
    snapshot y no se pueden contrastar. Un control que las mirase estaría
    inventando una referencia que no existía.
    """
    overlap = received.shape[1] - lag
    if overlap <= 0:
        raise ValueError("El snapshot no deja solape que comparar")
    a = received[:, :overlap, 0]
    b = stored[:, :overlap, 0]
    return np.max(np.abs(a / (b + EPS) - 1.0), axis=1)


# --------------------------------------------------------------------------
# Extracción de features: una fila por ventana, las cuatro representaciones
# --------------------------------------------------------------------------

FEATURES = (
    "canal_coherencia", "canal_ruptura", "canal_geometria", "canal_oscilacion",
    "precio_reticula",
    "retorno_cnn", "retorno_cross_asset", "retorno_3sigma",
    "vintage_discrepancia",
)

#: Configuraciones de gate que se comparan. Están anidadas a propósito: la
#: diferencia entre `sin_ia` y `con_cnn` es la **aportación marginal del deep
#: learning**, y la de `sin_ia` frente a `solo_3sigma` la del resto del banco
#: frente al control estándar. Sin este anidamiento no se puede atribuir valor.
GATE_SUBSETS = {
    "solo_3sigma": ("retorno_3sigma",),
    "sin_ia": ("canal_coherencia", "canal_ruptura", "canal_geometria",
               "canal_oscilacion", "precio_reticula", "retorno_cross_asset",
               "retorno_3sigma", "vintage_discrepancia"),
    "con_cnn": FEATURES,
}


def extract(received_p: np.ndarray, stored_p: np.ndarray, z: np.ndarray,
            cnn) -> np.ndarray:
    """Matriz (n_ventanas, 9) con el score de cada control."""
    columns = [
        channel.channel_coherence_score(received_p),
        channel.channel_breach_score(received_p),
        channel.channel_geometry_shift_score(received_p),
        channel.channel_oscillation_score(received_p),
        pricelab.grid_step_score(received_p),
        base.score_cnn(cnn, z),
        base.score_cross_asset(z),
        base.score_3sigma(z),
        vintage_discrepancy(received_p, stored_p),
    ]
    return np.column_stack([np.asarray(c, dtype=float) for c in columns])


# --------------------------------------------------------------------------

def _inject(prices, a, b, family, mode, rng):
    """Devuelve (precios_recibidos, precios_almacenados) de la ventana.

    `restated` corrompe toda la ventana: el snapshot guardado sigue limpio, así
    que el solape discrepa. `fresh` corrompe solo la cola posterior al snapshot,
    que es lo que ocurre cuando el defecto entra con el dato nuevo.
    """
    injector = channel.PRICE_FAMILIES[family]
    stored = prices[a:b + 1]
    if mode == "restated":
        corrupted = injector(prices, a, b + 1, rng)
    else:
        corrupted = injector(prices, b + 1 - SNAPSHOT_LAG, b + 1, rng)
    return corrupted, stored


def build_block(prices, bounds, scaled_clean, cnn, families, modes, rng):
    """Features de un bloque temporal: ventanas limpias + cada familia × modo.

    `scaled_clean` es la normalización de la serie limpia completa, calculada una
    sola vez fuera. Las inyecciones solo tocan la columna objetivo, así que de las
    ventanas corrompidas basta renormalizar esa columna —localmente— y reutilizar
    las de los pares.
    """
    clean_p = np.asarray([prices[a:b + 1] for a, b in bounds], dtype=float)
    clean_z = np.asarray([scaled_clean[a:b] for a, b in bounds], dtype=np.float32)
    out = {"clean": extract(clean_p, clean_p, clean_z, cnn)}
    for family in families:
        for mode in modes:
            received = np.empty_like(clean_p)
            z = clean_z.copy()
            for i, (a, b) in enumerate(bounds):
                corrupted, _ = _inject(prices, a, b, family, mode, rng)
                received[i] = corrupted[a:b + 1]
                z[i, :, 0] = normalize_target_window(corrupted, a, b)
            out[f"{family}|{mode}"] = extract(received, clean_p, z, cnn)
    return out


def _labels(block, keys):
    x = np.vstack([block["clean"]] + [block[k] for k in keys])
    y = np.r_[np.zeros(len(block["clean"])),
              np.ones(sum(len(block[k]) for k in keys))]
    return x, y


def _combiner(seed: int) -> XGBClassifier:
    """Mismos hiperparámetros conservadores que el XGB ya usado en el proyecto."""
    return XGBClassifier(n_estimators=300, max_depth=3, min_child_weight=10,
                         learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                         reg_lambda=1.0, eval_metric="logloss",
                         random_state=seed, n_jobs=8)


def run(panel_path: Path, output_dir: Path, seeds=SEEDS) -> dict:
    prices, _ = pricelab.read_prices(panel_path)
    scaled = pricelab.normalize(prices)
    bounds = pricelab.window_bounds(scaled)
    data = pricelab.build(panel_path, seeds)
    n_tr, n_va, n_te = data["n"]["train"], data["n"]["validation"], data["n"]["test"]
    tr_b = bounds[:n_tr]
    va_b = bounds[n_tr:n_tr + n_va]
    te_b = bounds[n_tr + n_va:n_tr + n_va + n_te]
    purge = int(np.ceil(pricelab.WINDOW / pricelab.WINDOW_STRIDE)) - 1
    n_fit = int(0.70 * n_va)
    cal_start = n_fit + purge
    if n_va - cal_start < 20:
        raise ValueError("Validación insuficiente para separar ajuste y calibración")
    fit_b, cal_b = va_b[:n_fit], va_b[cal_start:]
    fit_z, cal_z = data["val_z"][:n_fit], data["val_z"][cal_start:]

    families = list(channel.PRICE_FAMILIES)
    modes = ("restated", "fresh")
    keys = [f"{f}|{m}" for f in families for m in modes]

    vintage_only: dict[str, list[float]] = {}
    vintage_fpr: list[float] = []
    combiner: dict[str, list[float]] = {}
    lofo: dict[str, list[float]] = {}
    singles: dict[str, dict[str, list[float]]] = {}
    union: dict[str, list[float]] = {}
    subsets: dict[str, dict[str, list[float]]] = {}
    importance: list[np.ndarray] = []

    for seed in seeds:
        cnn = base.fit_cnn(data["train_z"], fit_z, seed=seed)
        fit_block = build_block(prices, fit_b, scaled, cnn, families, modes,
                                np.random.default_rng(seed))
        cal_block = build_block(prices, cal_b, scaled, cnn, families, modes,
                                np.random.default_rng(seed + 10_000))
        test_block = build_block(prices, te_b, scaled, cnn, families, modes,
                                 np.random.default_rng(seed + 20_000))

        # --- vintage solo, threshold fitted on the held-out calibration block ---
        v = FEATURES.index("vintage_discrepancia")
        vintage_threshold = gate.calibration_threshold(
            cal_block["clean"][:, v], FP_TARGET)
        vintage_fpr.append(float(np.mean(test_block["clean"][:, v] > vintage_threshold)))
        for key in keys:
            vintage_only.setdefault(key, []).append(float(np.mean(
                test_block[key][:, v] > vintage_threshold)))

        # --- Each control uses a frozen threshold calibrated off-test. ---
        for j, name in enumerate(FEATURES):
            threshold = gate.calibration_threshold(cal_block["clean"][:, j], FP_TARGET)
            singles.setdefault(name, {}).setdefault("test_false_positive_rate", []).append(
                float(np.mean(test_block["clean"][:, j] > threshold)))
            for key in keys:
                singles[name].setdefault(key, []).append(float(np.mean(
                    test_block[key][:, j] > threshold)))

        # Union of controls: split the nominal calibration budget by Bonferroni.
        def union_flags(evaluated_block, share, subset=FEATURES):
            fired = np.zeros(len(evaluated_block), dtype=bool)
            for name in subset:
                j = FEATURES.index(name)
                threshold = gate.calibration_threshold(cal_block["clean"][:, j], share)
                fired |= evaluated_block[:, j] > threshold
            return fired

        # No tune the union against test FPR. Report the realized held-out rate.
        share = FP_TARGET / len(FEATURES)
        realized = float(np.mean(union_flags(test_block["clean"], share)))
        union.setdefault("per_control_share", []).append(share)
        union.setdefault("test_false_positive_rate", []).append(realized)
        for key in keys:
            union.setdefault(key, []).append(
                float(np.mean(union_flags(test_block[key], share))))

        # Subset unions are parallel comparisons, not a sequential router.
        for label, subset in GATE_SUBSETS.items():
            sh = FP_TARGET / len(subset)
            realized = float(np.mean(union_flags(test_block["clean"], sh, subset)))
            entry = subsets.setdefault(label, {})
            entry.setdefault("test_false_positive_rate", []).append(realized)
            for key in keys:
                entry.setdefault(key, []).append(
                    float(np.mean(union_flags(test_block[key], sh, subset))))

        # --- Fit on the tuning segment, calibrate on a later purged segment. ---
        x_tr, y_tr = _labels(fit_block, keys)
        model = _combiner(seed).fit(x_tr, y_tr)
        importance.append(model.feature_importances_)
        score = lambda m, mdl=model: mdl.predict_proba(m)[:, 1]
        calibration = score(cal_block["clean"])
        threshold = gate.calibration_threshold(calibration, FP_TARGET)
        combiner.setdefault("test_false_positive_rate", []).append(
            float(np.mean(score(test_block["clean"]) > threshold)))
        for key in keys:
            combiner.setdefault(key, []).append(float(np.mean(
                score(test_block[key]) > threshold)))

        # --- leave-one-family-out del combinador ---
        for held in families:
            kept = [k for k in keys if not k.startswith(f"{held}|")]
            x_h, y_h = _labels(fit_block, kept)
            partial = _combiner(seed).fit(x_h, y_h)
            s = lambda m, mdl=partial: mdl.predict_proba(m)[:, 1]
            lofo_threshold = gate.calibration_threshold(s(cal_block["clean"]), FP_TARGET)
            for mode in modes:
                lofo.setdefault(f"{held}|{mode}", []).append(float(np.mean(
                    s(test_block[f"{held}|{mode}"]) > lofo_threshold)))

    mean = lambda d: {k: float(np.mean(v)) for k, v in d.items()}
    output = {
        "protocol": {
            "source": str(panel_path),
            "representations": ["canal", "precio", "retorno_normalizado", "vintage"],
            "features": list(FEATURES),
            "families": families,
            "modes": {
                "restated": "el defecto reescribe historia ya publicada; vintage la ve",
                "fresh": f"el defecto solo toca las {SNAPSHOT_LAG} sesiones posteriores al snapshot; vintage es ciego por construcción",
            },
            "snapshot_lag_sessions": SNAPSHOT_LAG,
            "splits": "CNN train + model-selection validation; detector fit on early validation; threshold calibration on later purged validation; test used once",
            "combiner": "XGBClassifier(300, depth 3, min_child_weight 10, lr 0.05)",
            "threshold_protocol": "frozen validation order-statistic thresholds; nominal 5% target; realized test FPR reported, no clean-test feedback",
            "threshold_guarantee": "No distribution-free guarantee claimed; temporal dependence and drift remain.",
            "validation_model_selection_windows": int(n_fit),
            "validation_purged_windows": int(purge),
            "validation_calibration_windows": int(len(cal_b)),
            "single_observation_calibration_resolution": float(1.0 / len(cal_b)),
            "bonferroni_share_below_resolution": bool(FP_TARGET / len(FEATURES) < 1.0 / len(cal_b)),
            "n_windows": data["n"],
            "seeds": list(seeds),
            "target_false_positive_rate": FP_TARGET,
        },
        "vintage_alone_validation_threshold": {**mean(vintage_only),
                                               "test_false_positive_rate": float(np.mean(vintage_fpr))},
        "single_controls_validation_threshold": {n: mean(d) for n, d in singles.items()},
        "union_validation_threshold": mean(union),
        "gate_subsets_validation_threshold": {n: mean(d) for n, d in subsets.items()},
        "combiner_validation_threshold": mean(combiner),
        "combiner_leave_one_family_out_validation_threshold": mean(lofo),
        "feature_importance": dict(zip(FEATURES,
                                       np.mean(importance, axis=0).round(4).tolist())),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path,
                        default=ROOT / "data" / "panel_extendido_2026-09-09.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_representation_stack")
    args = parser.parse_args()
    r = run(args.panel, args.output)
    fams = r["protocol"]["families"]
    vin, comb, lofo = (r["vintage_alone_validation_threshold"], r["combiner_validation_threshold"],
                       r["combiner_leave_one_family_out_validation_threshold"])

    singles, uni = r["single_controls_validation_threshold"], r["union_validation_threshold"]
    keys = [f"{f}|{m}" for f in fams for m in ("restated", "fresh")]
    best_single = {k: max(singles[n][k] for n in singles) for k in keys}

    print(f"\nUmbrales congelados con objetivo nominal {FP_TARGET:.0%}; "
          f"FPR realizada OOS: combinador {comb['test_false_positive_rate']:.3f}, "
          f"unión {uni['test_false_positive_rate']:.3f}. No se reajustan usando el test.")
    print(f"  {'familia':18s} {'modo':10s} {'vintage':>9s} {'mejor1':>8s} "
          f"{'UNIÓN':>8s} {'XGB':>8s} {'XGB.LOFO':>9s}")
    for f in fams:
        for mode in ("restated", "fresh"):
            k = f"{f}|{mode}"
            print(f"  {f:18s} {mode:10s} {vin[k]:9.3f} {best_single[k]:8.3f} "
                  f"{uni[k]:8.3f} {comb[k]:8.3f} {lofo[k]:9.3f}")
    worst = lambda d: min(d[k] for k in keys)
    avg = lambda d: float(np.mean([d[k] for k in keys]))
    print(f"\n  {'':30s} {'media':>8s} {'peor':>8s}")
    for label, d in (("mejor control por familia (oráculo)", best_single),
                     ("UNIÓN de controles gateados", uni), ("combinador XGBoost", comb)):
        print(f"  {label:30s} {avg(d):8.3f} {worst(d):8.3f}")
    print("\nImportancia de features del combinador:")
    for k, v in sorted(r["feature_importance"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:24s} {v:.4f}")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
