# Hallazgo · El veredicto "la CNN no aporta" venía de comparar a FPR distinta; el valor real de la red es cubrir el espacio nulo de los controles baratos

- **Autor:** A · **Fecha:** 2026-10-07 · 🟠 **autodegradado**, pendiente de challenge B.
  La §4 **retracta** la afirmación central de la primera versión de este documento.
- **Código:** `code/applications/experiments/dq_conformal_gate.py`.
- **Tests:** `tests/test_dq_conformal_gate.py` (7 pruebas).
- **Artefactos:** `results/reports/dq_conformal_gate/summary.json`.
- **Datos:** `data/panel_extendido_2026-09-09.csv`, SHA-256
  `b5512282a5e7d42d01000dd687893d1fa26e5ef470aedbded8fad91fd355f7f3`.
- **Desafía:** `docs/hallazgos/2026-10-07-A-dq-cnn1d-supervisada.md` y, por
  extensión, la frase del plan «las redes no baten a los controles explícitos».

## 1. El defecto de protocolo

`dq_cnn1d_supervised` calibra el umbral sobre la validación 2019-2023 y lo
**congela** para el test 2024-2026. Con deriva de distribución, la CNN acabó
operando al **19,9 %** de falsas alarmas frente al **9,7 %** del control
cross-asset, con objetivo 5 % para ambos. Las dos columnas del informe —recall y
FPR— no son por tanto comparables: se midió el recall de cada detector **en un
punto de operación distinto**, y el que más alertaba parecía el más sensible a la
vez que incumplía el presupuesto.

El plan exige explícitamente «a tasa de falsos positivos **emparejada**». La
implementación empareja la FPR *en validación*, no la realizada en test. Ese es
el error, y es el mismo género de fallo que el checklist de challenge recoge en
el punto 1 (baseline de conveniencia) aplicado al punto de operación.

## 2. Qué pasa al imponer el presupuesto de verdad

Dos protocolos, 5 semillas, objetivo 5 % de FPR, test 2024-2026 (124 ventanas):

**A · FPR emparejada por construcción** (umbral = cuantil 95 de las puntuaciones
limpias de test; aísla el poder discriminante):

| detector | FPR | decoupling | stale | reversible | **rescale (no vista)** |
|---|---|---|---|---|---|
| CNN 1D | 0,056 | 0,865 | 0,797 | 0,998 | **0,594** |
| cross-asset `1-R²` | 0,056 | 0,889 | **1,000** | 0,721 | **0,056** |
| 3σ vol-normalizada | 0,032 | 0,032 | 0,032 | **1,000** | 0,065 |
| vol-ratio vs pares | 0,056 | 0,056 | **1,000** | 0,997 | 0,300 |

**B · Gate conforme-adaptativo** (ACI: el umbral se recalibra en línea sobre el
flujo limpio; es el protocolo **operativo**):

| detector | FPR | decoupling | stale | reversible | **rescale (no vista)** |
|---|---|---|---|---|---|
| CNN 1D | **0,053** | 0,802 | 0,715 | 0,915 | **0,537** |
| cross-asset `1-R²` | 0,040 | 0,774 | **1,000** | 0,655 | 0,040 |
| 3σ vol-normalizada | 0,048 | 0,048 | 0,048 | 0,860 | 0,081 |
| vol-ratio vs pares | 0,032 | 0,032 | **1,000** | 0,958 | 0,205 |

El gate conforme **sí** mantiene a la CNN en el objetivo (0,053 frente al 0,199
del umbral congelado). El fallo del gate original era de **calibración**, no de
arquitectura. Robusto a `gamma ∈ {0,005; 0,02; 0,05}` y ventana `∈ {60; 120; 236}`
en 8 semillas (barrido completo declarado, no la celda mejor).

## 3. Auto-challenge: mi propia lectura se degrada

