# Resultado exploratorio: VAE de Brent con recalibración por régimen

- **Fecha:** 2026-10-06
- **Código:** `code/applications/experiments/brent_regime_autoencoder.py`
- **Datos:** `data/brent_fred_daily.csv`, Brent diario 1987-05-20 a 2026-06-29
  (9.922 precios; SHA-256 en el JSON de resultados).
- **Reproducción:** `.venv/bin/python code/applications/experiments/brent_regime_autoencoder.py`
- **Estado:** exploratorio; pendiente de challenge supervisor.

## Diseño ejecutado

VAE de ventanas trailing de 32 log-retornos (32→16→4→16→32), prior latente
gaussiano, MSE + `0.01 × KL`, semilla fija. Comparación annual walk-forward
2000-2025 entre recalibración anual sobre cinco años, VAE congelado desde el
fit pre-2000 y EWMA λ=0.94. Escaladores, pesos y clusters se ajustan en train;
el holdout temporal inmediato calibra umbral para ~20 revisiones/año con
cooldown común de diez sesiones. Los episodios de caídas son el peor decil
rolling-train de retornos acumulados a diez sesiones, con labels purgados en
fronteras. El identificador de estado/latente es local al fold.

## Resultados

Promedio no ponderado de los 26 recalls anuales:

| Modelo | Recall episodios | Falsas alarmas/año | Revisiones/año | MSE reconstrucción OOS |
|---|---:|---:|---:|---:|
| VAE adaptativo anual | 0,478 | 10,21 | 13,34 | 1,220 |
| VAE congelado | 0,537 | 10,33 | 13,65 | 1,145 |
| EWMA 0,94 | 0,489 | 10,29 | 13,49 | — |

El objetivo de 20 revisiones/año no es siempre alcanzable tras cooldown; se
publican las cargas efectivas (validación y test) en vez de llamarlas iguales.
Bootstrap circular pareado por bloques de tres años (5.000 draws): adaptativo
menos congelado = **−0,059**, IC95% **[−0,113, −0,010]**; adaptativo menos EWMA =
**−0,010**, IC95% **[−0,063, 0,058]**. Esto desaconseja la recalibración anual
como mejora de alerta; la comparación con EWMA no acredita incremento.

Diagnóstico de generación desde el prior del VAE congelado, 512 ventanas:

| Estadístico diario | Real pre-2000 | Generado |
|---|---:|---:|
| Desviación estándar | 0,0231 | 0,0256 |
| Cuantil 1 % | −0,0582 | −0,0587 |
| Cuantil 99 % | 0,0614 | 0,0592 |
| Autocorrelación lag 1 dentro de ventana | 0,054 | −0,011 |

Con el ruido de observación gaussiano del decoder, las colas **marginales** se
aproximan en esta calibración; la dinámica serial no. Eso es una comprobación de
generación descriptiva, no validación de una distribución conjunta útil para
simular P&L. El espacio latente perfila retorno/volatilidad/drawdown recientes,
pero no explica causas ni fija estados comparables entre folds.

## Conclusión propuesta a B

La recalibración anual no mejora la priorización de revisión y pierde frente al
VAE congelado; no domina EWMA. La utilidad actual del VAE es **resumir ventanas**
y explorar configuraciones, no proteger capital. No conectar este score con una
reducción de gross long antes de que un backtest de cartera multiactivo lo
supere neto de costes y contra FHS-EWMA/solo-vol. Sharpe, alpha y capital no
quedan demostrados por este experimento.
