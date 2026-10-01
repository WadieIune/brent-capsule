from __future__ import annotations

import argparse
import os
from typing import List

import numpy as np
import pandas as pd

from .backtest import walk_forward_backtest
from .config import load_config, save_json
from .cv_purged import single_holdout_split, walk_forward_folds
from .data_sources import is_series_bundle_mode, load_data_from_config
from .datasets import build_metadata_payload, prepare_dataset_from_bundle, prepare_dataset_from_config
from .evaluate import evaluate_predictions, predict_indices
from .feature_engineering import compute_market_features
from .outlier_control import fit_metric_templates
from .pattern_metrics import METRIC_COLUMNS
from .reporting import generate_reports
from .series_bundle import load_series_bundle, validate_series_bundle
from .torch_model import train_torch_pipeline


def refit_zscore(
    frame: pd.DataFrame,
    raw_wide: pd.DataFrame,
    feature_cols: List[str],
    fit_until: pd.Timestamp,
) -> tuple[pd.DataFrame, dict]:
    """Reestandariza las features usando SOLO datos hasta ``fit_until``.

    El bundle publicado traía un z-score calculado sobre la muestra completa, de
    modo que la escala del test se estimaba con datos del test. Aquí la media y
    la desviación se ajustan únicamente sobre las filas anteriores o iguales al
    último día de entrenamiento del fold, y se aplican después a todas las filas.

    Devuelve el frame reestandarizado y los estadísticos, para dejar constancia
    de la ventana de ajuste en el informe de cada fold.
    """
    out = frame.copy()
    dates = pd.to_datetime(frame["date"])
    fit_mask = (dates <= pd.Timestamp(fit_until)).to_numpy()
    if int(fit_mask.sum()) < 30:
        raise ValueError(
            f"Ventana de ajuste demasiado corta ({int(fit_mask.sum())} filas) hasta {fit_until}."
        )

    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for col in feature_cols:
        raw_name = col[3:] if col.startswith("z__") else col
        if raw_name not in raw_wide.columns:
            continue
        values = raw_wide[raw_name].to_numpy(dtype=float)
        mu = float(np.nanmean(values[fit_mask]))
        sd = float(np.nanstd(values[fit_mask], ddof=0))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0  # constante en el tramo de ajuste: se deja sin escalar
        out[col] = (values - mu) / sd
        means[raw_name] = mu
        stds[raw_name] = sd

    return out, {
        "fit_until": str(pd.Timestamp(fit_until).date()),
        "fit_rows": int(fit_mask.sum()),
        "n_features": len(means),
        "means": means,
        "stds": stds,
    }


def _set_split(window_table: pd.DataFrame, train, valid, test) -> pd.DataFrame:
    wt = window_table.copy().reset_index(drop=True)
    split = np.full(len(wt), "none", dtype=object)
    split[np.asarray(train, dtype=int)] = "train"
    split[np.asarray(valid, dtype=int)] = "valid"
    split[np.asarray(test, dtype=int)] = "test"
    wt["split"] = split
    return wt


