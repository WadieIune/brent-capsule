# Control de capital por posiciones en una cartera de commodities
### Marco de riesgo de 4 capas y especificación de dashboard — detector de canal (solo precio)

> Versión compilable (PDF) en `docs/risk_framework.tex` (Overleaf).

## 1. Base de evidencia
El mandato de un Risk Director no es predecir la dirección, sino **controlar el capital y
sobrevivir a los regímenes**. Los hallazgos empíricos delimitan lo posible:

| Hallazgo empírico | Implicación para riesgo |
|---|---|
| Dirección del Brent no predecible (corr ≈ 0, hit ≈ base rate) | Prohibido dimensionar capital por "señal direccional" del modelo |
| Chartismo no pasa el backtest (DSR = 0, pierde vs buy&hold, MaxDD −59%) | El patrón no justifica subir tamaño; sirve de *challenge* al desk |
| Volatilidad sí predecible (persistencia, hit 0.58–0.72) | Palanca central: sizing y límites por riesgo |
| Detección de canal fiable y estable (AUC 0.97, sin decaimiento a 12m) | Descriptor de régimen, no alfa |
| Cross-asset no predice dirección pero define correlación | Agregación de riesgo de cartera, no el trade |

## 2. Marco de 4 capas (protección alrededor del capital)

```
┌────────────────────────────────────────────────────────┐
│ Capa 4 · Riesgo de cartera y correlación                │
│   VaR/ES · netting largo-corto · correlación móvil       │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Capa 3 · Overlay de régimen   ◄ detector          │  │
│  │   prob. de canal como descriptor, no señal         │  │
│  │  ┌────────────────────────────────────────────┐  │  │
│  │  │ Capa 2 · Límites duros                      │  │  │
│  │  │   bruto/neto · concentración · drawdown/stop │  │  │
│  │  │  ┌──────────────────────────────────────┐  │  │  │
│  │  │  │ Capa 1 · Sizing por riesgo            │  │  │  │
│  │  │  │   vol targeting · tamaño ∝ 1/σ         │  │  │  │
│  │  │  │      ┌──────────────────────┐          │  │  │  │
│  │  │  │      │  Capital (riesgo)     │          │  │  │  │
│  │  │  │      └──────────────────────┘          │  │  │  │
│  │  │  └──────────────────────────────────────┘  │  │  │
│  │  └────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

- **Capa 1 · Sizing por riesgo (diario):** `wᵢ = (riesgo_obj/σᵢ) / Σ(1/σⱼ)` (risk parity); la vol prevista manda el tamaño, no la vista direccional.
- **Capa 2 · Límites duros (intradía):** bruto/neto, concentración por activo y sector, drawdown/stop con de-risking automático, riesgo de curva/roll.
- **Capa 3 · Overlay de régimen (diario):** el detector etiqueta el régimen; nunca sube capital, solo marca contra-régimen y dispara recálculo de riesgo.
- **Capa 4 · Cartera y correlación (diario):** VaR/ES, netting, correlación móvil, ratio de diversificación.

## 3. Especificación de dashboard
Consume `results/models/heads.joblib` → por instrumento/día: `prob_ascending_channel`, `prob_descending_channel`, `pred_canal`, `confianza`. Semáforo: 🟢 info · 🟡 aviso · 🔴 brecha.

**Panel A — Exposición y sizing (Capa 1):** vol prevista σᵢ (EWMA/GARCH); tamaño objetivo wᵢ; ratio vol realizada/objetivo → 🟡 >1.2 recortar · 🔴 >1.5 de-risk 50%.

**Panel B — Límites (Capa 2):** utilización bruto (🟡 >85% · 🔴 ≥100%); sesgo neto (justificar); concentración activo (🟡 >25% · 🔴 >35%) y sector (🔴 >50%); drawdown vs stop (🟡 −8% · 🔴 −12%).

**Panel C — Régimen (Capa 3, detector):** régimen por activo (`pred_canal`+`confianza`); % cartera contra-régimen (🟡 >30% → revisión); cambio de régimen → recalcular VaR/correlación; confianza media <0.5 → no accionar.

**Panel D — Cartera y correlación (Capa 4):** VaR/ES 1d 99%; correlación media móvil 60d (🟡 ρ̄>0.6); ratio de diversificación (🔴 <1.3); backtest de excepciones (Kupiec/Christoffersen).

**Panel E — Salud y recalibración:** edad de la cabeza (🟡 >12m recalibrar); frescura del dato (🔴 >3 días); PSI de confianza (🟡 >0.2); dos relojes → régimen trimestral/anual, vol/correlación diario.

## 4. Gobernanza
- **Regla de oro:** ningún gatillo del Panel C aumenta capital; el sizing lo manda el riesgo (A/B), no el patrón.
- **Uso del modelo:** herramienta de *challenge* — ante "más capital porque rompe un canal", la evidencia (DSR=0) exige justificar el sizing por riesgo.
- **Multi-commodity:** entrenar una cabeza por commodity (mismo enfoque solo-precio).
- **Flujo diario:** `channel_detector.py predict` → Panel C; A/B/D consumen libro + estimadores; E vigila salud.
