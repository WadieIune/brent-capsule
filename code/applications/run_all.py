"""Orquestador de las aplicaciones de Riesgo de Mercado (harness ARF).

Ejecuta cada experimento a través del `Harness`, registra un `run_manifest.json`
por experimento y escribe un resumen consolidado. Sigue el bucle del framework:
observar → planificar → ejecutar → verificar → comparar → decidir → registrar.

Uso:
  # con la serie del proyecto (data/brent_fred_daily.csv) si existe:
  python run_all.py

  # forzar datos sintéticos (para verificar sin la serie propietaria):
  python run_all.py --synthetic

  # split temporal por fecha y salida a un directorio concreto:
  python run_all.py --cutoff 2020-08-20 --out outputs

Salidas (en `outputs/` salvo --out):
  - <experiment_id>/run_manifest.json   (uno por experimento)
  - summary.json                        (consolidado de decisiones y métricas)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from harness import Harness  # noqa: E402
from experiments import ALL_EXPERIMENTS  # noqa: E402


def build_config(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "prices_path": args.prices,
        "synthetic": bool(args.synthetic),
        "cutoff": args.cutoff,
        "alpha": args.alpha,
        "horizon": args.horizon,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prices", default=None, help="CSV de precios Brent (date,BRENT)")
    ap.add_argument("--synthetic", action="store_true", help="usa serie sintética")
    ap.add_argument("--cutoff", default=None, help="fecha de corte del split temporal (YYYY-MM-DD)")
    ap.add_argument("--alpha", type=float, default=0.99, help="nivel de confianza del VaR")
    ap.add_argument("--horizon", type=int, default=10, help="horizonte del forecast de vol")
    ap.add_argument("--out", default=os.path.join(_HERE, "outputs"), help="directorio de salidas")
    ap.add_argument("--only", default=None, help="ejecuta solo un experimento por id")
    args = ap.parse_args(argv)

    try:  # consolas Windows cp1252: evita UnicodeEncodeError al imprimir
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    config = build_config(args)
    harness = Harness(out_dir=args.out, task_id="risk_applications")

    experiments = [E() for E in ALL_EXPERIMENTS]
    if args.only:
        experiments = [e for e in experiments if e.id == args.only]
        if not experiments:
            print(f"[run_all] id desconocido: {args.only}")
            return 2

    manifests: List[Dict[str, Any]] = []
    for exp in experiments:
        manifests.append(harness.run(exp, config=config))

    summary = {
        "task_id": "risk_applications",
        "config": config,
        "experiments": [
            {
                "id": m["experiment_id"],
                "title": m.get("title"),
                "decision": m.get("decision"),
                "notes": m.get("notes"),
                "error": m.get("error"),
                "manifest": m.get("manifest_path"),
            }
            for m in manifests
        ],
    }
    os.makedirs(args.out, exist_ok=True)
    summary_path = os.path.join(args.out, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)

    print("\n=== Resumen de aplicaciones ===")
    for e in summary["experiments"]:
        print(f"  [{e['decision']:>7}] {e['id']:<22} {e['notes'] or e['error'] or ''}")
    print(f"\n[run_all] resumen -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())