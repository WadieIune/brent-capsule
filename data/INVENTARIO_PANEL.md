# Inventario del panel extendido

Entrega en respuesta a la instrucción de B (bandeja de A, 2026-09-11):
*«CSV versionado, inventario de fuente/instrumento/unidad, calendario,
`release_time`, `vintage_time` cuando aplique, `ingestion_time`, hash y prueba
de que el join as-of no usa futuro»*.

**Artefacto:** `data/panel_extendido_2026-09-09.csv`
**Rango:** 2007-01-01 → 2026-09-10 · 5.139 días hábiles × 21 variables
**sha256:** `3b351ce135fccd9d...` (el valor completo está en el provenance; lo
verifica `data/verify_panel.py`)
**`ingestion_time`:** 2026-09-11
**Verificación:** `python data/verify_panel.py` → todas las comprobaciones pasan.

---

## 1. Inventario por variable

| Variable | Fuente | Instrumento | Unidad | Calendario | Última obs. | Lag mín. |
|---|---|---|---|---|---|---|
| `BRENT` | FRED | `DCOILBRENTEU` | USD/barril | bursátil EE.UU. | 2026-09-09 | ≥ 2 d.háb. |
| `WTI` | FRED | `DCOILWTICO` | USD/barril | bursátil EE.UU. | 2026-09-09 | ≥ 2 |
| `NATGAS` | FRED | `DHHNGSP` | USD/MMBtu | bursátil EE.UU. | 2026-09-09 | ≥ 2 |
| `VIX` | FRED | `VIXCLS` | puntos de índice | bursátil EE.UU. | 2026-09-10 | ≥ 1 |
| `DGS2` | FRED | `DGS2` | % anual | bursátil EE.UU. | 2026-09-09 | ≥ 2 |
| `DGS10` | FRED | `DGS10` | % anual | bursátil EE.UU. | 2026-09-09 | ≥ 2 |
| `DGS30` | FRED | `DGS30` | % anual | bursátil EE.UU. | 2026-09-09 | ≥ 2 |
| `DTWEXBGS` | FRED | `DTWEXBGS` | índice (ene-2006 = 100) | semanal-diario | 2026-09-04 | ≥ 5 |
| `DFF` | FRED | `DFF` | % anual | todos los días | 2026-09-09 | ≥ 2 |
| `SOFR` | FRED | `SOFR` | % anual | bursátil EE.UU. | 2026-09-10 | ≥ 1 |
| `GOLD` | Yahoo | `GC=F` | USD/oz troy | bursátil EE.UU. | 2026-09-10 | ≥ 1 |
| `SILVER` | Yahoo | `SI=F` | USD/oz troy | bursátil EE.UU. | 2026-09-10 | ≥ 1 |
| `COPPER` | Yahoo | `HG=F` | USD/libra | bursátil EE.UU. | 2026-09-10 | ≥ 1 |
| `SP500` | Yahoo | `^GSPC` | puntos de índice | bursátil EE.UU. | 2026-09-10 | ≥ 1 |
| `DAX` | Yahoo | `^GDAXI` | puntos de índice | bursátil Alemania | 2026-09-10 | ≥ 1 |
| `EUROSTOXX50` | Yahoo | `^STOXX50E` | puntos de índice | bursátil zona euro | 2026-09-10 | ≥ 1 |
| **`EURUSD`** | **panel original** | — | USD por EUR | 24/5 | **2026-03-06** | **NO EXTENDIDA** |

**Derivadas** (calculadas en el propio panel, sin fuente externa):
`SPREAD_US10Y_US2Y` = `DGS10 − DGS2` · `SPREAD_WTI_BRENT` = `WTI − BRENT` ·
`RATIO_WTI_BRENT` = `WTI / BRENT` · `BRENT_EURUSD_RATIO` = `BRENT / EURUSD`.

> `BRENT_EURUSD_RATIO` hereda el corte de `EURUSD`: **no está extendida más allá
> de 2026-03-06.**

## 2. `release_time` y `vintage_time`

**No se han podido obtener.** Requieren la API de ALFRED con clave, que no está
disponible en el entorno. En su lugar se publica una **cota inferior medida**
del retardo de publicación: la distancia entre la última observación disponible
y el instante de ingesta (columna «Lag mín.»). Es una cota, no el retardo real.

Consecuencia operativa, y hay que respetarla: **el panel está fechado por
observación, no por publicación.** Quien lo consuma debe aplicar el retardo de
su variable. `DTWEXBGS` es la más expuesta (≥ 5 días hábiles).

## 3. Prueba de que el join as-of no usa futuro

`data/verify_panel.py` la ejecuta en tres piezas encadenadas:

1. **No hay relleno hacia delante.** Los festivos siguen siendo `NaN`
   (160–211 por serie). Un `ffill` los habría eliminado por construcción.
   Las repeticiones exactas que sí aparecen se explican por la rejilla de
   cotización, no por relleno: la tasa de repetición sigue al cociente
   |Δ| mediano / tick (DGS2: ratio 3 → 19 %; BRENT: ratio 89 → 1,1 %;
   SP500: ratio 1.202 → 0,0 %).
2. **El desplazamiento temporal óptimo es 0** para las 7 series no-FRED,
   contrastado contra `dataset_wide_with_target.csv` en ~4.800 sesiones de
   solape. Un óptimo en −1 o +1 delataría adelanto o retraso de un día.
3. **Ninguna variable contiene observaciones posteriores a la ingesta.**

Como cada valor no nulo de la fila `t` procede de la observación de esa misma
fecha `t` (1) y está correctamente fechado (2), la fila `t` no contiene
información de fechas posteriores.

## 4. EURUSD: por qué no se extiende

Yahoo `EURUSD=X` fue **descargado, validado y rechazado**. Sus barras diarias
están fechadas un día antes de la sesión que contienen: no existe barra
etiquetada en viernes y sí en domingo. Usarlo sin corregir mete un
**look-ahead de un día**. El remapeo al siguiente día hábil deja todavía 20–50
días por año con error superior al 0,5 % frente a la referencia, y error
mediano de 0,206 % en 2026 —justo el tramo nuevo—.

Detalle y reproducción en
[`docs/hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md`](../docs/hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md).

**Impacto acotado para WP-V3:** la variable «dólar» de la capa exógena es
`DTWEXBGS` (dólar amplio), que **sí** está extendida a 2026-09-04. El hueco de
`EURUSD` no bloquea WP-V3.

**Vía de resolución:** FRED `DEXUSEU`, que no respondió durante la ingesta
(cuatro intentos, `TimeoutError`; Yahoo respondía con normalidad en el mismo
momento).
