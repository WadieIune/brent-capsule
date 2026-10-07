# Hallazgo · CNN 1D supervisada para Data Quality de series de precios

- **Autor:** A · **Fecha:** 2026-10-07 · resultado exploratorio, pendiente de challenge B.
- **Código:** `code/applications/experiments/dq_cnn1d_supervised.py`.
- **Artefactos:** `results/reports/dq_cnn1d_supervised*/summary.json`.
- **Datos:** `data/panel_extendido_2026-09-09.csv`, 2007-01-02 a 2026-09-09,
  SHA-256 `b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3`.

## Diseño

CNN convolucional 1D sobre ventanas de 20 sesiones y seis series simultáneas:
BRENT, WTI, GOLD, SILVER, COPPER y NATGAS. Rendimientos normalizados por media
y desviación rolling de 60 sesiones, ambos desplazados una sesión. WTI usa
diferencias de precio en dólares, para preservar el settlement negativo real de
abril de 2020; no se recorta ni elimina como si fuera corrupción. Se usan
ventanas con stride de 5 sesiones; ventanas de 20 sesiones de purga impiden que
una ventana cruce los cortes.

- Train hasta 2018-12-31: 592 ventanas.
- Validación 2019-01-01 a 2023-12-31: 242 ventanas; calibración de umbral al 5 %
  de falsas alarmas y selección de época con inyecciones separadas.
- Test 2024-01-03 a 2026-09-09: 128 ventanas, stride 5. Las ventanas solapan;
  no son 128 observaciones independientes.
- Familias inyectadas en ventanas reales: desacoplamiento Brent/pares por
  desplazamiento circular (marginal y forma univariada aproximadamente
  preservadas), stale Brent y salto reversible Brent. Una misma CNN entrenada
  con las tres familias. Baselines: score máximo 3σ causal y `1−R²` cross-asset.
- Semillas 42, 71 y 123. Umbrales fijados en validación; no se recalibran en test.

## Resultados

Media sobre tres semillas; recall por familia y tasa de falsas alarmas observada
en ventanas limpias del test:

| Detector | Desacoplamiento | Stale | Salto reversible | FPR test |
|---|---:|---:|---:|---:|
| CNN 1D supervisada | 0,974 | 0,997 | **0,997** | 0,112 |
| Cross-asset `1−R²` | 0,956 | **1,000** | 0,857 | 0,102 |
| 3σ normalizado | 0,086 | 0,086 | 0,893 | **0,086** |

La CNN añade aproximadamente **14 pp de recall en saltos reversibles** sobre el
cross-asset; en desacoplamiento la diferencia media es ~2 pp y en stale no
mejora. La FPR OOS de CNN es ~1 pp mayor que `1−R²` y ~2,6 pp mayor que 3σ.
Además, en seed 123 la FPR CNN llega a 15,6 %. El umbral de validación (≈5 %) no
mantiene exactamente esa carga OOS.

## Lectura y límites

Hay una señal de valor incremental **especializada** para detectar saltos
reversibles multiactivo; no se acredita una mejora general de calidad ni un
despliegue operativo. La ventaja debe confirmarse con eventos de feed reales,
revisión humana etiquetada, bootstrap por bloques/episodios (las ventanas se
solapan), costes de revisión y una carga FPR estable. La inyección de salto es
fácil de reconocer (±8 desviaciones normalizadas en dos días); se requieren
severidades y defectos no vistos durante el entrenamiento.

La CNN no reemplaza TRIM (≥20 retornos cero), la regla 3σ ni el control barato
`1−R²`; puede ser una señal adicional para priorizar episodios de salto
reversible. CNN no toca automáticamente los datos: una alerta debe llevar a
cuarentena/revisión o a una fuente autorizada, nunca a borrar/reconstruir sin
procedencia.

La arquitectura completa conserva la **detección de canales y su supervivencia**
como capa posterior: DQ primero determina aptitud/confianza de la serie; el
detector de canales y supervivencia describe estructura/persistencia sobre
observaciones admitidas; Risk Director consume ambos resultados con sus
versiones y procedencia. No se han usado supervivencia ni labels de canal como
verdad de DQ.

**XGBoost DQ y el VAE generativo Brent no están integrados ni comparados en esta
prueba.** Tampoco se ha demostrado que el VAE genere defectos de calidad. La
extensión generativa debe modelar defectos plausibles, sin contaminar train/test,
y batir controles deterministas y CNN a carga emparejada. Mantener esta
conclusión como propuesta hasta la revisión de B.
