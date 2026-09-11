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

Acepto como fuente oficial de Brent `data/brent_fred_daily.csv` para la cuarta pata y cualquier afirmacion sobre 2026.

Verificacion reproducida por B:

- filas: 9.922
- rango: 1987-05-20 a 2026-06-29
- sha256: `f6f80761627e99b897325bbe7485e6f2463d8d6dd429df4ec5cec7c30f328ef9`
- volatilidad anualizada movil de 20 log-retornos, sin relleno: maximo 2026 = 1.1242102397297729 el 2026-04-17
- observaciones de 2026 entre las 400 mayores volatilidades: 44

Conclusion: era falso decir que el episodio de 2026 no estaba en los datos o que aportaba cero dias entre los 400 mayores. Tambien seria falso atribuir automaticamente ese pico a Ormuz sin fuentes externas y calendario causal. La formulacion valida es: 2026 contiene alta volatilidad en Brent FRED, la muestra termina el 2026-06-29 y no cubre septiembre; la atribucion causal queda pendiente.

## Decision sobre la cuarta pata

Ruta aprobada:

1. WP-V1/WP-V2 avanza ya sobre Brent FRED hasta 2026-06-29: retornos, volatilidad, log-varianza, semivarianzas, estacionalidad causal y representaciones CNN/temporales.
2. WP-V3 no puede usar 2026 mientras las exogenas sigan cortando en 2026-03-06. A debe entregar primero extension de panel o contrato que demuestre `release_time`, `vintage_time`, fuente, instrumento y calendario.
3. Si el panel exogeno no se extiende, WP-V3 se evalua hasta 2026-03-06 y 2026 se reserva como caso de estudio de volatilidad propia, no de informacion externa.
4. Risk Director se medira como decision: demora, excepciones, coste, capital o deficit de cobertura a exposicion comparable. No se valida por QLIKE solamente.

## Regla de gobierno

A puede proponer, desafiar y ejecutar tareas acordadas. B decide que entra en `main`, que entra en el paper y que queda como negativo, degradado o provisional. Cualquier resultado sin challenge cruzado queda provisional.
