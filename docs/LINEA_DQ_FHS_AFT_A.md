# Cierre de alcance: datos, DQ, FHS-EWMA, AFT y CNN descriptiva

Fecha: 2026-10-01. Investigador sugerente delegado. Repositorio inspeccionado:
`/home/wadie/Escritorio/brent-capsule`. No se han editado archivos del repositorio.

## Conclusión para el supervisor

Hay tres resultados distintos que conviene consolidar sin inventar una cadena:

1. FHS-EWMA obtiene un proxy retrospectivo de capital22,71% inferior al VaR
   histórico en un contraste Brent reproducido hoy. No es una evaluación de DQ
   ni demostración de ahorro regulatorio desplegable.
2. XGBoost-AFT ordena supervivencia de canales: C-index medio0,6638, desviación
   entre seis folds0,0072. Su calibración agregada es peor que Kaplan-Meier.
3. CNN clasifica canales ascendentes/descendentes con AUC0,9732/0,9557 según el
   artefacto guardado. Es capacidad descriptiva, no beneficio de depuración o capital.

«Dato limpio alimenta TODO» es una arquitectura deseable, no una propiedad
demostrada del pipeline actual. Los módulos tienen fuentes/cargadores y tratamiento
del calendario distintos; no he localizado una salida DQ canónica consumida por
todos ellos. No cerrar como validada la secuencia DQ→FHS→AFT→CNN.

## Reproducción directa del22,7%

