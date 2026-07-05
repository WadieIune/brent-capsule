# /docs — Documentación del proyecto (proyecto único: v3)

| Fichero / carpeta | Qué es |
|---|---|
| **`CCN_BRENT_canal/`** | **El documento del proyecto** (LaTeX, compilar en Overleaf con pdfLaTeX). Consolida todo: detector de canal solo-precio, evidencia bootstrap cross-asset, OOS 2026, recalibración, chartismo por capas, backtest DSR/PBO, **marco de riesgo de 4 capas + dashboard** (§6) y anexos: A formulación matemática, B justificación de métricas, C reproducibilidad, D hoja de ruta. Figuras generadas desde los resultados reales. |
| `presentacion_brent.html` | Presentación visual autocontenida (abrir en cualquier navegador). Incluye los 4 hallazgos, el marco de riesgo y la hoja de ruta. |
| `JUSTIFICACION_METRICAS.md` | Resumen rápido del Anexo B (por qué cada métrica, para el comité). |
| `MEJORAS_PROPUESTAS.md` | Hoja de ruta detallada (investigación / código / datos). |
| `PROJECT_LEDGER.md` | Registro histórico de sesiones y decisiones del proyecto. |

## Documentos retirados (recuperables del historial de git)

- `CCN_BRENT_pattern/` — documento LaTeX de la corrida v2 corta (superado por `CCN_BRENT_canal/`).
- `main.tex` + `references.bib` — borrador de manuscrito elsarticle v2 (contenido absorbido).
- `risk_framework.{tex,md}` — marco de riesgo standalone (integrado como §6 del documento principal y en el HTML).

Para recuperarlos: `git show 5238de6:docs/<fichero>`.
