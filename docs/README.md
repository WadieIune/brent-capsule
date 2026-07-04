# Documentación LaTeX — BRENT Pattern System v2

Manuscrito científico en formato de revista (**Systems and Soft Computing**,
Elsevier) que documenta el sistema, su metodología y la versión v2 (validación
temporal robusta + reproducibilidad).

## Ficheros

- `main.tex` — manuscrito completo (clase `elsarticle`). Es **autocontenido**: no
  depende de imágenes externas (las figuras aparecen como *placeholders* con su
  pie; sustitúyelos por `\includegraphics` cuando dispongas de las figuras
  finales).
- `references.bib` — bibliografía: referencias de los borradores originales +
  metodología de validación financiera (López de Prado: PSR/DSR/PBO).

## Compilación

Requiere una distribución LaTeX (TeX Live / MiKTeX) con la clase `elsarticle`
(incluida en ambas distribuciones).

```bash
# Opción recomendada (resuelve todo automáticamente):
latexmk -pdf main.tex

# Manual:
pdflatex main
bibtex   main
pdflatex main
pdflatex main
```

En Windows con MiKTeX, los paquetes que falten se instalan automáticamente en la
primera compilación.

## Cómo insertar las figuras

1. Guarda cada figura (PNG/PDF) en una subcarpeta `figures/`.
2. Sustituye el `\figplaceholder{fig:etiqueta}{Pie...}` correspondiente por:

```latex
\begin{figure}[!ht]
  \centering
  \includegraphics[width=0.9\linewidth]{figures/nombre.pdf}
  \caption{Pie de figura.}
  \label{fig:etiqueta}
\end{figure}
```

## Correspondencia con los resultados

Las tablas del manuscrito (métricas por partición, informe por clase, matriz de
confusión, backtest) se corresponden directamente con las hojas del Excel
`results/reports/brent_resultados.xlsx` generado por la cápsula, de modo que los
revisores pueden validar cada cifra frente a la configuración exacta registrada en
`results/run_manifest.json` y en la hoja `01_Configuracion`.