Comando ejecutado sin escritura de bytecode:
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python code/applications/experiments/_h1h3_gate/h1_attrib_h3.py`.
Finalizó correctamente. Fuente declarada por la ejecución:
`data/brent_fred_daily.csv`. Alpha0,99, ventana250, corte2020-08-20.

| Métrica H3 reproducida | VaR histórico móvil | FHS-EWMA |
|---|---:|---:|
| VaR medio |0,07945|0,06772|
| Excepciones en peor ventana250 |8|5|
| Multiplicador de esa ventana |3,75|3,40|
| Proxy `capital_worst` |0,29792|0,23026|
| Tasa de excepciones redondeada |1,38%|1,31%|

Variación del proxy: `0,23026/0,29792-1≈-22,71%`. Número confirmado, alcance
acotado: no son euros sin una exposición declarada; no es ES, ni componente CNN,
ni factorial limpio/sucio. Tampoco cobertura idéntica: las tasas difieren.

El script llama `load_brent` de `h1_cheap.py`, que carga la serie Brent mediante
`common.load_prices`; no llama al módulo de DQ ni consume su salida. H3 calcula
`_historical_var` y `_fhs_var` sobre los mismos retornos Brent. En este contraste
univariado no entra el WTI negativo, objeción que sí afecta a otros experimentos.

## Problemas de atribución y validación del informe anterior

- `kupiec_ok` no implementa el test de Kupiec: devuelve verdadero si la tasa está
  entre0,5% y2%. Etiquetarlo «Kupiec aprobado» es incorrecto. Requiere calcular
  el estadístico formal, independencia y calibración condicional por separado.
- `capital_analysis` de `portfolio_var.py` obtiene k a partir de la peor ventana
  de TODO el test y lo multiplica por el VaR medio de TODO el test. Es un proxy
  retrospectivo de severidad/recargo, no secuencia causal de capital disponible.
- El título de H3 habla de ES, pero la implementación aquí calcula VaR. No
  intercambiar ambas magnitudes.
- El documento `docs/hallazgos/2026-09-11-A-H1-H3-gate-barato-capital.md` atribuye
  al final una conexión CNN-DQ que contradice la auditoría previa y el código:
  geométrico no significa convolucional. Debe corregirse antes de presentación.
- El overlay H1 usa un cuantil de probabilidades sobre todo el test. Ese problema
  no invalida por sí mismo el cálculo numérico H3 separado, pero impide llamar
  desplegable al overlay y mezclarlo con el positivo FHS.
- Cambiar un dato/filtro y reproducir la cifra no equivale a preregistro. El
  experimento H3 se formuló tras análisis previos y sigue siendo exploratorio.

## No confundir22,7% y1,8%

`results/reports/portfolio_var_alert_manifest.json` contiene otro experimento:
cartera de seis commodities,1393 sesiones de test; FHS-EWMA presenta excepciones
1,005%, Kupiec p0,985 y Christoffersen p0,1284; el proxy capital baja1,84% respecto
al histórico. El propio informe dice que la prueba DQ estadística rechaza todos
los estimadores. Estos resultados no son los del contraste univariado22,7%.
No escoger el porcentaje mayor sin explicar activo, muestra, cálculo y comparador.

## DQ: lo implementado y lo pendiente

La ruta `dq_capital_impact.sanitize` utiliza máscaras de precios<=0, eliminación
de filas sin cambios agregados y dropna. No ejecuta CNN ni el detector geométrico
completo. Presenta los problemas ya documentados en
`/tmp/CNN_DQ_XGBOOST_CAPITAL_A.md`: WTI negativo genuino eliminado; retornos de la
ruta sucia calculados con clip a1e-9; calendario/horizonte distintos; primera fila
contada como relleno; cambios de precio usados indebidamente como observaciones
reales. Mantener esas objeciones en la auditoría de cartera, no extrapolarlas sin
distinción al Brent univariado H3.

Un contrato DQ común debe preservar filas originales, procedencia, calendario de
mercado, hora de publicación/ingesta, flags, valores corregidos y cuándo estuvo
disponible la corrección. La salida debe tener versión/hash y todos los modelos
declarar ese mismo input. Repeticiones legítimas y shocks extremos no se borran
por parecer raros; un instrumento que admite precios negativos necesita P&L
compatible. Falta demostrar que esa infraestructura alimenta todos los módulos.

## AFT: cifra y significado exactos

Artefacto: `results/reports/part2_channel_survival_validacion.json`, sección
`walk_forward.summary.q2_xgb_aft`: media0,6638, std0,0072, mínimo0,6557, seis folds.
El±0,007 se refiere a dispersión entre folds, no a un IC95% demostrado.
La sección calibración da MAE XGB-AFT0,0421 frente a KM0,0192; la discriminación
de duración no demuestra probabilidad absoluta más precisa. El artefacto concluye
`SIN EDGE`. No trasladar este C-index al target pérdidas/capital ni al detector DQ.

## CNN: cifra y significado exactos

Artefacto: `results/reports/detector_solo_precio.json`. Canal ascendente AUC
0,9732253642, descendente0,9556638991;1974 observaciones test y corte2020-08-20.
Hoy se verificó el artefacto, no se reentrenó la CNN ni se revalidó su preprocesado.
La revisión previa de escala/procedencia sigue siendo relevante. En todo caso
clasificar una figura de precio no demuestra anticipar shock, limpiar dato o
optimizar capital. Mantenerla como componente descriptivo con ese alcance.

## Siguiente contraste robusto de FHS y DQ

El supervisor desarrolla el factorial DQ×modelo con benchmark FHS/EWMA. Para
converger sin confusores:

1. Calendario y exposición comunes, targets futuros de verdad verificada y
   ventanas equivalentes para todos; DQ cambia información, no problema evaluado.
2. Pronósticos VaR/ES causales; todo parámetro y transformación aprendido con el
   pasado. Si se usa un k ilustrativo, calcular k_t solo con excepciones disponibles
   antes de t y presentar su carácter simplificado, sin titular regulatorio.
3. Comparar reserva/coste a protección comparable con tests formales y pérdida
   realizada. Un proxy menor acompañado de subcobertura no es ahorro válido.
4. Versiones/release-time: un retraso fijo no demuestra ausencia de revisiones
   futuras. Clasificar el backtest como pseudo-tiempo-real cuando no hay vintages.
5. Registrar cadena de fuentes y salida DQ por modelo; solo entonces afirmar que
   la misma capa de datos auditados alimenta todos los componentes.

La línea puede consolidarse como infraestructura de dato auditado más benchmarks
de riesgo y evidencia descriptiva separada. La frase «capital22,7% robusto gracias
a DQ» no está respaldada por el contraste reproducido.
