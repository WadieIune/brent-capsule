# Challenge C5 — `dq_impact`

**Autor:** Agente A (heredado)  
**Auditor:** Agente B  
**Estado:** ❌ refutado en el alcance reclamado; el efecto de saneamiento queda como observación descriptiva.

## Veredicto

El experimento demuestra que transformar el panel crudo en un panel compatible con el motor log-normal cambia materialmente las magnitudes de riesgo, pero no demuestra que el control geométrico sea la causa ni que aporte valor frente a controles fuertes de dominio.

## Evidencia reproducible

El manifiesto `results/reports/dq_impact_manifest.json` reporta WTI negativo el 2020-04-20, concentración de riesgo WTI 0.9845 → 0.2405 (74.4 puntos porcentuales) y retornos cero 31.12% → 0%.

El baseline declarado es únicamente el cuantil de `|retorno|` (q=0.999), aunque el pre-registro exige comparar Hampel/MAD, Tukey, isolation forest y detector de rachas. Ese baseline débil sí detecta el precio no positivo (`true`), por lo que no se establece ventaja de detección para ese caso.

## Checklist de auditoría

1. **Baseline fuerte:** falla; el manifiesto usa el baseline débil que el pre-registro prohíbe.
2. **Control de nivel:** falla para la afirmación de valor del detector; no hay control aleatorio ni comparación a igual carga para `dq_impact`.
3. **Features:** la detección usa geometría, pero la limpieza posterior es `drop_nonpositive` y `to_trading_days`, reglas de dominio independientes de geometría.
4. **Componentes propios:** no se separa el impacto del precio negativo del impacto del calendario; los 74.4 pp son una atribución conjunta.
5. **Fuga temporal:** no es el problema principal de este experimento descriptivo; debe tratarse como comparación de saneamientos, no como validación predictiva.
6. **Degenerados:** no se reporta un caso degenerado en C5.
7. **Verdad de referencia:** ambos defectos se identifican por reglas de dominio directamente observables (`price <= 0`, calendario laborable).
8. **Método especializado:** un filtro de precios no positivos y un calendario de sesiones son rivales especializados y más directos que el canal.
9. **Dato:** el WTI negativo es un evento de mercado real, aunque incompatible con log-retornos; llamarlo “defecto” requiere separar incompatibilidad del modelo y error de captura.
10. **Configuraciones:** el manifiesto no muestra exploración múltiple, pero la ausencia de baseline fuerte impide promover el resultado.

## Alcance que sí sobrevive

Puede afirmarse de forma descriptiva que la gobernanza de datos debe interceptar precios incompatibles con el modelo log-normal y distinguir días de negociación de relleno de calendario antes de calcular riesgo. No puede afirmarse que la geometría del canal sea necesaria, superior, ni la responsable de la mejora.
