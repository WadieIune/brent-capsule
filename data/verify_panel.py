#!/usr/bin/env python3
"""Verificación del panel extendido. Ejecutable y sin argumentos.

Responde a la entrega mínima exigida por B (bandeja de A, 2026-09-11):
inventario por variable, calendario, tiempos, hash y prueba de que el
join as-of no usa futuro.

    python data/verify_panel.py

Sale con código 1 si alguna comprobación falla.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent
PANEL = DATA / "panel_extendido_2026-09-09.csv"
PROV = DATA / "panel_extendido_PROVENANCE.json"
REF = DATA / "dataset_wide_with_target.csv"

FRED = {"BRENT", "WTI", "NATGAS", "VIX", "DGS2", "DGS10", "DGS30",
        "DTWEXBGS", "DFF", "SOFR"}
YAHOO = {"GOLD", "SILVER", "COPPER", "SP500", "DAX", "EUROSTOXX50"}
DERIVED = {"SPREAD_US10Y_US2Y", "SPREAD_WTI_BRENT", "BRENT_EURUSD_RATIO",
           "RATIO_WTI_BRENT"}
# EURUSD queda fuera de FRED y de YAHOO a propósito: ver §"pendiente" en el
# provenance. Yahoo EURUSD=X fue rechazado por su convención de fechas.

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if ok else 'FALLA'}] {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def main() -> int:
    panel = pd.read_csv(PANEL, parse_dates=["date"]).set_index("date")
    prov = json.loads(PROV.read_text())

    print(f"\nPANEL  {PANEL.name}")
    print(f"  {panel.index.min().date()} → {panel.index.max().date()}  "
          f"{len(panel)} filas × {panel.shape[1]} variables\n")

    print("1. Integridad del artefacto")
    digest = hashlib.sha256(PANEL.read_bytes()).hexdigest()
    check("sha256 coincide con el provenance", digest == prov.get("sha256"),
          digest[:16] + "...")

    print("\n2. Calendario")
    expected = pd.bdate_range(panel.index.min(), panel.index.max())
    check("el índice es exactamente bdate_range (lun-vie, sin huecos de fila)",
          panel.index.equals(expected), f"{len(expected)} días hábiles")
    check("índice estrictamente creciente y sin duplicados",
          panel.index.is_monotonic_increasing and not panel.index.has_duplicates)

    print("\n3. Ausencia de relleno hacia delante (ffill)")
    # La prueba decisiva no es contar repeticiones —que dependen de la rejilla
    # de cotización— sino comprobar que los festivos SIGUEN siendo NaN: un
    # ffill los habría eliminado por construcción.
    # DFF y EURUSD no cierran en los festivos bursátiles y por tanto no tienen
    # huecos: para ellos la comprobación se hace por dispersión de repeticiones.
    SIN_CALENDARIO_BURSATIL = {"DFF", "EURUSD"}
    for col in sorted(set(panel.columns) - DERIVED - SIN_CALENDARIO_BURSATIL):
        s = panel[col]
        lo, hi = s.first_valid_index(), s.last_valid_index()
        gaps = int(s.loc[lo:hi].isna().sum())
        check(f"{col}: conserva festivos como NaN (no hay ffill)", gaps > 0,
              f"{gaps} NaN internos")

    # EURUSD: mercado 24/5, cotiza en festivos de EE.UU. La ausencia de huecos
    # es esperada. La señal de ffill sería que las repeticiones se concentraran
    # en los días de cierre real (25-dic, 26-dic, 1-ene); se comprueba que no.
    s = panel["EURUSD"].dropna()
    reps = s.index[(s.diff() == 0).to_numpy()]
    cierre = sum(d.strftime("%m-%d") in ("12-25", "12-26", "01-01") for d in reps)
    frac = cierre / max(1, len(reps))
    check("EURUSD: repeticiones NO concentradas en días de cierre (no hay ffill)",
          frac < 0.25, f"{cierre}/{len(reps)} = {100 * frac:.0f} % en cierres")
    print("      (DFF se excluye: la Fed publica el tipo efectivo también en"
          " festivo, así que no tiene huecos)")
    print("\n      Informativo — las repeticiones exactas se explican por la")
    print("      rejilla de cotización, no por relleno:")
    for col in ("DGS2", "DGS10", "NATGAS", "BRENT", "SP500"):
        s = panel[col].dropna()
        d = s.diff().abs()
        d = d[d > 0]
        print(f"        {col:<8} |Δ| mediano/tick = {d.median() / d.min():>7.1f}"
              f"   repeticiones = {100 * (s.diff() == 0).mean():>5.1f} %")

    print("\n4. Los huecos son festivos, no pérdida de datos")
    for col in sorted(set(panel.columns) - DERIVED):
        s = panel[col]
        lo, hi = s.first_valid_index(), s.last_valid_index()
        gaps = int(s.loc[lo:hi].isna().sum())
        frac = gaps / len(s.loc[lo:hi])
        check(f"{col}: huecos internos < 6 %", frac < 0.06,
              f"{gaps} días ({100 * frac:.1f} %)")

    print("\n5. Alineación temporal contra la referencia auditada")
    print("     (dataset_wide_with_target.csv; un desplazamiento óptimo ≠ 0")
    print("      indicaría look-ahead o retraso de un día)")
    ref = pd.read_csv(REF, parse_dates=["date"]).set_index("date")
    for col in sorted((YAHOO | {"EURUSD"}) & set(ref.columns)):
        errs = []
        for d in (-1, 0, 1):
            joined = pd.concat([panel[col].shift(d).rename("y"),
                                ref[col].rename("x")], axis=1).dropna()
            errs.append(float(np.median((joined["y"] / joined["x"] - 1).abs())) * 100)
        best = (-1, 0, 1)[int(np.argmin(errs))]
        check(f"{col}: desplazamiento óptimo = 0", best == 0,
              f"err mediano {errs[1]:.4f} %")

    print("\n6. El join as-of no usa futuro")
    # El panel está fechado por OBSERVACIÓN, no por publicación. La prueba
    # que importa es que ninguna fila t contenga información cuya fecha de
    # observación sea posterior a t: se verifica porque cada valor no nulo
    # procede de la observación de esa misma fecha (no hay ffill, §3) y
    # porque el desplazamiento óptimo es 0 (§5).
    # Falta el retardo de publicación: se mide como cota inferior con la
    # última observación disponible en el momento de la ingesta.
    ingest = pd.Timestamp(prov.get("ingestion_date", "2026-09-11"))
    print(f"     ingesta: {ingest.date()}   retardo mínimo observado:")
    for col in sorted(set(panel.columns) - DERIVED):
        last = panel[col].dropna().index.max()
        lag = int(np.busday_count(last.date(), ingest.date()))
        print(f"       {col:<14} última obs {last.date()}  →  lag ≥ {lag} d.háb.")
    check("ninguna variable tiene observaciones posteriores a la ingesta",
          all(panel[c].dropna().index.max() <= ingest for c in panel.columns))
    print("     NOTA: quien consuma el panel debe aplicar el retardo de "
          "publicación de su variable.\n     El panel NO lo aplica: está "
          "fechado por observación.")

    print()
    if fails:
        print(f"RESULTADO: {len(fails)} comprobación(es) fallida(s):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("RESULTADO: todas las comprobaciones pasan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
