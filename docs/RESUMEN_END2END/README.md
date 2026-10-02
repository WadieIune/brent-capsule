# Resumen end-to-end (LaTeX, ≤10 páginas)

Documento conciso para que el equipo entienda **todo lo hecho de principio a
fin**, lo corrija y lo transforme en paper.

- **Fuente:** `main.tex` (autocontenido).
- **Figura del proceso:** TikZ dentro del propio `.tex` — editable, sin ficheros
  externos ni binarios. Es la misma arquitectura que
  `docs/figuras/sistema_productivo_cnn_gate_capital.svg`.
- **Compilar en Overleaf:** subir `main.tex`, `pdflatex main` ×2 (sin bibtex).
  No requiere la carpeta `figures/`.

## Qué cubre
Visión end-to-end (dos gates + dos palancas de capital + backtest en paralelo),
datos y calidad del dato (DQ → capital 13,4 %), CNN (GASF/GADF, AUC 0,97),
supervivencia del canal (C-index 0,664), VaR/ES y capital (−22,7 %, batería
completa), el backtest como filtro (DSR, PBO, nulo), lo que **no** funciona y por
qué importa, limitaciones/reproducibilidad y punteros al código.

## Relación con el otro LaTeX del repo
`docs/CCN_BRENT_canal/main.tex` es la documentación **extensa** de una iteración
anterior (detector + supervivencia + VaR), con sus figuras generadas de
`results/`. Este resumen es la versión **corta y actualizada** con el encuadre de
capital, los dos gates y el backtest como capa de validación. Para el paper:
partir de este resumen como esqueleto y tirar del detallado para los anexos.