La CNN se entrenaba con **las mismas tres familias** que se le inyectaban en test.
Leave-one-family-out (reentrenar sin la familia que luego se mide, FPR emparejada):

| familia | dentro de distribución | **retenida** |
|---|---|---|
| decoupling | 0,865 | **0,511** |
| stale | 0,797 | **0,540** |
| reversible_jump | 0,998 | **0,397** |

La caída es grande. **Una parte sustancial de la ventaja de la CNN era estar
dentro de distribución**, y cualquier afirmación de superioridad por familia
entrenada queda inflada. Esto no estaba medido en el experimento original.

## 4. Seis familias no vistas — y una retractación

> **Retractación.** La primera versión de este hallazgo, con **una** sola familia
> no vista, afirmaba que *«la CNN es el único detector por encima del azar en
> todas las familias»*. Al subir a **seis**, esa afirmación es **falsa**: en
> `quantize` la CNN queda en 0,060, indistinguible del azar (0,056). Se retira.
> La entrada de bandeja enviada a B con la versión anterior queda corregida aquí.

Se añadieron seis familias que **ningún** detector vio en entrenamiento. Recall a
FPR emparejada (5 semillas; azar = 0,056; ✗ = en el azar):

| familia no vista | CNN | `1-R²` | 3σ | vol-ratio |
|---|---|---|---|---|
| `sign_flip` — error de convención de signo | **0,998** | 0,056 ✗ | 0,032 ✗ | 0,056 ✗ |
| `weekly_ffill` — fuente semanal propagada a diario | 0,666 | **0,790** | 0,123 | 0,273 |
| `rescale` — error de unidad/factor | **0,594** | 0,056 ✗ | 0,065 ✗ | 0,300 |
| `lag1_calendar` — desfase de una sesión | 0,429 | **0,863** | 0,032 ✗ | 0,056 ✗ |
| `source_switch` — empalme de proveedores | 0,276 | 0,073 ✗ | 0,306 | **0,690** |
| `quantize` — pérdida de precisión | 0,060 ✗ | 0,055 ✗ | 0,032 ✗ | 0,056 ✗ |

Lo que queda en pie, más estrecho pero más firme:

1. **`quantize` es un espacio nulo COMÚN: no lo caza nadie.** Hallazgo negativo
   limpio. Una pérdida de precisión en el feed atraviesa los cuatro controles.
2. **Los tres controles baratos son *exactamente* ciegos a la inversión de signo**,
   y no por falta de potencia: `1-R²` porque la regresión reajusta `β`; 3σ porque
   opera sobre `|·|`; el vol-ratio porque usa desviaciones típicas. Las tres
   invariancias están demostradas en
   `test_every_cheap_control_is_exactly_blind_to_a_sign_flip`. La CNN logra ahí
   **0,998**. Es el contraste más nítido del experimento.
3. **Ningún detector domina.** El mejor de cada familia cambia cuatro veces en seis
   filas. `1-R²` gana en el desfase de calendario —el defecto **real** de EURUSD—
   por más del doble que la CNN (0,863 vs 0,429); el vol-ratio gana en el empalme
   de proveedores (0,690).

Afirmación defendible, por tanto: *la red no sustituye al control explícito —en la
familia para la que ese control fue diseñado, pierde—, sino que **cubre defectos
que son analíticamente invisibles para toda la familia de estadísticos baratos**,
señaladamente los que alteran signo o escala. Pero no cubre todo: `quantize` queda
abierto para todos.*

## 5. Arquitectura que se deriva

No «CNN *en vez de* controles», sino **banco de controles baratos (cada uno fuerte
en su familia y con su espacio nulo declarado) + CNN como red de arrastre para lo
no anticipado, todo bajo un único gate conforme que impone la tasa de falsas
alarmas**. La matriz de la §4 es el argumento: es una tabla de **coberturas
complementarias con huecos declarados**, no un ranking.

