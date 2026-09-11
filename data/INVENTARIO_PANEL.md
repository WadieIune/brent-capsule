# Inventario del panel extendido

Entrega en respuesta a la instrucción de B (bandeja de A, 2026-09-11):
*«CSV versionado, inventario de fuente/instrumento/unidad, calendario,
`release_time`, `vintage_time` cuando aplique, `ingestion_time`, hash y prueba
de que el join as-of no usa futuro»*.

**Artefacto:** `data/panel_extendido_2026-09-09.csv`
**Rango:** 2007-01-01 → 2026-09-10 · 5.139 días hábiles × 21 variables
**sha256:** `b5512282a5e7d42d...` (el valor completo está en el provenance; lo
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
| `EURUSD` | **BCE** | `EXR.D.USD.EUR.SP00.A` | USD por EUR | TARGET | 2026-09-10 | ≥ 1 |

**Derivadas** (calculadas en el propio panel, sin fuente externa):
`SPREAD_US10Y_US2Y` = `DGS10 − DGS2` · `SPREAD_WTI_BRENT` = `WTI − BRENT` ·
`RATIO_WTI_BRENT` = `WTI / BRENT` · `BRENT_EURUSD_RATIO` = `BRENT / EURUSD`.

> `EURUSD` es el **tipo de referencia del BCE, fijado a las 14:15 CET**. Es una
> convención horaria distinta de la del resto del panel, y se elige a conciencia:
> la serie anterior estaba corrupta (§4). Calendario TARGET, no bursátil de EE.UU.

## 2. `release_time` y `vintage_time`

**No se han podido obtener.** Requieren la API de ALFRED con clave, que no está
disponible en el entorno. En su lugar se publica una **cota inferior medida**
del retardo de publicación: la distancia entre la última observación disponible
y el instante de ingesta (columna «Lag mín.»). Es una cota, no el retardo real.

Consecuencia operativa, y hay que respetarla: **el panel está fechado por
observación, no por publicación.** Quien lo consuma debe aplicar el retardo de
su variable. `DTWEXBGS` es la más expuesta (≥ 5 días hábiles).

## 3. Prueba de que el join as-of no usa futuro

`data/verify_panel.py` la ejecuta en tres piezas encadenadas
(más el control de saltos de §5):

1. **No hay relleno hacia delante.** Los festivos siguen siendo `NaN`
   (160–211 por serie). Un `ffill` los habría eliminado por construcción.
   Las repeticiones exactas que sí aparecen se explican por la rejilla de
   cotización, no por relleno: la tasa de repetición sigue al cociente
   |Δ| mediano / tick (DGS2: ratio 3 → 19 %; BRENT: ratio 89 → 1,1 %;
   SP500: ratio 1.202 → 0,0 %).
2. **El desplazamiento temporal óptimo es 0** para las 6 series de Yahoo,
   contrastado contra `dataset_wide_with_target.csv` en ~4.800 sesiones de
   solape. Un óptimo en −1 o +1 delataría adelanto o retraso de un día.
   `EURUSD` queda fuera de este contraste porque esa referencia está corrupta
   justo en esa variable (§4); su fuente actual, el BCE, es independiente.
3. **Ninguna variable contiene observaciones posteriores a la ingesta.**

Como cada valor no nulo de la fila `t` procede de la observación de esa misma
fecha `t` (1) y está correctamente fechado (2), la fila `t` no contiene
información de fechas posteriores.

## 4. EURUSD: dos fuentes rechazadas y una aceptada

**Yahoo `EURUSD=X` — rechazado.** Sus barras están fechadas un día antes de la
sesión que contienen (no hay barra en viernes y sí en domingo). Usarlo mete un
**look-ahead de un día**.

**La serie del panel original — rechazada, y esto es lo grave.** Contiene **10
saltos diarios superiores al 5 %**, imposibles en el euro/dólar, concentrados en
2008 y con patrón de día 8 (8-ene, 8-feb, 8-sep, 8-oct, 8-dic). El mayor es
1,4918 → 1,2926 el 2008-12-08, un 13,8 % que nunca ocurrió. **Ninguna otra
variable de esa referencia presenta el defecto.**

**BCE `EXR.D.USD.EUR.SP00.A` — aceptado.** Tipo de referencia oficial,
2007-01-02 → 2026-09-10, 98,1 % de cobertura, **cero saltos imposibles**.
Sustituye a la serie anterior en **toda** la historia, no solo en la cola.

Detalle y reproducción en
[`docs/hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md`](../docs/hallazgos/2026-09-11-A-eurusd-yahoo-desfase-de-un-dia.md).

## 5. Control de saltos imposibles

Se añade a raíz de lo anterior: umbral por instrumento y **lista explícita de
excepciones justificadas** (Brent en abril de 2020, arancel del cobre de julio
de 2025, desplome de la plata de enero de 2026). No se relajan los umbrales para
que el test pase; un salto no listado hace fallar la verificación. `NATGAS` queda
excluido con motivo: el Henry Hub al contado se multiplica de un día para otro
en las olas de frío y ningún umbral porcentual separa defecto de evento.
