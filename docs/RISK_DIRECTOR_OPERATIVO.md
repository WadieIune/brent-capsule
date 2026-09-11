# Risk Director operativo diario

Estado: herramienta operativa inmediata, no resultado confirmatorio del paper.
Objetivo: no perder dias de decision mientras se valida la parte academica.

## Fuente mandante

Para la cuarta pata integrada se usa `data/panel_extendido_2026-09-09.csv`.

- Rango del panel: 2007-01-01 a 2026-09-10.
- Brent observado hasta 2026-09-09, ultimo valor 109.51.
- Hash actual: `15388ae2b48b46652c15380ad911890aae4a0f2c18a3eefa62f61ca642ee51d8`.
- Fuente declarada: FRED + Yahoo chart API, sin forward-fill.

`data/brent_fred_daily.csv` queda como historico largo de Brent hasta 2026-06-29.
No manda para decisiones que dependan del tramo julio-septiembre de 2026.

## Ejecucion diaria

```bash
/home/wadie/Escritorio/brent-capsule/.venv/bin/python code/applications/run_all.py \
  --only risk_director_daily \
  --panel data/panel_extendido_2026-09-09.csv \
  --out code/applications/outputs_operational
```

Salidas:

- `code/applications/outputs_operational/risk_director_daily/risk_director_daily.json`
- `code/applications/outputs_operational/risk_director_daily/risk_director_daily.csv`
- `code/applications/outputs_operational/risk_director_daily/run_manifest.json`

## Lectura actual

Run reproducido el 2026-09-11:

- Fecha Brent: 2026-09-09.
- Brent: 109.51.
- Movimiento desde 2026-06-29: +52.97 %.
- Movimiento 20 observaciones: +17.42 %.
- Volatilidad realizada anualizada a 20 observaciones: 44.37 %.
- Percentil de volatilidad en panel 2007-2026: 83.46 %.
- Maximo de volatilidad julio-septiembre: 93.31 % el 2026-08-04.
- Estado operativo: `vigilancia`.

Razones del estado actual:

- El tramo julio-septiembre ya contiene tension de volatilidad.
- Brent cotiza con prima amplia frente a WTI.

Acciones recomendadas para `vigilancia`:

- Revisar sensibilidad de caja/margen a +/-10 y +/-20 USD por barril.
- Comprobar limites internos antes de nuevas posiciones largas/cortas Brent.

## Reglas de uso

1. El monitor se actualiza cada vez que cambie el panel.
2. Ninguna lectura operativa se presenta como causalidad geopolitica sin calendario externo documentado.
3. La salida sirve para decision de riesgo: exposicion, cobertura, escenarios, liquidez y capital.
4. La validacion academica sigue por separado: QLIKE, purga temporal, nulos y challenge cruzado.
5. Si el estado pasa a `alerta` o `crisis`, Risk Director prevalece sobre la redaccion del paper.
