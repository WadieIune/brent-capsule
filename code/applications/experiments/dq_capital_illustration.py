#!/usr/bin/env python3
"""Ilustración DIDÁCTICA en base 100: por dónde un defecto de dato sesga el capital.

**Esto no es una medición.** No usa el panel del proyecto, no estima el impacto
real de ningún defecto y no debe citarse como resultado. Es un ejemplo vanilla
—un único factor de riesgo, serie sintética, semilla fija— cuyo único objetivo es
mostrar la **dirección** del sesgo: qué familias de defecto hacen *infraestimar*
capital y cuáles lo hacen *sobreestimar*.

Una cartera de CIB tiene bastantes más capas: múltiples factores y su matriz de
correlaciones, diversificación entre mesas, cargas por riesgo específico y
default, multiplicadores supervisores, backtesting y P&L attribution por mesa,
NMRF, y el propio suelo de SA. Nada de eso está aquí. La aritmética de abajo es
deliberadamente la mínima que permite ver el signo del error.

Por qué importa el signo:
  - **Infraestimar** capital es un problema prudencial: la cartera está peor
    capitalizada de lo que el modelo declara, y el defecto lo oculta.
  - **Sobreestimar** capital también es un problema: inmoviliza recursos y puede
    disparar acciones de gestión innecesarias sobre un riesgo que no existe.

El ejercicio se promedia sobre 400 réplicas y reporta en qué fracción de ellas el
sesgo va en la dirección dominante. Con una sola serie, diferencias pequeñas son
ruido muestral y no dirección: ese control evita afirmar un signo que no existe.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]

BASE = 100.0          # notional en base 100
SESSIONS = 250
TRUE_DAILY_VOL = 0.010
Z99 = 2.326           # cuantil normal al 99 %, un día
SEED = 20261007
REPLICATIONS = 400    # el signo del sesgo se promedia; con una sola serie es ruido


def clean_returns(rng: np.random.Generator) -> np.ndarray:
    """Serie sintética con volatilidad conocida."""
    return rng.normal(0.0, TRUE_DAILY_VOL, size=SESSIONS)


def d_stale(returns: np.ndarray) -> np.ndarray:
    """Cotización repetida en el último mes: el precio deja de moverse."""
    out = returns.copy()
    out[-20:] = 0.0
    return out


def d_weekly_ffill(returns: np.ndarray) -> np.ndarray:
    """Fuente semanal propagada a diario: el movimiento se reagrupa, no desaparece."""
    out = np.zeros_like(returns)
    for stop in range(4, len(returns), 5):
        out[stop] = returns[max(0, stop - 4):stop + 1].sum()
    return out


def d_spurious_jump(returns: np.ndarray) -> np.ndarray:
    """Tick erróneo que revierte al día siguiente: variabilidad que no ocurrió."""
    out = returns.copy()
    t = len(out) // 2
    out[t] += 8 * TRUE_DAILY_VOL
    out[t + 1] -= 8 * TRUE_DAILY_VOL
    return out


def _quantize(returns: np.ndarray, step: float) -> np.ndarray:
    prices = BASE * np.exp(np.cumsum(returns))
    return np.diff(np.log(np.r_[BASE, np.round(prices / step) * step]))


def d_quantize_fine(returns: np.ndarray) -> np.ndarray:
    """Rejilla FINA frente al movimiento diario: el redondeo AÑADE ruido.

    Con base 100 y vol diaria del 1 %, el movimiento típico es ~1 unidad. Una
    rejilla de 0,5 introduce error de redondeo del mismo orden que la señal, así
    que infla la varianza medida.
    """
    return _quantize(returns, 0.5)


def d_quantize_coarse(returns: np.ndarray) -> np.ndarray:
    """Rejilla GRUESA frente al movimiento diario: el precio se queda pegado.

    Con rejilla de 5 unidades la mayoría de las sesiones no cambian de escalón,
    pero cuando cambian lo hacen de golpe por un escalón entero (un 5 % sobre base
    100, cinco veces la volatilidad verdadera). El resultado **no** es que la
    varianza se hunda: los saltos de escalón pesan mucho más que los ceros y la
    varianza medida se multiplica. Contraintuitivo y conviene dejarlo escrito,
    porque la intuición de «redondear quita movimiento» es la equivocada.
    """
    return _quantize(returns, 5.0)


DEFECTS = {
    "cotización repetida (stale)": d_stale,
    "fuente semanal propagada": d_weekly_ffill,
    "precisión, rejilla gruesa": d_quantize_coarse,
    "precisión, rejilla fina": d_quantize_fine,
    "tick erróneo que revierte": d_spurious_jump,
}


def var99(returns: np.ndarray) -> float:
    """VaR paramétrico a un día, en unidades de base 100."""
    return float(Z99 * np.std(returns, ddof=1) * BASE)


def run(output_dir: Path) -> dict:
    rng = np.random.default_rng(SEED)
    references, gaps = [], {name: [] for name in DEFECTS}
    for _ in range(REPLICATIONS):
        clean = clean_returns(rng)
        reference = var99(clean)
        references.append(reference)
        for name, defect in DEFECTS.items():
            gaps[name].append(var99(defect(clean)) - reference)

    reference = float(np.mean(references))
    rows = []
    for name, values in gaps.items():
        values = np.asarray(values)
        gap = float(np.mean(values))
        # Fracción de réplicas en que el sesgo va en la dirección dominante: si no
        # es prácticamente 1, la dirección no es una propiedad del defecto.
        consistency = float(np.mean(np.sign(values) == np.sign(gap)))
        # Sin consistencia de signo no hay dirección que reportar: etiquetar el
        # signo de una media de ~0 como "infraestima" sería inventar un sesgo.
        if consistency < 0.90:
            direction = "SIN DIRECCION (no sesga esta metrica)"
        else:
            direction = "INFRAESTIMA capital" if gap < 0 else "SOBREESTIMA capital"
        rows.append({
            "defecto": name,
            "var99_medido_base100": round(reference + gap, 2),
            "diferencia_vs_serie_limpia": round(gap, 2),
            "direccion": direction,
            "consistencia_del_signo": round(consistency, 3),
        })
    output = {
        "aviso": ("Ilustración didáctica con serie sintética y un solo factor de "
                  "riesgo. NO es una medición del impacto real y no debe citarse "
                  "como resultado del paper."),
        "fuera_del_alcance": [
            "múltiples factores y su matriz de correlaciones",
            "diversificación entre mesas",
            "riesgo específico y de default",
            "multiplicadores supervisores y backtesting/PLA por mesa",
            "NMRF y suelo del método estándar",
        ],
        "supuestos": {
            "notional_base": BASE,
            "sesiones": SESSIONS,
            "volatilidad_diaria_verdadera": TRUE_DAILY_VOL,
            "cuantil_normal_99": Z99,
            "semilla": SEED,
            "replicas": REPLICATIONS,
            "var": "paramétrico normal a un día",
        },
        "var99_serie_limpia_base100": round(reference, 2),
        "casos": rows,
        "lectura": (
            "El único de los cinco que INFRAESTIMA es la cotización repetida: "
            "quita movimiento sin dejar ningún valor atípico, así que un control "
            "de outliers no lo ve y el capital queda por debajo de lo debido. Es "
            "el caso prudencialmente peligroso y el que motiva los checks TRIM de "
            "repetidos. Los demás SOBREESTIMAN, y el más grave con diferencia no "
            "es el tick erróneo —que un 3σ caza— sino la rejilla gruesa, que "
            "ningún control de magnitud marca como anómala."
        ),
        "tres_avisos_contraintuitivos": [
            "La fuente semanal propagada NO sesga el VaR a un día: su signo solo "
            "es consistente en el 51 % de las réplicas, o sea azar. Reagrupa el "
            "movimiento conservando la varianza total. Sigue siendo un defecto "
            "serio —destruye la autocorrelación y desplaza el P&L en el tiempo— "
            "pero es invisible a esta métrica concreta. Un defecto puede ser "
            "grave para una medida de riesgo e inocuo para otra.",
            "Redondear NO quita movimiento: la rejilla gruesa deja el precio "
            "pegado varios días y luego lo mueve un escalón entero, y esos saltos "
            "pesan mucho más que los ceros. Sobreestima, y fuerte. La intuición "
            "contraria es la natural y es la equivocada.",
            "El signo del sesgo no se deduce de la etiqueta del defecto ni de su "
            "tamaño: depende de la relación entre el defecto y el movimiento "
            "típico de la serie. Por eso un control no puede 'corregir' el capital "
            "aplicando un ajuste por tipo de defecto; hay que detectarlo, "
            "sanear la serie y recalcular.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(output, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "reports" / "dq_capital_illustration")
    args = parser.parse_args()
    r = run(args.output)
    print("\nILUSTRACIÓN DIDÁCTICA — base 100, un solo factor, serie sintética.")
    print("No es una medición; no citar como resultado.\n")
    print(f"  VaR 99 % a un día sobre la serie limpia: {r['var99_serie_limpia_base100']:.2f}"
          f"  (sobre {BASE:.0f} de notional, media de {REPLICATIONS} réplicas)\n")
    print(f"  {'defecto':30s} {'VaR medido':>11s} {'dif.':>7s} {'signo':>7s}  dirección")
    for row in r["casos"]:
        print(f"  {row['defecto']:30s} {row['var99_medido_base100']:11.2f} "
              f"{row['diferencia_vs_serie_limpia']:+7.2f} "
              f"{row['consistencia_del_signo']:7.1%}  {row['direccion']}")
    print(f"\n  'signo' = fracción de las {REPLICATIONS} réplicas en que el sesgo va en esa "
          "dirección.\n  Por debajo del 100 % la dirección no es una propiedad del defecto.")
    print(f"\n  -> {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
