# Hallazgo · (a) CNN vs smoothness paramétrico en curvas · (b) splits re-ajustados = control de vintage

- **Autor:** A · **Fecha:** 2026-10-07.
- Reproducción: `dq_curve_cnn_supervised.py`, `dq_eq_backadjust.py` (+ JSON en results/reports).

## (a) CNN 1D supervisada vs residuo Nelson-Siegel (pico de 4 pb = 1,4σ de retorno, FP=2 %)
| Detector | recall_test | fp_test |
|---|---|---|
| **residuo Nelson-Siegel (forma)** | **1,00** | 0,03 |
| 3σ por nodo | 0,075 | 0,03 |
| CNN 1D supervisada | **0,05** | 0,01 |

**El control de smoothness paramétrico gana decisivamente; la CNN no lo iguala.**
Probé 4 variantes de red (autoencoder, max-pool, avg-pool, entrada=forma) y ninguna
supera ~0,05: una conv pequeña no replica la extracción EXACTA del componente suave
(nivel/pendiente/curvatura) que hace el modelo paramétrico, y el drift de nivel
domina la señal del pico. **Paré de ajustar para no hacer p-hacking.** Conclusión:
el valor está en la **feature de smoothness** (NS/Svensson), no en la red —coherente
con el resto del proyecto y con la CNN de B (que solo ganaba en saltos reversibles).
Para que una red aporte habría que alimentarla con el residuo paramétrico, momento
en que el modelo ya hace el trabajo.

## (b) Split EQ re-ajustado hacia atrás = control de VINTAGE (resultado fuerte)
Se escala el tramo histórico previo por 0,98 (re-ajuste hacia atrás). Recall sobre
el tramo re-ajustado (FP=2 %):
| Control | recall |
|---|---|
| 3σ sobre retorno | 0,02 |
| cross-asset sobre retorno | 0,04 |
| nivel-ratio rolling (auto-referencial) | 0,02 |
| **vintage vs serie almacenada** | **1,00** |

**El re-ajuste es invisible a TODOS los controles auto-referenciales** (el escalado
no cambia los retornos; un control rolling se adapta al nuevo nivel), **y solo la
comparación con el vintage almacenado lo caza.** Es la tesis del MASTER: una
reescritura histórica deja la serie obsoleta en BBDD y solo se detecta comparando
versiones. **Justifica un control de vintage/snapshot en el framework**, además de
los de desviación.

## Framework DQ — control correcto por familia (cuadro final)
| Defecto | Mejor control | Recall (vs 3σ) |
|---|---|---|
| rachas/repetidos ≥20 | TRIM | 1,0 (3σ 0,0) |
| stale | cross-asset / TRIM | 1,0 |
| decoplamiento | cross-asset (pares naturales) | 0,06–0,98 según par |
| saltos | 3σ | 1,0 (real EURUSD 10/10) |
| forma de curva (pico sub-σ) | **smoothness NS/Svensson** | 1,0 (3σ 0,05) |
| reescritura histórica | **vintage vs almacenado** | 1,0 (resto ~0) |

**Mensaje honesto del paper:** el valor es el FRAMEWORK de control-correcto-por-defecto,
que domina al 3σ estándar; las redes (mi AE/CNN, la CNN de B) NO baten a los
controles explícitos correctos. La contribución es la asignación principiada, no la
complejidad del modelo.
