"""Harness engineering para los experimentos de aplicaciones (ARF).

Envuelve cada experimento en una ejecución reproducible siguiendo el patrón del
*Agentic Research Framework* (`01_ENGINEERING/HARNESS_ENGINEERING.md`):

    Input spec → Pre-flight checks → Execution → Logging → Validation →
    Comparison (baseline) → Decision → Artifact storage

Cada run registra los campos mínimos del harness (task/experiment id, timestamp,
inputs, config, seed, comando, outputs, métricas, errores y decisión) en un
`run_manifest.json` por experimento, para que cualquier afirmación quede
respaldada por evidencia reproducible.

No depende de nada del proyecto: es infraestructura pura (stdlib + numpy).
"""
from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

SEED = 42


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_seeds(seed: int = SEED) -> None:
    """Fija semillas deterministas (coherente con la cápsula: seed=42)."""
    os.environ["PYTHONHASHSEED"] = "0"
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:  # pragma: no cover - numpy siempre presente en este repo
        pass


@dataclass
class RunContext:
    """Especificación de entrada de un run (input spec + configuración + seed)."""

    experiment_id: str
    config: Dict[str, Any] = field(default_factory=dict)
    out_dir: str = "outputs"
    seed: int = SEED
    inputs: List[str] = field(default_factory=list)
    task_id: str = "risk_applications"
    logger: Callable[[str], None] = print

    def log(self, msg: str) -> None:
        line = f"[{self.experiment_id}] {msg}"
        try:
            self.logger(line)
        except UnicodeEncodeError:  # consolas Windows cp1252 con caracteres unicode
            self.logger(line.encode("ascii", "replace").decode("ascii"))

    def experiment_dir(self) -> str:
        d = os.path.join(self.out_dir, self.experiment_id)
        os.makedirs(d, exist_ok=True)
        return d


@dataclass
class ExperimentResult:
    """Salida estructurada de un experimento."""

    metrics: Dict[str, Any] = field(default_factory=dict)
    baseline: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    decision: str = "review"          # accept | reject | review | error
    notes: str = ""
    preflight_issues: List[str] = field(default_factory=list)


class Experiment:
    """Contrato mínimo de un experimento. Subclasear y sobreescribir `run`.

    - `id`     : identificador estable del experimento.
    - `title`  : descripción legible.
    - `preflight(ctx)` : devuelve una lista de problemas (vacía si todo OK).
    - `run(ctx)`       : ejecuta y devuelve un `ExperimentResult`.
    """

    id: str = "experiment"
    title: str = ""

    def preflight(self, ctx: RunContext) -> List[str]:  # pragma: no cover - override
        return []

    def run(self, ctx: RunContext) -> ExperimentResult:  # pragma: no cover - override
        raise NotImplementedError


class Harness:
    """Ejecuta experimentos y persiste el manifiesto reproducible por run."""

    def __init__(self, out_dir: str = "outputs", seed: int = SEED,
                 task_id: str = "risk_applications",
                 logger: Callable[[str], None] = print):
        self.out_dir = out_dir
        self.seed = seed
        self.task_id = task_id
        self.logger = logger
        os.makedirs(out_dir, exist_ok=True)

    def run(self, experiment: Experiment, config: Optional[Dict[str, Any]] = None,
            inputs: Optional[List[str]] = None) -> Dict[str, Any]:
        config = dict(config or {})
        inputs = list(inputs or [])
        set_seeds(self.seed)

        ctx = RunContext(
            experiment_id=experiment.id,
            config=config,
            out_dir=self.out_dir,
            seed=self.seed,
            inputs=inputs,
            task_id=self.task_id,
            logger=self.logger,
        )
        ctx.log(f"start · {experiment.title or experiment.id}")

        manifest: Dict[str, Any] = {
            "task_id": self.task_id,
            "experiment_id": experiment.id,
            "title": experiment.title,
            "timestamp_utc": utc_now(),
            "inputs": inputs,
            "config": config,
            "seed": self.seed,
            "command": " ".join([os.path.basename(sys.executable)] + sys.argv),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        }

        # --- Pre-flight checks ------------------------------------------------
        issues = experiment.preflight(ctx)
        manifest["preflight_issues"] = issues
        if issues:
            for it in issues:
                ctx.log(f"pre-flight: {it}")

        # --- Execution + timing ----------------------------------------------
        t0 = time.time()
        try:
            result = experiment.run(ctx)
            manifest["metrics"] = result.metrics
            manifest["baseline"] = result.baseline
            manifest["artifacts"] = result.artifacts
            manifest["decision"] = result.decision
            manifest["notes"] = result.notes
            if result.preflight_issues:
                manifest["preflight_issues"] = list(
                    dict.fromkeys(issues + result.preflight_issues)
                )
            manifest["error"] = None
        except Exception as exc:  # noqa: BLE001 - se registra el fallo, no se oculta
            manifest["metrics"] = {}
            manifest["decision"] = "error"
            manifest["error"] = f"{type(exc).__name__}: {exc}"
            manifest["traceback"] = traceback.format_exc()
            ctx.log(f"ERROR {manifest['error']}")
        manifest["elapsed_seconds"] = round(time.time() - t0, 3)

        # --- Artifact storage -------------------------------------------------
        exp_dir = ctx.experiment_dir()
        man_path = os.path.join(exp_dir, "run_manifest.json")
        with open(man_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False, default=str)
        manifest["manifest_path"] = man_path
        ctx.log(f"decision={manifest['decision']} · manifest -> {man_path} "
                f"({manifest['elapsed_seconds']}s)")
        return manifest