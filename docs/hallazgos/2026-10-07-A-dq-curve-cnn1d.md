# Hallazgo · CNN 1D y control de shape en curva de tipos

- **Autor:** A · **Fecha:** 2026-10-07 · evaluación exploratoria, pendiente de challenge B.
- **Código:** `code/applications/experiments/dq_curve_cnn1d.py`.
- **Artefactos:** `results/reports/dq_curve_cnn1d*/`.
- **Fuente:** `data/panel_extendido_2026-09-09.csv`, SHA-256
  `b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3`.

## Contrato y diseño

La hipótesis del MASTER es estructural: un error pequeño en un nodo puede ser
normal en su propia serie temporal y, aun así, romper smoothness o la relación
de hedge con otro tenor/instrumento. Se evalúa un precursor de esa hipótesis con
la única curva multitenor disponible: **US Treasury CMT DGS2/DGS10/DGS30**. No
son nodos de una curva ZC bootstrapped. El panel no contiene DGS5 ni la pareja
GBP base/SONIA; con tres nodos tampoco se puede evaluar Svensson de forma
identificada.

CNN convolucional 1D recibe la curva de una fecha (niveles centrados, en bp).
Train hasta 2018, validación 2019-2023 y test 2024-09/2026; el modelo aprende
con curvas limpias y bumps sintéticos de 2-4 bp en el nodo 10Y. Se calibran
umbrales al 2% de FPR en validación. En test se inyecta un bump puntual 10Y de
1, 2, 3, 4, 5 u 8 bp sobre cada curva observada.

Baselines en la misma carga de validación: (i) 3σ causal por nodo sobre cambios
diarios de yield, (ii) residuo de interpolación lineal 2Y-30Y en log-tenor para
el nodo 10Y. Tres semillas (42/71/123). Es una prueba de recuperación de
perturbaciones conocidas, no etiquetas de corrupción real.

## Resultados

Media de tres semillas; cada cifra de recall es la fracción de curvas de test
que alerta tras añadir el bump especificado:

| Bump aislado en 10Y | CNN 1D | Residuo lineal cross-tenor | 3σ temporal/nodo |
|---:|---:|---:|---:|
| 1 bp | 0,499 | **0,991** | 0,018 |
| 2 bp | 0,499 | **0,991** | 0,018 |
| 3 bp | 0,500 | **0,991** | 0,018 |
| 4 bp | 0,500 | **0,991** | 0,018 |
| 5 bp | 0,501 | **0,989** | 0,018 |
| 8 bp | 0,501 | **0,989** | 0,018 |

La FPR limpia de test fue 0 para CNN y residuo lineal, y 1,8% para 3σ; los
umbrales se fijaron solo con validación. La FPR de CNN fue inestable por semilla
en la **detección de bumps**: recall para un bump de 1 bp varió entre 0,247 y
0,769, frente a ~0,991 estable del control lineal.

## Lectura

1. El control de forma **sí aporta frente a 3σ puntual** para el defecto
   construido: la anomalía es cross-tenor, no un gran cambio temporal.
2. En este panel y con tres nodos, la CNN no aporta frente al control simple de
   interpolación en log-tenor: detecta menos bumps y es más sensible a la
   semilla. **No pasa el gate de complejidad/valor incremental.** El resultado
   favorable pertenece al control de shape, no al deep learning.
3. No se afirma que Svensson esté implementado ni que los CMT sean una curva ZC.
   Para evaluar el caso real hacen falta curvas bootstrapped con malla de tenores
   suficiente y cotizaciones/versiones fuente.

## Próximo gate

Antes de reabrir CNN: (a) construir/obtener ZC y OIS por convención e instrumento;
(b) representar por tenor, fecha, instrumento y vintage con precisión numérica;
(c) inyectar bumps localizados y desalineamientos entre pares con hedge ratio y
DV01 estimados solo en train (correlación >98% es un filtro, no una cobertura por
sí misma); (d) comparar a igual FPR/curva-mes contra 3σ, interpolación, Svensson
residual y checks de arbitraje; (e) incluir bumps suaves válidos, cambios de
régimen y defectos no vistos para medir falsos positivos. La heatmap puede
servir de explicación visual; el modelo debe consumir el tensor numérico.

Splits y reversiones históricas requieren fuente de acciones corporativas y
vintages, no se deben etiquetar solo por un movimiento de 2%. El smile de
volatilidad necesita una prueba distinta de arbitraje calendar/butterfly y un
grid strike-tenor válido.

Detección de canales y supervivencia permanecen en el framework: DQ valida la
serie/superficie primero; los canales describen estructura y supervivencia sirve
al análisis de riesgo posterior. Esta prueba no usa esos modelos como etiquetas.

## Match con CNN 1D y línea YOLO

El resultado de B con curva multi-tenor sintética tipo Nelson-Siegel responde a
otra pregunta que este test CMT de tres nodos. Hay que comparar ambos en un
único arnés: mismas curvas limpias y corruptas, mismos splits, mismas
inyecciones (spikes locales, desplazamientos paralelos y pares base/RFR), y
umbral fijado en validación al mismo presupuesto de falsas alarmas. La métrica
debe ser por evento y curva-fecha, además de recall por amplitud; no basta con
clasificar una ventana como anómala. B favorece el residuo Nelson-Siegel en su
generador; este test favorece interpolación log-tenor en CMT observado. No son
la misma muestra y no se deben combinar como una comparación directa.

YOLO es una hipótesis de **localización**, no una alternativa naturalmente mejor
para modelar la serie: se podría rasterizar fecha×tenor o tiempo×valor y etiquetar
cajas alrededor de kinks/spikes, para que el detector devuelva clase, confianza
y coordenadas; luego se mapean a fecha y tenor. Esto puede ayudar en la revisión
humana de dónde está el defecto, pero la imagen no debe reemplazar valores
numéricos ni checks financieros. Resolución, escala/ejes y cuantización en bp
pueden cambiar la geometría o perder exactitud. El control primario debe seguir
siendo numérico (CNN 1D/residuo); YOLO sería comparador de localización con recall
de eventos, IoU temporal-tenor y FPR por curva-fecha, usando rasterización
congelada y sin augmentations que alteren el significado financiero.

Este informe de curva no evaluó YOLO. En un experimento separado se descargó y
entrenó YOLO11n para spikes de log-volatilidad; no es evidencia transferible a
curvas. La documentación oficial define su salida como cajas/clases y exige
etiquetas bbox normalizadas; eso habilita localización interpretable, pero no
demuestra mejora DQ numérica
([Detect](https://docs.ultralytics.com/tasks/detect),
[formato de datasets](https://docs.ultralytics.com/datasets/detect)).

### Challenge solicitado a B

1. Repetir su CNN supervisada en el mismo protocolo, publicando recall/FPR del
   residuo NS y 3σ con umbral solo de validación.
2. Auditar que las etiquetas representen el evento (pico/nodo/fecha), no toda
   una región transformada. Para back-adjustment de equity, contrastar nivel,
   vintage y retorno en el empalme; etiquetar toda la historia ajustada puede
   diluir el recall de métodos de retorno.
3. Si interesa YOLO, acordar antes un benchmark pareado y la disponibilidad de
   la dependencia; no atribuir valor por una visualización más atractiva.
