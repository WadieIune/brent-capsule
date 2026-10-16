# Respuesta al challenge · distribución de rendimientos y distorsión por gate

- **Fecha:** 2026-10-07
- **Challenge:** `docs/auditorias/2026-10-07-A-challenge-dq-return-distribution.md`
- **Veredicto que acepto:** 🟠 **degradado**. El panel D y todos los porcentajes
  de «distorsión corregida» / «ganancia de precisión» **quedan fuera del paper**.

## Acepto, y el motivo decisivo no lo había visto

El challenge señala seis problemas. Cinco los tenía declarados como límites, lo
que **no** los convierte en aceptables: declarar un sesgo no lo elimina. Pero el
tercero es de otra naturaleza y es el que invalida el número, no solo lo matiza:

> *Distorsión y recall no están calculados sobre las mismas ventanas: Wasserstein
> promedia 40 episodios elegidos de un test, mientras recall viene del stack
> completo y sus escenarios. Se multiplican agregados no pareados.*

Es correcto y es un error mío de construcción, no de redacción. En
`dq_return_distribution.run()` la distorsión se promedia sobre 40 episodios con
su propio `rng`, y el recall se lee del `summary.json` del stack, que usó otras
inyecciones sobre las 124 ventanas. Multiplicar `media(1−recall) × media(W)` da
por supuesta una correspondencia entre dos muestras que **no están pareadas**.
Ningún disclaimer arregla eso.

También acepto sin reservas:

- **«Precisión» es la palabra equivocada.** No calculo precision/PPV ni falsos
  descubrimientos a prevalencia defendible. Era terminología incorrecta.
- **Es una proyección bajo corrección perfecta**, no una mejora medida. El
  pipeline no corrige la serie ni vuelve a medir la distribución corregida.
  Detección y corrección son problemas distintos y los traté como uno.
- **La garantía conformal no es «sea cual sea la forma»** sin supuestos.
  Sobreafirmé: depende de dependencia entre ventanas, drift y tamaño de
  calibración, y con 236 ventanas solapadas ninguna de las tres es inocua.
- FPR no emparejadas entre gates, estandarización con look-ahead, prevalencia
  uniforme y base absoluta pequeña: ya estaban declarados y siguen en pie.

## Qué se ha cambiado

- **Panel D retirado de la figura.** `docs/figuras/dq_distribucion_rendimientos.png`
  lo sustituye por un diagnóstico descriptivo sin proyección: de cuántos días
  depende la cola (curtosis 76,4 → 25,9 → 12,9 → 4,9 al excluir 0/1/3/10 días
  extremos, todos ellos movimientos reales de 2020 y 2009).
- **La comparación de gates sigue calculándose pero se publica marcada** bajo
  `proyeccion_no_validada` en el JSON, con el motivo completo y la lista de lo
  que haría falta para reabrirla. Se conserva para auditoría del proceso, no
  como resultado.
- La salida de consola y el docstring del módulo lo dicen explícitamente.
- El hallazgo `2026-10-07-A-dq-distorsion-distribucion-por-gate.md` lleva el
  aviso en cabecera.

## Qué sigue en pie

El **diagnóstico descriptivo** (§1-2 del hallazgo, paneles A-D):

- Suponer normalidad con ±3σ **infraestima** la frecuencia de extremos: en Brent
  |z| > 3 ocurre el 1,11 % frente al 0,27 % teórico (4,1×), y a 5σ 5.605×. Lo que
  la normal sobreestima es la masa de los hombros (1σ y 2σ: 0,5× y 0,8×).
- De ahí **no** se sigue ninguna dirección de sesgo en capital, como el challenge
  dice y como ya recogía el documento de nueve series.
- Un 3σ que dispara 4× lo que su supuesto promete **no separa una cola real de
  mercado de un defecto**. Esto motiva el framework por representaciones; no lo
  demuestra. La demostración tiene que venir de detección con etiquetas, y esa es
  la línea de C10/C11, no ésta.

Todo con la reserva de **look-ahead** por estandarización de muestra completa,
igual que el documento de nueve series, que sigue siendo la entrega preferida
para la comparación multi-activo.

## Condiciones para reabrir la parte degradada

Las del challenge, sin rebaja:

1. Test temporal **no solapado**.
2. Prevalencia y severidad **prefijadas antes** del test.
3. **Las mismas inyecciones** en el lado de la distorsión y en el del recall —
   esto es lo que hoy falla.
4. FPR **emparejada** entre gates, con incertidumbre.
5. Una **política de corrección explícita** con su error residual, en vez de
   suponer corrección perfecta.
6. Reportar Wasserstein, cuantiles y curtosis en **unidades absolutas** además de
   la métrica relativa, y precisión como **PPV** sobre prevalencia justificada.
