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
    # DFF no cierra en festivo y por tanto no tiene huecos.
    for col in sorted(set(panel.columns) - DERIVED - {"DFF"}):
        s = panel[col]
        lo, hi = s.first_valid_index(), s.last_valid_index()
        gaps = int(s.loc[lo:hi].isna().sum())
        check(f"{col}: conserva festivos como NaN (no hay ffill)", gaps > 0,
              f"{gaps} NaN internos")
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

    print("\n4bis. Ausencia de saltos diarios imposibles")
    # Este control se añade porque la serie EURUSD del panel original llegó a
    # producción con 10 saltos superiores al 5 % —imposibles en ese cruce— y
    # ninguna comprobación anterior los veía. Umbrales por instrumento, con
    # holgura para los episodios reales conocidos (WTI negativo en abril 2020).
    MAX_SALTO = {"EURUSD": 5, "GOLD": 12, "SILVER": 20, "COPPER": 15,
                 "SP500": 13, "DAX": 13, "EUROSTOXX50": 13, "BRENT": 25,
                 "VIX": 120}
    # Excepciones revisadas una a una. No se relajan los umbrales para que el
    # test pase: cada fecha se admite con motivo, y cualquier salto NO listado
    # falla. Criterio usado: un print defectuoso revierte al día siguiente; un
    # evento real persiste.
    EVENTOS_REALES = {
        ("BRENT", "2020-04-02"): "acuerdo OPEP+ anunciado; +35 %",
        ("BRENT", "2020-04-21"): "crisis de almacenamiento COVID; Brent a 9,12 USD",
        ("BRENT", "2020-04-22"): "rebote tras el mínimo; el nivel no revierte",
        ("COPPER", "2025-07-31"): "EE.UU. exime al cobre refinado del arancel 232",
        ("SILVER", "2026-01-30"): "fin del estrechamiento; 114→78 y se mantiene en 76-84",
    }
    for col, lim in sorted(MAX_SALTO.items()):
        s = panel[col].dropna()
        jumps = (s.pct_change(fill_method=None).abs() * 100).dropna()
        bad = [d for d in jumps[jumps > lim].index
               if (col, str(d.date())) not in EVENTOS_REALES]
        n_exc = int((jumps > lim).sum()) - len(bad)
        check(f"{col}: sin saltos diarios > {lim} % no justificados", not bad,
              (f"{n_exc} excepción(es) documentada(s)" if n_exc else "")
              + ("" if not bad else
                 f" · {len(bad)} SIN justificar: "
                 f"{', '.join(str(d.date()) for d in bad[:4])}"))
    print("      Excluidos de este control, con motivo:")
    print("        WTI     el 2020-04-20 el precio fue negativo de verdad.")
    print("        NATGAS  Henry Hub al contado: durante las olas de frío se")
    print("                multiplica de un día para otro (Uri 2021: 11,32→23,86;")
    print("                enero 2024: 3,15→13,20). Ningún umbral porcentual")
    print("                separa defecto de evento en un spot físico.")

    print("\n5. Alineación temporal contra la referencia auditada")
    print("     (dataset_wide_with_target.csv; un desplazamiento óptimo ≠ 0")
    print("      indicaría look-ahead o retraso de un día)")
    # EURUSD queda fuera de este contraste: su serie en la referencia está
    # corrupta (ver §4bis y el hallazgo de 2026-09-11), así que compararse con
    # ella no informa. Su fuente actual es el BCE, independiente.
    ref = pd.read_csv(REF, parse_dates=["date"]).set_index("date")
    for col in sorted(YAHOO & set(ref.columns)):
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