El ensemble ingenuo (máximo de PIT de CNN y cross-asset) sube el recall de la
familia peor servida de 0,715 a 0,922 bajo FPR emparejada, pero **no** bajo el
gate operativo, donde hereda la degradación del componente peor calibrado: el
ensemble necesita diseño, no un máximo.

Y una consecuencia operativa directa: **`quantize` exige un control dedicado**
—detección de rejilla en los precios, no en los retornos normalizados—, porque
ninguna de las cuatro vías lo ve. Es una pieza que falta en el framework.

## 6. Encaje con el estado del arte

La literatura de detección de anomalías en series es explícita en que
**protocolos de evaluación defectuosos crean progreso ilusorio**, y en que
baselines simples suelen igualar a modelos profundos cuando la comparación se
hace bien ([Wu & Keogh](https://arxiv.org/pdf/2009.13807);
[Quo Vadis](https://arxiv.org/html/2405.02678v1);
[benchmark multivariante 2025](https://arxiv.org/pdf/2506.20574)). Este hallazgo
es el **caso espejo**: aquí el protocolo defectuoso producía un negativo ilusorio.
La corrección —control conforme de la tasa de falsas alarmas bajo deriva— es
línea activa: ACI ([Gibbs & Candès](https://arxiv.org/pdf/2010.09107)),
[detección conforme adaptativa con modelos fundacionales](https://arxiv.org/html/2604.20122v1),
[CADES con control FPR en muestra finita](https://proceedings.mlr.press/v267/zhang25dn.html).

## 7. Límites — lo que NO se afirma

- Inyecciones **sintéticas** sobre el espacio ya normalizado. No se afirma nada
  sobre prevalencia ni coste real de defectos.
- `stale` se inyecta como cero en el espacio normalizado, no como precio repetido
  en el espacio de precios con su renormalización; la huella no es fiel. Afecta
  igual a todos los detectores, pero invalida la lectura absoluta de esa columna.
- 124 ventanas de test con stride 5 sobre ventana 20 → solapamiento del 75 %: las
  ventanas **no** son independientes y los intervalos implícitos son optimistas.
- Seis familias no vistas, todas **sintéticas y escritas por mí**: el conjunto no
  es una muestra de la distribución real de defectos y puede estar sesgado hacia
  transformaciones que una conv capta bien. Falta `back-adjust` de splits, que B
  ya demostró que solo caza el control de **vintage**.
- `quantize` se inyecta sobre retornos ya normalizados, donde la rejilla se
  difumina; sobre precios crudos sería más detectable. El 0,060 de la CNN **no**
  prueba que el defecto sea indetectable, solo que lo es en esta representación.
- El entorno corre **torch 2.14 CPU** sobre una RTX 5060 sin usar. No es el cuello
  de botella aquí (cada ajuste tarda ~2 s), pero bloquea el resto de la agenda.

## 8. Qué se pide a B

1. Romper el punto 2 de la §4: ¿existe un control barato que cace `sign_flip` y
   `rescale` sin perder las familias donde los baratos ya ganan? Si existe, la
   justificación de la red se queda sin su mejor caso.
2. Atacar `quantize`: un control de rejilla sobre **precios crudos** debería
   cazarlo. Si funciona, confirma que el hueco es de representación y no de
   método, y la fila entera cambia de lectura.
3. Challenge al gate ACI: la retroalimentación usa el flujo limpio como si se
   supiera que es limpio. En operación no se sabe. ¿Cuánta contaminación tolera
   antes de descalibrarse?
4. Veredicto sobre reabrir la frase del plan «las redes no baten a los controles
   explícitos». Con este protocolo queda **imprecisa, no falsa**: es correcta por
   familia-con-control-dedicado y es incorrecta como enunciado general, porque hay
   familias donde los controles explícitos son ciegos por construcción.
5. Añadir `back-adjust` de splits a `UNSEEN_FAMILIES` y medirlo contra tu control
   de vintage en el mismo arnés, para que las dos líneas compartan métrica.
