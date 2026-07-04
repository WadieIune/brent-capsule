"""Generación de reportes en Excel y manifiesto de reproducibilidad.

Este módulo es *aditivo*: no modifica las salidas existentes (JSON/CSV) del
pipeline. Toma el diccionario `summary` producido por `train_torch.run`, la
tabla de predicciones out-of-sample y la configuración efectiva del experimento,
y produce:

  1. Un libro Excel (`.xlsx`) con múltiples hojas listo para presentación
     académica: incluye TODOS los parámetros de configuración del experimento
     (imprescindibles para que una revista pueda validar la reproducibilidad),
     el entorno de ejecución, y las métricas de clasificación, regresión y
     backtest (Sharpe, PSR, Deflated Sharpe Ratio, PBO/CSCV).
  2. Un `run_manifest.json` con la configuración resuelta + información del
     entorno (versiones, commit de git, timestamp, semilla), que actúa como
     registro de reproducibilidad del run.

Robustez: si `openpyxl` no está disponible, se degrada con elegancia a una
exportación en CSV (una por hoja) sin interrumpir el pipeline. Ninguna
excepción de este módulo debe abortar el entrenamiento.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades de aplanado / entorno
# ---------------------------------------------------------------------------

def flatten_config(config: Dict[str, Any], _prefix: str = "") -> List[Dict[str, Any]]:
    """Aplana el config anidado en filas (seccion, parametro, valor)."""
    rows: List[Dict[str, Any]] = []
    for key, value in config.items():
        full_key = f"{_prefix}.{key}" if _prefix else str(key)
        if isinstance(value, dict):
            rows.extend(flatten_config(value, _prefix=full_key))
        else:
            section = full_key.split(".")[0]
            parameter = full_key[len(section) + 1:] if "." in full_key else full_key
            if isinstance(value, (list, tuple)):
                value = json.dumps(list(value), ensure_ascii=False)
            rows.append({"seccion": section, "parametro": parameter, "valor": value})
    return rows


def _git_commit(cwd: Optional[str] = None) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def environment_info() -> Dict[str, Any]:
    """Recopila versiones y plataforma para trazabilidad del experimento."""
    info: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "git_commit": _git_commit(),
    }
    try:
        import torch  # type: ignore

        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["cuda_device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        info["torch_version"] = None
        info["cuda_available"] = None
        info["cuda_device"] = None
    return info


# ---------------------------------------------------------------------------
# Construcción de tablas a partir del summary
# ---------------------------------------------------------------------------

def _kv_frame(data: Dict[str, Any], key_name: str = "metrica", val_name: str = "valor") -> pd.DataFrame:
    rows = [{key_name: k, val_name: v} for k, v in data.items() if not isinstance(v, (dict, list))]
    return pd.DataFrame(rows)


def _run_info_frame(config: Dict[str, Any], summary: Dict[str, Any], env: Dict[str, Any]) -> pd.DataFrame:
    bt = summary.get("backtest", {}) or {}
    evaluation = summary.get("evaluation", {}) or {}
    classification = evaluation.get("classification", {}) or {}
    info = {
        "esquema_validacion": summary.get("scheme"),
        "n_folds": summary.get("n_folds"),
        "embargo": summary.get("embargo"),
        "max_future": summary.get("max_future"),
        "n_ventanas_oos": evaluation.get("n"),
        "accuracy": classification.get("accuracy"),
        "balanced_accuracy": classification.get("balanced_accuracy"),
        "macro_f1": classification.get("macro_f1"),
        "backtest_signal": bt.get("signal"),
        "sharpe_annual": (bt.get("strategy", {}) or {}).get("sharpe_annual"),
        "deflated_sharpe_ratio": (bt.get("deflated_sharpe", {}) or {}).get("deflated_sharpe_ratio"),
        "pbo": (bt.get("pbo", {}) or {}).get("pbo"),
        "device": config.get("training", {}).get("device"),
        "image_size": config.get("dataset", {}).get("image_size"),
        "lookback": config.get("dataset", {}).get("lookback"),
        "seed": config.get("training", {}).get("seed"),
        "timestamp_utc": env.get("timestamp_utc"),
        "torch_version": env.get("torch_version"),
        "cuda_available": env.get("cuda_available"),
        "git_commit": env.get("git_commit"),
    }
    return pd.DataFrame([{"campo": k, "valor": v} for k, v in info.items()])


def _classification_frames(classification: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    overall = {k: classification.get(k) for k in ("accuracy", "balanced_accuracy", "macro_f1", "n")}
    frames["overall"] = pd.DataFrame([{"metrica": k, "valor": v} for k, v in overall.items()])

    per_class = classification.get("per_class", {}) or {}
    rows = []
    for label, m in per_class.items():
        rows.append({
            "clase": label,
            "precision": m.get("precision"),
            "recall": m.get("recall"),
            "f1": m.get("f1"),
            "soporte": m.get("support"),
        })
    frames["per_class"] = pd.DataFrame(rows)

    cm = classification.get("confusion_matrix")
    labels = classification.get("labels")
    if cm is not None and labels is not None:
        cm_df = pd.DataFrame(cm, index=[f"real_{l}" for l in labels], columns=[f"pred_{l}" for l in labels])
        frames["confusion_matrix"] = cm_df.reset_index().rename(columns={"index": "clase_real"})
    return frames


def _backtest_frames(bt: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    strategy = bt.get("strategy", {}) or {}
    bh = bt.get("buy_and_hold", {}) or {}
    keys = sorted(set(strategy) | set(bh))
    rows = [{"metrica": k, "estrategia": strategy.get(k), "buy_and_hold": bh.get(k)} for k in keys]
    frames["performance"] = pd.DataFrame(rows)

    robustness = {}
    robustness.update({f"dsr.{k}": v for k, v in (bt.get("deflated_sharpe", {}) or {}).items()})
    robustness.update({f"pbo.{k}": v for k, v in (bt.get("pbo", {}) or {}).items()
                       if not isinstance(v, list)})
    robustness["n_oos"] = bt.get("n_oos")
    robustness["signal"] = bt.get("signal")
    robustness["fee_bps"] = bt.get("fee_bps")
    frames["robustness"] = pd.DataFrame([{"metrica": k, "valor": v} for k, v in robustness.items()])

    sr_fold = bt.get("sharpe_per_fold")
    if sr_fold is not None:
        frames["sharpe_per_fold"] = pd.DataFrame(
            {"fold": list(range(len(sr_fold))), "sharpe_annual": sr_fold}
        )
    return frames


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def build_run_manifest(config: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """Registro de reproducibilidad: config resuelta + entorno + resumen clave."""
    env = environment_info()
    evaluation = summary.get("evaluation", {}) or {}
    classification = evaluation.get("classification", {}) or {}
    bt = summary.get("backtest", {}) or {}
    return {
        "environment": env,
        "config": config,
        "headline_metrics": {
            "scheme": summary.get("scheme"),
            "n_folds": summary.get("n_folds"),
            "n_oos": evaluation.get("n"),
            "accuracy": classification.get("accuracy"),
            "balanced_accuracy": classification.get("balanced_accuracy"),
            "macro_f1": classification.get("macro_f1"),
            "sharpe_annual": (bt.get("strategy", {}) or {}).get("sharpe_annual"),
            "deflated_sharpe_ratio": (bt.get("deflated_sharpe", {}) or {}).get("deflated_sharpe_ratio"),
            "pbo": (bt.get("pbo", {}) or {}).get("pbo"),
        },
    }


def _write_sheets_csv(sheets: Dict[str, pd.DataFrame], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, df in sheets.items():
        path = os.path.join(out_dir, f"{name}.csv")
        df.to_csv(path, index=False)
        written.append(path)
    return written


def _collect_sheets(
    config: Dict[str, Any],
    summary: Dict[str, Any],
    oos_df: Optional[pd.DataFrame],
    env: Dict[str, Any],
) -> Dict[str, pd.DataFrame]:
    evaluation = summary.get("evaluation", {}) or {}
    classification = evaluation.get("classification", {}) or {}
    regression = evaluation.get("regression", {}) or {}
    bt = summary.get("backtest", {}) or {}

    sheets: Dict[str, pd.DataFrame] = {}
    sheets["00_Resumen"] = _run_info_frame(config, summary, env)
    sheets["01_Configuracion"] = pd.DataFrame(flatten_config(config))
    sheets["02_Entorno"] = pd.DataFrame([{"campo": k, "valor": v} for k, v in env.items()])

    if classification:
        cframes = _classification_frames(classification)
        sheets["03_Clasificacion"] = cframes.get("overall", pd.DataFrame())
        if "per_class" in cframes:
            sheets["04_Clasif_PorClase"] = cframes["per_class"]
        if "confusion_matrix" in cframes:
            sheets["05_MatrizConfusion"] = cframes["confusion_matrix"]

    if regression:
        sheets["06_Regresion"] = _kv_frame(regression)

    if bt:
        bframes = _backtest_frames(bt)
        if "performance" in bframes:
            sheets["07_Backtest"] = bframes["performance"]
        if "robustness" in bframes:
            sheets["08_Backtest_Robustez"] = bframes["robustness"]
        if "sharpe_per_fold" in bframes:
            sheets["09_SharpePorFold"] = bframes["sharpe_per_fold"]

    folds = summary.get("folds")
    if folds:
        sheets["10_Folds"] = pd.DataFrame(folds)

    if oos_df is not None and len(oos_df) > 0:
        # Excel limita a ~1.048.576 filas; el OOS es muy inferior, pero se acota.
        sheets["11_Predicciones_OOS"] = oos_df.head(1_000_000)

    return sheets


def generate_reports(
    config: Dict[str, Any],
    summary: Dict[str, Any],
    oos_df: Optional[pd.DataFrame],
    report_dir: str,
    excel_name: str = "brent_resultados.xlsx",
    manifest_name: str = "run_manifest.json",
) -> Dict[str, Any]:
    """Genera el Excel y el manifiesto. Nunca lanza: registra y degrada."""
    result: Dict[str, Any] = {"excel_path": None, "manifest_path": None, "csv_fallback": None, "error": None}
    try:
        os.makedirs(report_dir, exist_ok=True)
        env = environment_info()

        # Manifiesto de reproducibilidad (config + entorno).
        manifest_path = os.path.join(report_dir, manifest_name)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(build_run_manifest(config, summary), fh, indent=2, ensure_ascii=False, default=str)
        result["manifest_path"] = manifest_path

        sheets = _collect_sheets(config, summary, oos_df, env)

        try:
            import openpyxl  # noqa: F401
            excel_path = os.path.join(report_dir, excel_name)
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                for name, df in sheets.items():
                    safe = name[:31]  # límite de nombre de hoja en Excel
                    (df if df is not None else pd.DataFrame()).to_excel(writer, sheet_name=safe, index=False)
            result["excel_path"] = excel_path
        except ImportError:
            fallback_dir = os.path.join(report_dir, "excel_csv_fallback")
            result["csv_fallback"] = _write_sheets_csv(sheets, fallback_dir)
            result["error"] = "openpyxl no instalado: se exportó a CSV. Instala openpyxl para el .xlsx."
    except Exception as exc:  # pragma: no cover - salvaguarda total
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
