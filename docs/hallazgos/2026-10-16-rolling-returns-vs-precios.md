# Experimento: controles de canal sobre retornos rolling

**Estado:** resultado experimental provisional, pendiente de challenge cruzado; no es evidencia confirmatoria para publicación Tier 1.

## Pregunta

¿La ausencia de valor incremental de CNN/XGBoost se debe a que los controles de canal trabajan sobre precios, y mejoran si se calculan sobre ventanas rolling de retornos?

## Protocolo

El experimento ejecutable está en `code/applications/experiments/dq_rolling_return_channel.py`; sus métricas completas y huella del panel están en `results/reports/dq_rolling_return_channel/summary.json`.

Reproducción: `./.venv/bin/python code/applications/experiments/dq_rolling_return_channel.py`.

- Panel real: BRENT, WTI, DTWEXBGS, COPPER y EUROSTOXX50.
- Ventanas de 20 sesiones, stride 5 (75% de solapamiento); test cronológico: 124 ventanas, 2024-01-05 a 2026-09-01.
- Los defectos se inyectan en precios y después se vuelven a calcular retornos y normalización causal. Así se evita inyectar defectos directamente en una representación que no sería la de producción.
- Se comparan canal en precios, retornos acumulados rebasados, retornos crudos y retornos z normalizados causalmente; CNN y XGBoost se entrenan con tres semillas. Entrenamiento CNN en NVIDIA RTX 5060 Laptop GPU.
- Umbrales congelados a partir de una partición temporal posterior de validación limpia; el test no se emplea para seleccionar umbrales.
- XGBoost compara controles de precio frente a un banco ampliado de retorno con features de canal, cross-asset, 3σ, Hampel causal, z-score objetivo y TRIM; una tercera variante añade score CNN al mismo banco ampliado.
- Se compara umbral congelado con dos umbrales rodantes causales de tamaño 68: (i) actualización con todos los scores pasados del flujo observado y (ii) actualización solo con scores previos no alertados. Ninguno usa el score de la ventana evaluada para fijar su propio umbral. Los recalls sintéticos rodantes se evalúan contrafactualmente con el umbral formado por el flujo original no modificado, que no cuenta con adjudicación exhaustiva de calidad.

## Resultado

| Detector | FPR observada OOS | ROC AUC OOS descriptiva |
|---|---:|---:|
| Canal-precio, coherencia | 27,4% | 0,855 |
| Canal-retorno acumulado, coherencia | 26,6% | 0,857 |
| CNN sobre retornos z | 15,1% | 0,790 |
| TRIM, racha de 20 retornos cero | 0,0% | 0,695 |
| Hampel causal sobre retorno objetivo | 6,5% | 0,617 |
| Máximo z rolling, activo objetivo | 9,7% | 0,607 |
| XGBoost, controles de precio | 20,4% | 0,890 |
| XGBoost, banco ampliado de controles de retorno | 34,1% | 0,883 |
| XGBoost, banco ampliado + CNN | 26,1% | 0,875 |

La representación acumulada de retornos ofrece una diferencia pequeña frente al canal-precio en coherencia: +0,002 de AUC y -0,008 de FPR. No es evidencia de mejora robusta. En el banco ampliado, añadir CNN reduce la FPR de 34,1% a 26,1%, pero también reduce AUC de 0,883 a 0,875 y el recall medio de `source_switch` de 76,3% a 63,2%; no demuestra valor incremental general de CNN. XGBoost de precio mantiene la mayor AUC (0,890) y la FPR más baja entre los combinadores (20,4%). Todos los combinadores superan ampliamente el presupuesto nominal de 5% en test.

TRIM cumple exactamente su regla operativa y detecta todas las ventanas etiquetadas como `stale`, sin alertar en las ventanas limpias de este panel. Su AUC agregada no debe compararse como si fuera un detector universal: por construcción no detecta los otros defectos y su resultado positivo depende de que el `stale` sintético produzca 20 retornos exactamente cero. Hampel causal presenta FPR 6,5%, pero baja discriminación agregada (AUC 0,617) y no constituye una victoria global.

La CNN sola discrimina algunos defectos de forma útil (AUC global 0,790; AUC 0,939 para `reversible_jump`, 0,940 para `decoupling`) pero su FPR OOS es 15,1%, tres veces el objetivo nominal del 5%. No es todavía un control operativo calibrado.

### Umbral congelado frente a recalibración rodante