def run(config_path: str | None = None) -> dict:
    config = load_config(config_path)

    if is_series_bundle_mode(config):
        bundle = load_series_bundle(config)
        validation = validate_series_bundle(bundle, lookback=int(config["dataset"]["lookback"]))
        frame, window_table, feature_cols, extra = prepare_dataset_from_bundle(config, bundle)
    else:
        raw_df = load_data_from_config(config)
        market_df = compute_market_features(
            raw_df,
            target_col=str(config["data"].get("target_col", "brent_close")),
            resample_rule=str(config["data"].get("resample_rule", "B")),
        )
        frame, window_table, feature_cols = prepare_dataset_from_config(config, market_df)
        validation = {}
        extra = {"mode": "csv_or_download", "selected_feature_count": len(feature_cols)}

    window_table = window_table.reset_index(drop=True)
    output_cfg = config["output"]
    model_dir = output_cfg["model_dir"]
    metadata_dir = output_cfg["metadata_dir"]
    report_dir = output_cfg["report_dir"]
    for d in (model_dir, metadata_dir, report_dir):
        os.makedirs(d, exist_ok=True)

    horizon = int(config["dataset"]["horizon"])
    sr_horizon = int(config["dataset"].get("support_resistance_horizon", horizon))
    max_future = max(horizon, sr_horizon)
    embargo = int(config["cv"].get("embargo", config["dataset"].get("embargo", 0)))
    scheme = str(config["cv"].get("scheme", "single"))

    # Plantillas de métricas (para control de outliers): se ajustan sobre un train
    # purgado de referencia (holdout único), independientemente del esquema de CV.
    ref = single_holdout_split(
        window_table, max_future=max_future, embargo=embargo,
        train_fraction=float(config["dataset"].get("train_split", 0.72)),
        valid_fraction=float(config["dataset"].get("valid_split", 0.08)),
    )
    ref_table = _set_split(window_table, ref.train, ref.valid, ref.test)
    window_table.to_csv(os.path.join(metadata_dir, output_cfg["window_table_name"]), index=False)
    # Las fechas de cada partición no se estaban guardando y hubo que
    # reconstruirlas casando tensores contra la matriz z-score. En una cápsula
    # reproducible tienen que constar en el manifiesto.
    if "end_date" in window_table.columns:
        wt_dates = pd.to_datetime(window_table["end_date"])
        extra = dict(extra)
        extra["window_first_date"] = str(wt_dates.min().date())
        extra["window_last_date"] = str(wt_dates.max().date())
        n_tr = extra.get("precomputed_train_count")
        if isinstance(n_tr, int) and 0 < n_tr <= len(wt_dates):
            extra["train_date_range"] = [str(wt_dates.iloc[0].date()),
                                         str(wt_dates.iloc[n_tr - 1].date())]
            extra["test_date_range"] = [str(wt_dates.iloc[n_tr].date()),
                                        str(wt_dates.iloc[-1].date())]
    save_json(os.path.join(metadata_dir, "dataset_metadata.json"), build_metadata_payload(feature_cols, config, extra=extra))
    if validation:
        save_json(os.path.join(metadata_dir, output_cfg.get("validation_name", "bundle_validation.json")), validation)
    templates = fit_metric_templates(ref_table[ref_table["split"] == "train"], metric_cols=METRIC_COLUMNS)
    save_json(os.path.join(metadata_dir, output_cfg["metric_template_name"]), templates)

    # Construye los folds según el esquema de validación.
    if scheme == "walk_forward":
        folds = walk_forward_folds(
            window_table,
            n_splits=int(config["cv"].get("n_splits", 5)),
            max_future=max_future,
            embargo=embargo,
            valid_fraction=float(config["cv"].get("valid_fraction", 0.15)),
            expanding=bool(config["cv"].get("expanding", True)),
            min_train_size=int(config["cv"].get("min_train_size", 128)),
            rolling_train_size=config["cv"].get("rolling_train_size"),
        )
    else:
        folds = [ref]

    # Reestandarización por fold: la escala se ajusta solo con el tramo de
    # entrenamiento del fold, nunca con validación ni test.
    # DESACTIVADA POR DEFECTO: el capsule debe reproducir los `results/`
    # publicados, que usan la escala global del bundle. Es una mejora OPT-IN
    # y aún SIN VALIDAR (ver docs/ESTADO_2026-09-11_CONTINUAR.md); actívala con
    # `cv.refit_zscore_per_fold: true` solo en experimentos, no en la repro.
    refit_per_fold = (
        bool(config["cv"].get("refit_zscore_per_fold", False))
        and is_series_bundle_mode(config)
    )
    scaling_log: List[dict] = []

    fold_reports: List[dict] = []
    oos_frames: List[pd.DataFrame] = []
    for fold in folds:
        wt = _set_split(window_table, fold.train, fold.valid, fold.test)
        fid = None if scheme == "single" else fold.fold_id

        fold_frame = frame
        if refit_per_fold:
            fit_until = pd.to_datetime(wt.loc[wt["split"] == "train", "end_date"]).max()
            fold_frame, stats = refit_zscore(frame, bundle.raw_wide, feature_cols, fit_until)
            stats["fold_id"] = fold.fold_id
            scaling_log.append({k: v for k, v in stats.items() if k not in ("means", "stds")})
            print(f"[zscore] fold {fold.fold_id}: escala ajustada con "
                  f"{stats['fit_rows']} filas hasta {stats['fit_until']}")

        report = train_torch_pipeline(
            frame=fold_frame, table=wt, feature_cols=feature_cols, config=config,
            output_dir=model_dir, fold_id=fid,
        )
        fold_reports.append(report)
        merged = predict_indices(report["model_path"], fold_frame, wt, fold.test, feature_cols, config)
        merged["fold_id"] = fold.fold_id
        oos_frames.append(merged)

    oos = pd.concat(oos_frames, ignore_index=True).sort_values("end").reset_index(drop=True)
    oos.to_csv(os.path.join(report_dir, "torch_oos_predictions.csv"), index=False)

    eval_summary = evaluate_predictions(oos)
    summary: dict = {
        "scheme": scheme,
        "n_folds": len(folds),
        "embargo": embargo,
        "max_future": max_future,
        "zscore_refit_per_fold": bool(refit_per_fold),
        "zscore_scaling_windows": scaling_log,
        "evaluation": eval_summary,
        "folds": [
            {"fold_id": r.get("fold_id"), "best_valid_fine": r.get("best_valid_fine"),
             "train_windows": r.get("train_windows"), "valid_windows": r.get("valid_windows")}
            for r in fold_reports
        ],
    }
    if bool(config["backtest"].get("enabled", True)):
        summary["backtest"] = walk_forward_backtest(oos, config)

    save_json(os.path.join(report_dir, "torch_walkforward_summary.json"), summary)

    # Salida académica en Excel + manifiesto de reproducibilidad (aditivo).
    # `generate_reports` está diseñado para no lanzar nunca: registra y degrada.
    reports = generate_reports(config, summary, oos, report_dir)
    summary["reports"] = reports
    if reports.get("excel_path"):
        print(f"[reporting] Excel generado en: {reports['excel_path']}")
    elif reports.get("csv_fallback"):
        print(f"[reporting] openpyxl no disponible; CSVs en: {reports.get('csv_fallback')}")
    if reports.get("error"):
        print(f"[reporting] aviso: {reports['error']}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entrenamiento PyTorch para BRENT chartism + outliers")
    parser.add_argument("--config", type=str, default=None, help="Ruta al fichero de configuración (.json, .yaml o .yml)")
    args = parser.parse_args()
    run(args.config)
