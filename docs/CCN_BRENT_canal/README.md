# Documentación LaTeX — BRENT Pattern System v3 (detector de canal)

Documento de proyecto en formato académico que consolida **todos** los hallazgos
del sistema: detector de canal solo-precio (AUC 0.97/0.96), evidencia bootstrap
de que el cross-asset no aporta, test out-of-sample real de 2026, estabilidad
temporal/recalibración, chartismo por capas y backtest DSR/PBO.

## Compilar en Overleaf

1. Sube la carpeta completa (`main.tex`, `references.bib`, `figures/`) como
   proyecto (o un .zip de la carpeta).
2. Compilador: **pdfLaTeX**. Overleaf ejecuta bibtex automáticamente.

Local (si se dispone de TeX Live/MiKTeX): `latexmk -pdf main.tex`.

## Origen de las figuras

Todas las figuras de `figures/` se generan a partir de los resultados reales de
la cápsula (`results/reports/*.json`, `results/predictions/*.csv`,
`results/metadata/window_table.csv` y `data/dataset_wide_with_target.csv`).
No hay cifras manuales: cualquier número del documento es trazable a esos
ficheros.

## Estructura

- Secciones 1–5: introducción, datos, metodología, resultados y discusión.
- **Sección 6 — Marco de aplicación en riesgos**: control de capital en 4 capas
  (diagrama TikZ) y especificación del cuadro de mando (5 paneles con gatillos),
  construido sobre la evidencia empírica del propio proyecto.
- Sección 7: conclusiones.
- **Anexo A**: formulación matemática completa (etiquetado débil, GASF/GADF,
  CNN multitarea, cabezas logísticas, purga/embargo/walk-forward).
- **Anexo B**: justificación de cada métrica utilizada (AUC, precisión/recall/F1,
  balanced accuracy, macro-F1, bootstrap ΔAUC, PSR/DSR/PBO, CV purgada) con las
  referencias canónicas — pensado para el comité de publicación.
- **Anexo C**: reproducibilidad (cápsula, manifiesto, comandos).
- **Anexo D**: hoja de ruta de mejoras (investigación e ingeniería).
