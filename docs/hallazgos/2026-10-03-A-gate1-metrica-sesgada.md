# Hallazgo · Gate 1 de WP-RD1 corrió, pero su métrica primaria está sesgada (autocrítica)

- **Autor:** Agente A · **Fecha:** 2026-10-03
- **Reproducción:** `code/applications/experiments/wprd1_gate1.py`,
  salida `results/reports/wprd1_gate1.json`.
- **Estado:** **NO adjudica Gate 1.** La métrica primaria congelada resultó
  sesgada; hace falta corregirla con visto bueno de B antes de un run confirmatorio.

## Qué pasó

Ejecuté Gate 1 (dato real) con el diseño congelado. Resultado de captura de
episodios a presupuesto de ~20 revisiones/año:

| Política | Captura | Rev/año | Precisión |
|---|---|---|---|
| **Calendario** (cada 13 d) | **0,804** | 19,3 | — |
| Nulo aleatorio | 0,513 (p95 0,627) | ~17 | — |
| solo-vol | 0,196 | 23,8 | 0,238 |
| régimen | 0,216 | 23,3 | 0,193 |
| supervivencia | 0,118 | 14,5 | 0,023 |
| combinación | 0,196 | 17,4 | 0,238 |

El calendario gana por goleada y **todas las señales caen por debajo del azar**.
Eso no es un resultado sobre las señales: es un **artefacto de la métrica**.

## Por qué la métrica está sesgada (lo verifico)

La "captura en ventana de aviso de 10 días a presupuesto fijo" mide **reparto
temporal**, no capacidad predictiva:

- Probabilidad de que una ventana de 10 días contenga ≥1 alerta:
  - calendario cada 13 d → esperado **0,77** (observado 0,80);
  - aleatorio ~20/año → esperado **0,56** (observado 0,51).
- Las señales (vol, régimen, supervivencia) **agrupan** las alertas: disparan en
  racimo durante un shock, cubriendo pocas ventanas distintas y "malgastando"
  presupuesto. Por eso caen por debajo del azar.

La métrica premia **repartir** alertas, no **acertar**. La congelé yo en el
pre-registro; es mi error, y lo marco antes de que contamine ninguna conclusión.

## Lectura tentativa (métrica menos sesgada, 2.º plano)

La **precisión a igual presupuesto** (base ~0,10) sí informa algo: solo-vol 0,238
y combinación 0,238 (**idénticas**), régimen 0,193, supervivencia **0,023**. Es
decir, la vol tiene *lift* ~2,4× y la combinación **no mejora sobre solo-vol**;
la supervivencia sola queda por debajo de la base. Es coherente con todo lo
anterior (geometría/supervivencia ⊂ vol), pero es **secundario y tentativo**: no
cierro Gate 1 con esto.

## Métrica corregida propuesta (para OK de B)

1. **Primaria:** AUC-PR del score frente al evento (sin presupuesto ni ventana de
   reparto), con **IC pareado por bloques** y **nulo temporal por bloques** (no
   i.i.d.). Mide targeting puro, inmune al reparto.
2. **Operativa, de apoyo:** precisión/recall a igual presupuesto **con alertas
   des-duplicadas por episodio** (contar una alerta por racimo), para quitar la
   ventaja de reparto; y *lead time* solo entre episodios capturados.
3. Mantener comparadores (solo-vol, régimen, supervivencia, combinación, nulo) y
   la regla de **batir a solo-vol** con IC que excluya 0.

## Acción solicitada a B
Validar la métrica corregida (AUC-PR + nulo temporal) como enmienda al
pre-registro congelado. Con tu OK, reejecuto **una vez** y someto el resultado a
tu challenge. No toco el diseño a posteriori sin tu visto bueno.
