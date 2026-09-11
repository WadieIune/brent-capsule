# Decision supervisora B: roles, Brent oficial y cuarta pata

Fecha: 2026-09-11. Autoridad: B como agente supervisor por decision del usuario.
Estado: decision operativa, no resultado empirico nuevo.

## Veredicto sobre los fallos reportados

No evaluo intencion ni uso la palabra sabotaje como criterio tecnico. El patron relevante es operativo: tres fallos de A compartieron la misma raiz, aceptar una salida sin comprobar el artefacto exacto que la generaba. Desde ahora, las propuestas de A no entran como veredictos; entran como hipotesis o insumos hasta que B las valide.

Fallos convertidos en controles:

1. Marcadores de conflicto en `main` -> todo cambio que toque importabilidad debe probar import real antes de publicarse.
2. Normalizacion sesgada -> toda mejora debe compararse contra el artefacto/base exacto y registrar la transformacion usada.
3. Fichero de Brent equivocado -> toda afirmacion de datos debe citar fichero, rango temporal, hash cuando aplique y regla de prioridad entre fuentes.

## Decision sobre Brent y 2026

Acepto dos fuentes mandantes segun uso: `data/brent_fred_daily.csv` para historico largo de Brent hasta 2026-06-29, y `data/panel_extendido_2026-09-09.csv` para la cuarta pata integrada y cualquier afirmacion que toque julio-septiembre de 2026.

Verificacion reproducida por B sobre `panel_extendido_2026-09-09.csv`:

- filas: 5.139; columnas: 22 incluyendo `date`
- rango de panel: 2007-01-01 a 2026-09-10
- Brent observado: 2007-01-02 a 2026-09-09, ultimo valor 109.51
- sha256: `3b351ce135fccd9d958aaca3d13617daf453ba0194c318523000b16ed7dbdf68`
- exogenas principales: VIX, SP500, DAX, EUROSTOXX50, GOLD, SILVER y COPPER hasta 2026-09-10; WTI, DGS2, DGS10, DGS30, NATGAS y EURUSD hasta 2026-09-09; DTWEXBGS hasta 2026-09-04
- volatilidad anualizada movil de 20 log-retornos, sin relleno: maximo 2026 = 1.1242102397297729 el 2026-04-17; maximo julio-septiembre = 0.933137346514275 el 2026-08-04
- serie combinada 1987-2026 con extension de septiembre: 63 observaciones de 2026 entre las 400 mayores volatilidades, 20 de ellas entre julio y septiembre
- universo del panel extendido 2007-2026: 89 observaciones de 2026 entre las 400 mayores volatilidades, 32 de ellas entre julio y septiembre

Conclusion: era falso decir que el episodio de 2026 no estaba en los datos o que aportaba cero dias entre los 400 mayores. Ahora tambien seria incompleto cerrar el corte en 2026-06-29: hay un tramo julio-septiembre con Brent hasta 109.51 y volatilidad elevada. La atribucion causal a Ormuz u otra causa sigue pendiente de fechas externas y calendario causal.

## Decision sobre la cuarta pata

Ruta aprobada:

1. WP-V1/WP-V2 avanza ya sobre Brent extendido hasta septiembre de 2026: retornos, volatilidad, log-varianza, semivarianzas, estacionalidad causal y representaciones CNN/temporales.
2. Por instruccion MASTER del usuario, WP-V3 debe usar el panel extendido hasta septiembre de 2026. No queda como opcion acotar la capa exogena a 2026-03-06 para la evaluacion principal.
3. A debe entregar primero el panel extendido y su contrato temporal: `release_time`, `vintage_time` cuando aplique, fuente, instrumento, unidad, calendario, `ingestion_time`, hash y join as-of verificable. Variables no extensibles se excluyen de la evaluacion 2026 o se justifican como diagnostico separado.
4. Mientras esa extension no exista, WP-V1/WP-V2 pueden avanzar sobre Brent FRED; WP-V3 y el Risk Director integrado no se validan sobre 2026.
5. Risk Director se medira como decision: demora, excepciones, coste, capital o deficit de cobertura a exposicion comparable. No se valida por QLIKE solamente.

## Instruccion MASTER recibida

El usuario ha fijado como MASTER del proyecto que hay que extender todo hasta el dato disponible de septiembre de 2026. Esta decision prevalece sobre la alternativa previa de acotar WP-V3 a 2026-03-06 y sobre el corte intermedio 2026-06-29. B la adopta como requisito de avance: sin auditoria del panel exogeno extendido no hay evaluacion integrada CNN-info-Risk Director sobre 2026.

## Regla de gobierno

A puede proponer, desafiar y ejecutar tareas acordadas. B decide que entra en `main`, que entra en el paper y que queda como negativo, degradado o provisional. Cualquier resultado sin challenge cruzado queda provisional.
