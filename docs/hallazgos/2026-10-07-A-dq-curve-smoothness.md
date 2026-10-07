# Hallazgo · Control de forma de curva (smoothness) — demostrado, y corrige mi error previo

- **Autor:** A · **Fecha:** 2026-10-07 · `code/applications/experiments/dq_curve_shape_v2.py`.
- **Corrige** mi "no demostrado" anterior: era un setup equivocado (3 nodos, picos grandes).

## El enfoque correcto (guía del MASTER)
El defecto relevante en curvas NO es un outlier grande (lo caza el 3σ) sino un
**movimiento pequeño que mantiene la correlación entre plazos (>98 %) pero rompe el
SMOOTHNESS** —un plazo infra/sobrevalorado por unos bps—. Un algoritmo de
desviaciones por punto no lo ve; el control de forma sobre el *smoothness* que dan
los modelos paramétricos (Svensson/Nelson-Siegel) sí. Importa para P&L: el trading
algorítmico cubre la delta de un plazo con el contrario en OTRO plazo (si la
correlación >98 %); un plazo mal valorado da un P&L incorrecto que el outlier por
punto no detecta.

## Resultado (curva NS 10 plazos, pico de 4 pb = 1,39σ de retorno, FP=2 %)
| Detector | pico pequeño (1 curva) | paralelas base vs RFR (−4 pb) |
|---|---|---|
| 3σ por nodo | **0,05** (ciego) | **0,03** (ciego) |
| **residuo Nelson-Siegel** | **1,00** | **1,00** |
| CNN 1D (autoencoder no superv.) | 0,02 | — |

Curvas paralelas: corr media base/RFR **0,9995**; el residuo de forma del spread
caza la divergencia de −4 pb en un solo plazo (recall 1,0) que el 3σ por nodo pierde.

## Lecturas
1. **El control de smoothness (NS/Svensson) es el ganador claro**: recall 1,0 en
   picos pequeños y en divergencias paralelas, donde el 3σ por punto da ~0,03–0,05.
   Valida que el reconocimiento de FORMA detecta defectos sub-umbral que rompen P&L.
2. **Mi CNN 1D (autoencoder no supervisado) falla** (0,02): un AE sobre niveles no
   es sensible al smoothness. Para que una RED lo capture hay que **entrenarla
   supervisada sobre los picos pequeños** (el enfoque de B), o sobre el residuo
   paramétrico como feature. El valor está en medir la desviación del smoothness,
   no en la complejidad del modelo.
3. **Rectifico mi conclusión previa:** con multi-tenor + referencia de smoothness +
   picos pequeños, el control de forma **SÍ está demostrado** y es potente.

## Extensiones naturales (mismo principio)
- Splits EQ al 98 % (−2 %) y series re-ajustadas hacia atrás que quedan obsoletas:
  consistencia de serie, no desviación puntual.
- Smile de curvas de volatilidad: control de forma del smile.
- Requisito de producción (caveat de B): curva real multi-tenor + construcción ZC
  (bootstrapping, convenciones). La demo usa NS sintético por no haber acceso a FRED.
