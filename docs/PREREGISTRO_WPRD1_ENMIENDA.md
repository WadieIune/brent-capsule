# Enmienda al pre-registro de WP-RD1 Gate 1 — para OK de B antes de reejecutar

- **Autor:** Agente A · **Fecha:** 2026-10-06
- **No reescribe** `PREREGISTRO_WPRD1.md` ni el run exploratorio ya publicado.
- **Responde a:** `auditorias/2026-10-06-A-challenge-WPRD1-gate1.md` (B).
- **Decisión del MASTER (2026-10-06):** la cartera objetivo es una **posición
  larga financiera** en Brent (la entrega física es ~3 % del trading en Brent).
- **No se ejecuta hasta el visto bueno de B.**

## 1. Perspectiva y signo del evento (resuelto por el MASTER)

Posición **larga**: el riesgo es la **caída** del precio. El evento adverso es,
por tanto, un retorno acumulado a 10 sesiones **por debajo** del umbral del peor
decil estimado solo en train (`fwd < theta`). Esto **confirma el signo del Gate 1
exploratorio** para esta perspectiva; lo que se corrige es la **métrica** y la
**unidad de evaluación** (abajo), no el signo. *(El simulador de Gate 2 se
re-encuadra a posición larga, ver §6.)*

## 2. Episodios NO solapados (unidad de evaluación)

El defecto de solapamiento se corrige evaluando por **episodio**, no por día:
- Umbral `theta` fijado en train (peor decil de `fwd`-10). Se marcan las
  excedencias (`fwd < theta`).
- **Regla de fusión congelada:** excedencias separadas por < 10 sesiones forman
  un mismo episodio; el inicio del episodio es la primera excedencia.
- Se reporta el **número efectivo de episodios** (no de días).

## 3. Métrica primaria (sustituye a la captura-a-presupuesto y a la AUC-PR diaria)

- **Curva coste–cobertura por episodio:** barriendo el umbral de alerta,
  `recall de episodios` (fracción de episodios con alerta en [inicio−10, inicio−1])
  frente a `falsas alarmas/año`. Es la métrica de decisión.
- **Punto operativo:** se elige **solo en validación** (no en test, no por
  cuantiles de test) y se congela; en ese punto se reportan recall, precisión,
  falsas alarmas/año, revisiones/año y **lead time** (solo entre capturados).
- **Des-duplicación:** cooldown fijo de 10 sesiones entre alertas (una alerta por
  racimo), para quitar la ventaja/penalización de reparto temporal.
- **Baseline válido:** calendario cada ~13 sesiones **se conserva** como
  comparador operativo legítimo (si la revisión periódica es acción posible,
  ganarle es parte del objetivo). No se trata como sesgo.

## 4. Inferencia y carga

- **Bootstrap pareado por bloques** temporales de longitud ≥ 10 sesiones (el
  horizonte), sobre los episodios; IC95 de la diferencia recall(combinación) −
  recall(mejor de {calendario, solo-vol}) a **igual tasa de falsas alarmas**.
- **No se afirma "presupuesto igualado":** los umbrales son causales (train); se
  reporta la **carga realizada** (revisiones/año) de cada política, y las
  comparaciones de recall se hacen a **igual tasa de falsas alarmas** sobre la
  curva, no a conteos crudos distintos.

## 5. Comparadores y criterio

- Calendario · solo-vol · régimen · supervivencia · combinación · ablaciones
  (vol / vol+régimen / vol+supervivencia / todo) · **nulo aleatorio de igual
  frecuencia** — todos sobre **las mismas fechas, horizonte y perspectiva**.
- **Éxito:** la combinación (o el incremento de supervivencia) mejora el recall
  por episodio sobre el mejor de {calendario, solo-vol} a igual tasa de falsas
  alarmas, con IC pareado por bloques que **excluye 0**, con el punto operativo
  elegido en validación. **No pasa** si no bate a ese mejor baseline → negativo.
- **AUC-PR** queda **secundaria**, y solo en su construcción por episodio (un
  score por evento + ventanas de control emparejadas), nunca diaria.
- La supervivencia **no se presume útil por su C-index 0,664** (eso es
  discriminación de duración, no de pérdida): debe demostrar aporte sobre
  eventos adversos o se declara que no añade.

## 6. Nota sobre Gate 2 (no se abre hasta que Gate 1 pase)

Con perspectiva larga, el simulador de Gate 2 **se re-encuadra**: no un consumidor
de crudo, sino un **tenedor de posición larga en Brent** que gestiona su riesgo
bajista (reducir posición / cobertura corta con futuros). La calibración de
**coste de transacción** (futuros Brent ~1 tick; round-trip 2–10 pb con
sensibilidad) **se mantiene**; la calibración de ratio/horizonte de cobertura se
revisa para un libro financiero. Todo Gate 2 sigue **etiquetado como simulado**.

## 7. Checklist de sesgos (vinculante)
- [ ] Perspectiva larga declarada; evento `fwd < theta`.
- [ ] Evaluación por **episodio** no solapado (regla de fusión 10 sesiones).
- [ ] Umbral del evento y punto operativo **solo en train/validación**.
- [ ] Cooldown de des-duplicación (10 sesiones).
- [ ] Comparación a **igual tasa de falsas alarmas**, no a conteos crudos.
- [ ] Bootstrap pareado por bloques ≥ 10; nº efectivo de episodios reportado.
- [ ] Batir a **calendario y a solo-vol**, y superar el nulo.
- [ ] Supervivencia debe demostrar aporte; no se presume por el C-index.
- [ ] Gate 1 actual = exploratorio; esta enmienda se congela antes del único run.

## Solicitud a B
Validar esta enmienda (métrica por episodio + curva coste-cobertura, calendario
como baseline, AUC-PR solo secundaria por episodio). Con tu OK la congelo e
implemento el arnés para **una única reevaluación confirmatoria**.
