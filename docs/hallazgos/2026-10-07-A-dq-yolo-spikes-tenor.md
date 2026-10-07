# YOLO para spikes ligeros entre tenors — piloto — 2026-10-07

## Pregunta

¿Puede YOLO localizar un kink/spike pequeño en una curva frente a una curva
correlacionada (>98%), cuando los niveles/yields puntuales no parecen outliers?
El objetivo aquí es **tenor**, no spikes de volatilidad temporal.

## Diseño

Se generaron pares de curvas suaves paramétricas en una malla logarítmica de 32
tenors de 0,25 a 30 años, con factor común, ruido de cotización sub-bp e
intervalos de parámetros más amplios en OOD. Se inyectó en una sola curva un
spike local de 0,5–4 bp. Cada imagen representa el residuo entre curva primaria
y referencia, en bp y con ejes fijos; el bbox externo identifica el tenor
perturbado. YOLO11n (15 épocas) y CNN1D densa (15 épocas) se entrenaron en CUDA
RTX 5060. Train=1.000 pares, calibración=500 curvas limpias, test=500 limpias y
500 por amplitud. Semilla 42. Thresholds por score calibrados al 2 % de FPR
empírica en la validación limpia. Se evalúa alerta **y** localización en tenor.

Controles numéricos: residuo absoluto entre pares y residuo local contra un
suavizado de 3 puntos. CNN1D usa canales de residuo y curvatura de residuo.
Todos los números siguientes son sintéticos y exploratorios.

## Auditoría de etiquetas

La primera corrida mostró mAP50 0,995, pero al auditar las imágenes encontramos
una fuga: el renderer dibujaba un marcador circular en la ubicación de la caja
solo cuando la etiqueta era positiva. Se eliminó y se repitió el entrenamiento
completo; el mAP50 de validación cayó a 0,960. Se añadió un test que exige que
las imágenes con/sin objeto de etiqueta sean byte-a-byte idénticas. No se usan
las métricas de la primera corrida.

## Resultado tras corregir la fuga

FPR limpia en test: YOLO **1,4 %**, residuo local **2,0 %**, residuo pareado
3,0 %, CNN1D 4,4 %. Por tanto no es un punto de operación perfectamente
emparejado; la FPR CNN supera claramente el objetivo y las baselines simples
también quedan algo por encima.

Recall localizado por amplitud (0,5 / 1 / 2 / 3 / 4 bp):

| Detector | Recall por amplitud |
|---|---|
| YOLO | 0,144 / 0,578 / 0,658 / 0,682 / 0,684 |
| CNN1D | 0,290 / 0,978 / 1,000 / 1,000 / 1,000 |
| Residuo pareado | 0,330 / 0,996 / 1,000 / 1,000 / 1,000 |
| Residuo local | 0,140 / 0,794 / 1,000 / 1,000 / 1,000 |

## Veredicto

Este piloto sí ataca el caso solicitado: spikes leves **entre tenors**. YOLO
detecta parte de 0,5–1 bp, pero a 1 bp su recall 0,578 queda por debajo del
residuo local (0,794), CNN1D (0,978) y residuo pareado (0,996); a 2 bp y más,
el control pareado/local y CNN saturan mientras YOLO ronda 0,66–0,68. **YOLO no
pasa todavía el gate de detección DQ**. Puede servir como capa de localización
visual para revisión, pero no se justifica como alerta primaria frente al
control numérico.

Falta repetir varias semillas y comparar a FPR estrictamente emparejada; el test
OOD solo amplía parámetros/ruido del mismo generador y no demuestra
transferencia a curvas observadas. Además, un umbral de 2 % calibrado con 500
casos tiene incertidumbre muestral. El mAP de validación no es criterio de
éxito por sí solo.

## Siguiente experimento

1. Multi-seed (42/71/123/2026), bootstrap de intervalos por curva y curva-fecha.
2. Congelar el generador de imagen y medir sensibilidad a resolución, rango bp,
   cuantización, nodo/tenor, amplitud y bumps de 1 vs 2 tenors.
3. Incorporar perturbaciones realistas en una curva con smoothness paramétrica
   (Nelson-Siegel/Svensson) y un par correlacionado con desplazamiento residual;
   conservar un test de curvas reales no alteradas para falsos positivos.
4. Comparar recall, IoU del bbox en tenor, FPR por curva-fecha y latencia frente
   a CNN1D, residuo pareado, residuo de shape y 3σ temporal por nodo, todos a
   presupuesto FPR común.
5. Mantener VAE fuera hasta que su generación reproduzca ACF, colas, amplitud y
   duración de regímenes. El VAE previo comprimía colas y no justificó
   augmentación; no hace falta para este piloto.

## Reproducibilidad

- Código: `code/applications/experiments/dq_yolo_curve_tenor_spikes.py`
- Métricas: `results/reports/dq_yolo_curve_tenor_spikes_cleanlabels/summary.json`
- Pesos: `results/reports/dq_yolo_curve_tenor_spikes_cleanlabels/models/`
- Render temporal: `/tmp/dq_yolo_curve_tenor_spikes_cleanlabels/`
- Tests: `tests/test_dq_yolo_curve_tenor_spikes.py`
