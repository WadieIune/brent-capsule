# Pre-registro multiactivo · WP-RD1 (cartera larga 1/N) — para OK de B

- **Autor:** A · **Fecha:** 2026-10-06 · instrucción del MASTER («haz la 2»).
- **Base:** `docs/PROPUESTA_WP_RD1_MULTIACTIVO.md` (B) + lecciones de sesgo de
  Gate 1 v3 (purga en fronteras, baseline en validación, nulo con política propia,
  FA emparejada).
- **Estado:** congelado para tu visto bueno. El run multiactivo adjunto es
  **EXPLORATORIO** (etiquetado), no confirmatorio, hasta tu freeze.

## Cartera y datos
- **Cesta proxy 1/N** de `BRENT, WTI, GOLD, SILVER, COPPER, NATGAS` (sin pesos
  reales → proxy reproducible, no las posiciones del MASTER). FX/índices/tipos/VIX
  = contexto.
- **Fuente:** `data/panel_extendido_2026-09-09.csv` (mandante).
- **WTI negativo (abr-2020):** no se borra el día ni se aplica log a precio ≤ 0.
  **Representación provisional del run exploratorio:** retornos simples con suelo
  por activo en −95 %/día (preserva el evento sin que −284 % lo domine). **La
  representación definitiva la fija B** antes del confirmatorio (opciones: P&L en
  dólares por nocional, retorno simple con suelo, o tratamiento especial de los 2
  días de transición).

## Perspectiva y evento (coherente con el MASTER)
Cartera **larga**: evento adverso = **caída** acumulada de la cartera a 10
sesiones por debajo del peor decil estimado **solo en FIT (purgado)**; episodios
no solapados (fusión 10 sesiones).

## Señales a evaluar (ablaciones)
- **DQ** (control geométrico) antes de estimar riesgo.
- **vol de cartera** (EWMA) — baseline fuerte.
- **régimen y supervivencia** del canal **por activo**, agregados con
  **contribuciones al riesgo calculadas SOLO con train de cada fold** (corrige la
  fuga del artefacto actual, que las calcula sobre la muestra completa).
- **forecast multiactivo** (CNN temporal o tabular) como módulo distinto; no se
  presume que la CNN gane; se compara con EWMA/HAR/FHS.

## Métrica y controles (idénticos a Gate 1 v3, ya validados por B)
- **Purga ≥10** en cada frontera; **baseline preseleccionado en validación**;
  **FA emparejada** por interpolación con carga realizada reportada; **nulo con la
  misma política** (cooldown y nº de alertas); **bootstrap pareado por bloques ≥10**.
- **Capa de capital (si Gate 1 multiactivo pasa):** `k·VaR`, excepciones/agrupación
  (Kupiec/Christoffersen/DQ), ES, peor-250d, drawdown, Sharpe **neto de costes**
  (2–10 pb round-trip, sensibilidad). Menos excepciones **no cuenta** si viene de
  más capital, menos exposición o más rotación. **Covarianzas/contribuciones
  train-only por fold.**
- **Baselines:** VaR histórico, FHS-EWMA, política constante de igual VaR medio,
  reducción de exposición solo-vol. **FHS-EWMA aún es rechazado por DQ (p=0,016)**
  → referencia fuerte pero no plenamente validada; se reporta.

## Criterio y alcance
- **Éxito:** una capa de IA mejora recall por episodio sobre el mejor baseline a
  igual FA con IC que excluye 0 **y** supera el nulo; y, en su caso, mejora la
  protección de capital a cobertura/rotación comparables. Si no → negativo.
- Todo P&L/Sharpe/alpha de la cesta proxy es **simulado**; no es rentabilidad real.
- Gate 2 (acción de cartera) solo si Gate 1 multiactivo pasa.

## Solicitud a B
Validar: (1) representación definitiva del WTI negativo; (2) agregación de señales
por contribución al riesgo train-only; (3) FHS-EWMA como baseline pese al rechazo
DQ; (4) congelar para el único run confirmatorio. El run adjunto es exploratorio.
