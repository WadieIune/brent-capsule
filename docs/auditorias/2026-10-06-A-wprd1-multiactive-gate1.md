# WP-RD1 Gate multiactivo: resultado exploratorio para challenge

- **Fecha:** 2026-10-06
- **Código:** `code/applications/experiments/wprd1_multiactive_policy.py`
- **Datos:** `data/panel_extendido_2026-09-09.csv`, joint weekday panel
  2007-01-02–2026-09-09, 4.887 filas, SHA-256 registrado en el summary.
- **Resultado:** exploratorio, proxy no invertible; pendiente de revisión B.

## Protocolo

Cesta igual-weight de seis series, representada como variaciones de settlement
escaladas por la desviación de `Δprecio` estimada solo en train (una unidad de
riesgo por pata). El precio negativo de WTI en 2020-04-20 (**−36,98** en el
panel) se conserva, no se calcula retorno logarítmico ni se elimina la sesión.
La anchura del canal se expresa en unidades de precio. WTI se excluye de las
features de supervivencia basadas en ratios en **todos** los folds; la
contribución al risk score de supervivencia se renormaliza sobre las otras cinco
patas. No hay pesos, multiplicadores ni libro ejecutado del MASTER.

13 folds anuales 2014–2026; los 12 años completos 2014–2025 forman el agregado,
2026 es caso parcial aparte. Cada fold ajusta escalas, contribuciones de riesgo
y supervivencia con el pasado disponible; episodios de entrenamiento se
extraen con el panel truncado al corte. La cobertura adversa es retorno de
cartera a diez sesiones bajo el cuantil 10 % del train, fusionando excedencias
separadas por menos de diez sesiones. El FHS-EWMA de referencia usa bloques
solapados de diez residuos de cartera filtrados por EWMA (historial 252 sesiones)
y sigma actual. El operating point apunta a veinte revisiones/año en
validación; el cooldown de diez sesiones hace que la carga efectiva pueda ser
menor. Todos los modelos usan exposición objetivo 100 %, reducción común a 50 %
durante diez sesiones y sensibilidades de coste proxy 2/5/10 pb por unidad de
turnover.

## Alertas de riesgo

Recall **ponderado por episodios** sobre 50 episodios test completos:

| Señal | Capturados | Recall | Revisiones/año | Falsas alarmas/año |
|---|---:|---:|---:|---:|
| FHS-EWMA por bloques | 29/50 | 0,58 | 14,72 | 12,24 |
| Solo-vol EWMA | 37/50 | 0,74 | 16,36 | 13,19 |
| Vol + régimen | 33/50 | 0,66 | 14,99 | 12,16 |
| Vol + supervivencia | 39/50 | 0,78 | 16,86 | 13,53 |
| Vol + régimen + supervivencia | 37/50 | 0,74 | 15,92 | 12,76 |

La supervivencia aislada eleva la cobertura descriptiva respecto al FHS, pero
realiza unas 2,1 revisiones adicionales/año. Bootstrap circular pareado por
bloques de dos años (diez años con métricas pareadas): supervivencia−FHS
**+0,124**, IC95 **[−0,050, 0,321]**; combinación−FHS **+0,062**, IC95
**[−0,200, 0,283]**. Ambos intervalos incluyen cero. La combinación tampoco
supera a solo-vol en los episodios observados. La frecuencia realizada no es
idéntica entre políticas, pese a calibrar el punto cercano al presupuesto común;
no vender esta tabla como comparación a cargas exactamente igualadas.

## Reducción de gross long simulada

Con sensibilidad de costes de 5 pb por unidad de turnover, promedios 2014–2025:

| Señal | Exposición media | Sharpe proxy neto | ES-10d proxy | Drawdown proxy | Turnover |
|---|---:|---:|---:|---:|---:|
| FHS-EWMA | 0,717 | 0,445 | −2,286 | 7,321 | 2,08 |
| Solo-vol | 0,686 | 0,346 | −2,125 | 7,435 | 2,50 |
| Vol + supervivencia | 0,672 | 0,330 | −2,149 | 7,357 | 2,92 |
| Vol + régimen + supervivencia | 0,688 | 0,380 | −2,256 | 7,613 | 3,67 |

Lectura: supervivencia reduce más la exposición y el ES empeora menos que en
FHS en estas unidades proxy, pero su Sharpe proxy neto es menor y su turnover
mayor. La combinación no domina a FHS en el conjunto de métricas. Los costes
son multiplicados por turnover de un P&L normalizado sin nocional monetario,
así que son una sensibilidad matemática común, no costes de mercado calibrados.
Estas cifras **no son EUR, VaR regulatorio, capital real, alpha ni Sharpe
invertible**; drawdown/ES usan P&L de unidades de riesgo, y los intervalos de
excepción no se han validado con cobertura regulatoria.

## Challenge solicitado a B

1. Revisar la representación de P&L `Δprecio/σ_train` y el fixed 1/N risk-unit
   proxy, en particular la aptitud de 2–10 pb de coste proxy.
2. Auditar los episodios/ventanas de scoring y la interpretación de FHS 10d por
   bloques residuales con sigma constante en el horizonte.
3. Decidir si el delta de supervivencia merece una segunda prueba con un
   presupuesto de revisiones efectivamente emparejado en test, o si se mantiene
   solo como herramienta de priorización sin policy de capital.

No modificar retrospectivamente este registro; cualquier sensibilidad nueva
debe quedar identificada como análisis nuevo y no reemplazar el resultado.
