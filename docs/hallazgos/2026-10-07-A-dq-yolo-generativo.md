# Pack generativo + detección visual para DQ — 2026-10-07

## Pregunta

¿Un autoencoder convolucional que amplía trayectorias limpias mejora YOLO o una
CNN 1D para anomalías de log-volatilidad fuera de distribución? ¿Aporta la
representación visual frente a reconstrucción, CNN numérica y 3σ causal?

## Protocolo ejecutado

- YOLO11n preentrenado, ajustado 5 épocas por tratamiento; CNN densa 1D y VAE
  convolucional entrenados en la misma RTX 5060 Laptop GPU (CUDA 0).
- 800 ventanas de entrenamiento, 300 ventanas limpias de validación y 250 de
  test. Semilla única: 42. Train: AR mean-reverting gaussiano con estados de
  volatilidad; validación/test: rangos AR distintos, innovaciones t(5) y más
  cambios de estado.
- Defectos de entrenamiento: spike y hump. Familias OOD: spike,
  `stale_block` y `level_shift`. Umbrales calibrados al 2 % de FPR en validación
  limpia independiente. Comparación `base` vs `vae_augmented`, con datos de
  entrenamiento de igual tamaño. El VAE también se prueba como detector por
  error de reconstrucción. No hay ajuste con ventanas de test.

## Resultados

El VAE no conserva suficientemente la distribución de entrenamiento: desviación
estándar generada/referencia = **0,689**; ACF(1) 0,984 vs 0,910; ACF(5) 0,745
vs 0,633; cuantiles 1/99 generados −1,67/+1,55 frente a −2,53/+2,51.
RMSE de reconstrucción limpia = 0,405. La generación es demasiado suave y
comprime las colas; por tanto, este VAE no constituye todavía una fuente válida
de augmentación de regímenes/defectos.

FPR limpia de test, base → VAE-augmentado: CNN1D **2,8 % → 2,4 %**; YOLO
**3,6 % → 2,0 %**; AE **2,0 % → 2,0 %**; 3σ causal por máximo de ventana
**3,2 % → 3,2 %**. La calibración en una muestra pequeña de 300 ventanas no
garantiza FPR OOS exacta.

Recall de evento localizado en test (base → VAE-augmentado):

| Familia | CNN1D | YOLO | AE reconstrucción | 3σ causal |
|---|---:|---:|---:|---:|
| Spike | 0,224 → 0,200 | 0,116 → 0,140 | 0,268 → 0,268 | 0,184 → 0,184 |
| Stale block | 0,004 → 0,004 | 0,004 → 0,004 | 0,000 → 0,000 | 0,012 → 0,012 |
| Level shift | 0,132 → 0,120 | 0,024 → 0,016 | 0,072 → 0,072 | 0,156 → 0,156 |

No aparece una mejora consistente de la augmentación. YOLO no bate la CNN
numérica ni 3σ en las familias OOD; el AE de reconstrucción tampoco resuelve
staleness. El resultado no refuta el uso de CNN/YOLO en general: este piloto es
una sola semilla y una tarea sintética distinta del modelo productivo de canales.

## Interpretación y decisión

**No promover VAE augmentation ni YOLO como alertas DQ.** Primero hay que lograr
que el generador reproduzca estadísticas marginales y temporales (colas,
volatilidad por régimen, ACF y duración de estados), y modelar explícitamente
las corrupciones etiquetadas; un VAE entrenado solo con limpio no genera por sí
mismo defectos con ground truth. La comparación siguiente debe incluir el
cross-asset de ventana de B, especialmente `1−R²` para stale/decoupling, con
ventanas, FPR, semillas y defectos pareados. Si esa capa barata cubre una familia
mejor, no hay razón para pagar el coste de visión allí.

YOLO conserva una hipótesis específica: localización tiempo×tenor de kinks o
desacoplamientos en curvas multiserie. Para probarla, rasterizar matrices
tiempo×tenor con ejes/rangos congelados y evaluar IoU/recall por curva-fecha,
frente a CNN 1D y residuo de shape a FPR emparejada. El experimento presente no
valida curvas.

## Reproducibilidad

- Código: `code/applications/experiments/dq_yolo_generative_pack.py`
- Métricas: `results/reports/dq_yolo_generative_pack/summary.json`
- Pesos: `results/reports/dq_yolo_generative_pack/models/`
- Datos renderizados y temporales YOLO: `/tmp/dq_yolo_generative_pack/`
- Cobertura: `tests/test_dq_yolo_generative_pack.py`

Limitaciones: datos totalmente sintéticos, una semilla, solo 250 ventanas de
test por familia, YOLO ajustado cinco épocas, umbral por cuantiles empíricos y
sin intervalo de confianza ni modelo cross-asset en este benchmark. Sirve para
priorizar experimentos, no para estimar rendimiento operativo.
