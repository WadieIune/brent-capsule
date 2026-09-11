# Evaluacion cientifica B: informacion externa y Risk Director

Fecha: 2026-09-11. Estado: provisional, pendiente de challenge de A.
Objetivo: empezar el cierre cientifico de la cadena CNN -> informacion -> Risk Director con el panel extendido validado.

## Base de datos usada

Panel: `data/panel_extendido_2026-09-09.csv`.
Hash: `3b351ce135fccd9d958aaca3d13617daf453ba0194c318523000b16ed7dbdf68`.
Verificacion: `data/verify_panel.py` pasa completa.

El panel queda fechado por observacion, sin forward-fill. La disponibilidad exacta por publicacion/vintage todavia debe imponerse por variable antes de cualquier afirmacion operacional fuerte. EURUSD de Yahoo fue rechazado por posible look-ahead; queda sin extension fiable y se conserva solo hasta 2026-03-06.

## Bateria ejecutada

Script: `code/applications/experiments/risk_director_scientific_eval.py`.
Salida: `code/applications/outputs_scientific/risk_director_scientific_eval/summary.json`.

Diseno:

- Objetivo: media de los diez log-retornos cuadrados futuros de Brent.
- Baseline: EWMA o HAR, elegido cada ano por validacion temporal previa.
- Variante: mismo baseline + informacion externa del panel extendido.
- Evaluacion: walk-forward anual, purga de etiquetas antes de test, QLIKE pareada.
- Test producido: 671 pronosticos, de 2024-01-02 a 2026-08-25.

## Resultado principal

Delta QLIKE = perdida externa menos perdida baseline. Negativo favorece informacion externa.

- Delta medio: `+0.047286`.
- IC 95 % por bloques de 20: `[-0.020904, +0.132248]`.
- Por anos:
  - 2024: `-0.026228`.
  - 2025: `+0.088317`.
  - 2026: `+0.097845`.

Veredicto supervisor: no hay evidencia suficiente para afirmar que la capa externa mejore el pronostico QLIKE a diez sesiones. En 2026, precisamente el ano operativo relevante, la especificacion externa fija empeora el baseline.

## Lectura para Risk Director

Aunque QLIKE no mejora, el contraste de alertas top-decile muestra una senal operativa pequena:

- Precision baseline: `0.7941`.
- Precision externa: `0.8088`.
- Captura baseline: `0.3776`.
- Captura externa: `0.3846`.
- Ratio target medio alerta/resto baseline: `4.334`.
- Ratio target medio alerta/resto externo: `4.451`.

Esto no basta para cerrar una afirmacion estadistica fuerte, pero si justifica seguir usando el panel extendido en el Risk Director como monitor de vigilancia y escenarios, no como motor autonomo de forecast.

## Conexion con la CNN

El resultado CNN previo de B (`regime_cnn_forward_variance`) no cumplio el gate local de mejora incremental. Por tanto, la cadena no se debe escribir como CNN validada -> riesgo validado. La version cientificamente honesta es:

1. CNN sobre precio/canal: util como representacion geometrica, no validada como mejora de riesgo.
2. Transformacion a volatilidad/riesgo: necesaria y ya motivada.
3. Informacion externa: operacionalmente relevante, pero aun no mejora QLIKE con esta especificacion fija.
4. Risk Director: aplicacion inmediata como monitor de vigilancia, escenarios y revision de limites.

La siguiente prueba cientifica debe separar representacion y decision: comparar CNN temporal sobre volatilidad contra un modelo tabular con las mismas entradas, y despues medir utilidad economica de la politica de alertas, no solo QLIKE.

## Decision

Estado: `provisional/degradado`.

No entra al paper como resultado positivo. Si entra, debe entrar como resultado de disciplina metodologica: el sistema operativo detecta tension real en 2026, pero la mejora predictiva incremental de la informacion externa aun no queda demostrada frente a EWMA/HAR. La aplicacion al negocio se sostiene como monitor y protocolo de decision, no como predictor causal cerrado.
