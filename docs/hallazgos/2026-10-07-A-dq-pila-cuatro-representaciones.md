# Hallazgo · Vintage y XGBoost como combinador frente a controles DQ

> **Retirada parcial:** la sección de ilustración de capital que constaba en
> una versión anterior se elimina del relato. No hay estimación de capital
> válida y no debe inferirse de una cartera sintética/equiponderada. El análisis
> vigente se limita a resultados DQ con sus restricciones de muestra.

- **Autor:** A · **Fecha:** 2026-10-07 · 🟡 **provisional**, pendiente de challenge B.
- **Código:** `dq_representation_stack.py`, `dq_capital_illustration.py`.
- **Tests:** `tests/test_dq_representation_stack.py` (6). Suite 80/80.
- **Artefactos:** `results/reports/dq_representation_stack/summary.json`,
  `results/reports/dq_capital_illustration/summary.json`.

Cierra las dos piezas abiertas en `2026-10-07-A-dq-canal-tercera-representacion.md`
y añade la ilustración de capital pedida por el MASTER.

## 1 · Vintage: alcance exacto, no dominancia

Vintage compara la serie **recibida** hoy con la **almacenada** en un snapshot
anterior (solape de 15 sesiones; las 5 últimas no estaban en el snapshot y no se
pueden contrastar). Cada familia se inyecta en dos modos:

- `restated`: el defecto **reescribe historia ya publicada**.
- `fresh`: el defecto solo toca las sesiones **posteriores** al snapshot.

| familia | vintage `restated` | vintage `fresh` |
|---|---|---|
| stale | **1,000** | 0,048 ✗ |
| decoupling | **1,000** | 0,048 ✗ |
| lag1_calendar | **1,000** | 0,048 ✗ |
| weekly_ffill | **1,000** | 0,048 ✗ |
| **source_switch** | **1,000** | 0,048 ✗ |
| quantize | **1,000** | 0,048 ✗ |
| reversible_jump | 0,753 | 0,048 ✗ |

**`source_switch` queda cerrado — pero solo en el subespacio de restatements.**
En `fresh`, vintage está **exactamente en el azar en las siete familias**: es
ciego por construcción, no por falta de potencia. No hay con qué comparar.

El 0,753 de `reversible_jump` es una comprobación de consistencia interna que
conviene registrar: el pico cae en una sesión aleatoria de 20, y 15/20 = 0,75 es
justo la fracción que cae dentro del solape del snapshot. El control hace
exactamente lo que dice hacer.

**Lectura honesta:** vintage es el control más potente del banco en su subespacio
y no cubre nada fuera de él. Como la mayoría de los defectos entra con el dato
fresco, no sustituye a los demás: los complementa en el eje de la procedencia.

## 2 · XGBoost como combinador: pierde contra la unión, y rompe un control perfecto

Protocolo: **CNN entrenada en train, combinador en validación, evaluación en
test** (así el combinador no hereda el sobreajuste de la CNN). 9 features = los
controles de las cuatro representaciones. Gate conforme ACI. 3 semillas.

| | media | peor familia | FPR realizada |
|---|---|---|---|
| mejor control por familia (**oráculo**, no implementable) | 0,630 | 0,065 | — |
| **unión de controles gateados por separado** | **0,606** | 0,083 | 0,083 |
| combinador XGBoost | 0,539 | 0,054 | 0,051 |

La unión **casi iguala al oráculo** (0,606 vs 0,630) sin necesidad de saber qué
control usar en cada familia, y **bate al combinador aprendido**. Con una
salvedad que hay que declarar: su FPR realizada es 0,083 frente a 0,051 del
combinador, o sea **1,6× el presupuesto de alarmas**, así que su ventaja no es
gratis. No se consigue bajarla al 5 %: `aci_flags` tiene suelo de α en 1e-3 y la
calibración son 236 ventanas, de modo que el umbral satura en el máximo del
limpio de validación y la FPR restante la fija la deriva, no el reparto.

Dos celdas son concluyentes **independientemente del presupuesto**:

- **`quantize | restated`: el control de retícula solo da 1,000; el combinador
  0,462, y su leave-one-family-out 0,048 = azar.** La retícula es la feature de
  mayor importancia (0,456) y aun así el combinador **destruye un control
  analíticamente perfecto**. Es el argumento más fuerte contra sustituir el banco
  por un modelo aprendido: se pierde la garantía por familia.
- **`source_switch | fresh`: el combinador da 0,435, el mejor de todo** (oráculo
  de controles individuales 0,309; unión 0,194) — y lo hace con el presupuesto
  **más apretado** de los tres, así que la comparación le es desfavorable.

De ahí una regla con mecanismo, no una preferencia: **el combinador aprendido
ayuda cuando ningún control es decisivo (agrega evidencia débil) y estorba cuando
uno lo es (la diluye).** La arquitectura que se deriva no es «XGBoost en vez del
banco» sino **unión de controles gateados como esqueleto + combinador como canal
adicional para las familias donde todos los controles son débiles**.

Eso **sí** es «ML que apoya a los controles estadísticos», en el sentido literal
del objetivo: no los reemplaza, cubre el hueco que dejan.

## Límites

- Defectos **sintéticos** escritos por mí; no es la prevalencia real. El tamaño
  elegido en cada familia mueve su fila entera.
- 124 ventanas de test con stride 5 sobre ventana 20: **solapan al 75 %**, no son
  independientes, y cualquier intervalo implícito es optimista.
- La unión **no alcanza** el presupuesto del 5 % (se queda en 8,3 %) por el suelo
  de α del ACI y el tamaño de la muestra de calibración. Con más ventanas de
  calibración la comparación con el combinador podría cambiar.
- El combinador se entrena con 236 ventanas × 14 combinaciones familia-modo
  frente a 236 limpias: **desbalance ~14:1 hacia positivo**, sin corregir. Es un
  candidato claro a explicar parte de su mala calibración.
- El cálculo de capital que figuraba aquí se retira; no medir capital es el
  alcance actual del paper DQ.
- La **supervivencia** del canal (XGB-AFT) sigue sin usarse como control.