| Detector | FPR congelado | FPR rodante, todos los previos | FPR rodante, solo no-alertas | Recall `source_switch`: congelado → todos los previos | Recall `quantize`: congelado → todos los previos |
|---|---:|---:|---:|---:|---:|
| CNN sobre retornos z | 15,1% | 9,1% | 19,1% | 46,2% → 29,0% | 14,8% → 9,7% |
| XGBoost, controles de precio | 20,4% | 7,0% | 22,6% | 94,4% → 45,4% | 22,0% → 8,3% |
| XGBoost, banco ampliado de retorno | 34,1% | 11,6% | 36,3% | 76,3% → 40,1% | 36,8% → 10,8% |

La actualización con todos los scores pasados reduce falsas alarmas, pero queda
por encima del 5% en estos modelos y pierde sensibilidad en familias retenidas.
Los scores crecen dentro del test y los umbrales finales suben frente a los
iniciales; la bajada de FPR no es una mejora gratuita. La variante que aprende
solo de no-alertas excluye de forma endógena la cola alta, reduce sus umbrales y
aumenta FPR (en el XGBoost de retorno ampliado, 34,1% → 36,3%). “No alertado” no equivale a
“limpio”, y “alertado” no equivale a “defecto”.

**Conclusión de calibración:** recalibrar por rolling sin adjudicación ni
control de contaminación no resuelve la transferencia; puede intercambiar
falsas alarmas por pérdida de recall o inducir sesgo de selección. Ambas
variantes son pruebas metodológicas exploratorias, no estrategias recomendadas
para producción.

## Interpretación

La hipótesis de representación queda parcialmente respaldada como dirección de investigación, pero **no** explica por sí sola la falta de mejora del stack. Los retornos acumulados rebasados y los precios contienen casi la misma geometría para las features invariantes de canal; no son dos fuentes independientes de información. Los retornos diarios preservan bien spikes/stale en algunas features, pero su escala/ruido eleva falsas alarmas si se usa un XGBoost entrenado con el protocolo actual.

No se recomienda reemplazar los controles de precio ni presentar que CNN/XGBoost ya mejoran el estado del arte. Sí queda una señal focal para investigar: CNN parece discriminar defectos de sincronía/saltos, pero requiere calibración y prueba por episodios; stale, tick/cuántización y cambio de proveedor necesitan detectores específicos y fuertes baselines.

## Límites

- Etiquetas positivas sintéticas; no hay prevalencia de incidencias reales ni precisión positiva operacional.
- Solo tres semillas de entrenamiento no son tres muestras independientes de mercado.
- Ventanas de test solapadas al 75%; las métricas por ventana no son inferencia por episodio.
- La calibración dispone de 68 ventanas, por lo que la resolución mínima de la FPR empírica es aproximadamente 1,47 puntos porcentuales. El drift explica que la FPR OOS difiera del 5% nominal.
- Los escenarios de estrés de Lehman, COVID, Ucrania y Liberation Day no se han evaluado aquí como episodios adjudicados; Liberation Day cae dentro del test, pero sigue siendo movimiento real que no debe etiquetarse automáticamente como defecto.
- La supervivencia del canal no se evaluó como detector supervisado en este experimento. Sus features deben probarse como aporte incremental en datos/episodios reservados, no asumirse útiles por describir persistencia.

## Reutilización del arnés legado

No se toma `code/applications/experiments/dq_synthetic_validation.py` como
benchmark temporal de referencia: el registro de challenges lo mantiene
provisional (C3), su resultado histórico fue `reject`, y la inspección del código confirma que no separa
entrenamiento, calibración y test cronológicos. En particular, Hampel usa
ventana centrada; Tukey estima sus vallas sobre la serie completa ya corrupta;
Isolation Forest se ajusta sobre la serie completa evaluada. Esto no invalida
que el experimento responda a su pregunta histórica pre-registrada, pero sí
impide usar sus métricas como prueba OOS de este framework. El nuevo núcleo
`code/applications/dq_framework.py` ofrece baselines causales; todavía debe
integrarse en un arnés pareado que incluya canal/supervivencia y modelos.

## Próximo experimento

1. Fijar comparadores operativos con el mismo presupuesto de falsas alarmas y reportar recall por episodio, además de FPR por ventana.
2. Añadir controles fuertes y transparentes: rachas de retornos cero (umbral TRIM ≥20 sesiones), MAD/colas por retorno, tick/grid por activo y alineación temporal entre pares.
3. Dejar familias completas fuera de entrenamiento (por ejemplo `source_switch` y `quantize`) y evaluar transferencia por activo, no solo por ventana.
4. Evaluar los eventos reales con adjudicación de proveedor/calendario para separar estrés legítimo de corrupción de datos.
5. Probar si variables de canal y supervivencia mejoran de manera incremental a esos baselines sobre un test temporal congelado.
