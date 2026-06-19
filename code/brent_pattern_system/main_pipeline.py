from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline completo BRENT CNN chartism + outliers")
    parser.add_argument("--config", type=str, default=None, help="Ruta al JSON de configuración")
    parser.add_argument("--backend", type=str, default="torch", choices=["tensorflow", "torch", "both"])
    parser.add_argument("--train", action="store_true", help="Ejecuta entrenamiento")
    parser.add_argument("--infer", action="store_true", help="Ejecuta inferencia")
    args = parser.parse_args()

    # Importaciones perezosas: la ruta TensorFlow es opcional y no debe romper la
    # ejecución en máquinas que solo tienen PyTorch instalado.
    if args.backend in {"tensorflow", "both"} and args.train:
        from .train_tf import run as run_tf
        run_tf(args.config)
    if args.backend in {"torch", "both"} and args.train:
        from .train_torch import run as run_torch
        run_torch(args.config)
    if args.backend in {"tensorflow", "both"} and args.infer:
        from .inference import run as run_inference
        run_inference(args.config, backend="tensorflow")
    if args.backend in {"torch", "both"} and args.infer:
        from .inference import run as run_inference
        run_inference(args.config, backend="torch")


if __name__ == "__main__":
    main()
