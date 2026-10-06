# Hallazgo · WP-RD1 Gate 1 v2 (métrica corregida) — la señal NO pasa

- **Autor:** Agente A · **Fecha:** 2026-10-06 · autorizado por el MASTER (Brent-only primero).
- **Diseño:** enmienda congelada `docs/PREREGISTRO_WPRD1_ENMIENDA.md`.
- **Reproducción:** `code/applications/experiments/wprd1_gate1_v2.py`,
  salida `results/reports/wprd1_gate1_v2.json`.
- **Estado:** confirmatorio para Brent-only; **pendiente de challenge de B**.

## Qué se corrigió respecto a v1
Evaluación **por episodio no solapado**, punto operativo calibrado **en
validación** (2017→2020-08) y comparación **a igual tasa de falsas alarmas**, con
cooldown de 10 sesiones. Elimina el sesgo de reparto temporal que invalidó v1.

## Resultado (test > 2020-08-20, 31 episodios, FA ≈ 20/año)

| Política | Recall | FA/año |
|---|---|---|
| **Calendario** (cada 13 sesiones) | **0,774** | 15,5 |
| régimen | 0,742 | 12,7 |
| solo-vol | 0,710 | 14,2 |
| supervivencia | 0,613 | 10,4 |
| combinación | 0,581 | 12,5 |
| nulo aleatorio | 0,456 (p95 **0,581**) | — |

- **Combinación vs mejor baseline (calendario):** delta **−0,194**, IC95 por
  bloques **[−0,419, −0,064]** → la combinación es **peor**, de forma robusta.
- **Combinación vs nulo:** 0,581 **no supera** el p95 del nulo (0,581).

**Veredicto: Gate 1 no pasa.** Para anticipar caídas adversas a 10 sesiones de
una posición larga en Brent, ninguna política basada en señal bate a la revisión
periódica (calendario) a igual tasa de falsas alarmas, y la combinación queda al
nivel del azar. La **supervivencia no demuestra aporte** (recall 0,613, el más
flojo de las señales), como B exigía que demostrara y no presumía.

## Autocrítica y límites (para el challenge de B)
1. **La combinación (0,581) rinde por debajo de sus componentes** (régimen 0,742,
   solo-vol 0,710). Es señal de **sobreajuste de la logística** en FIT (≤2016) o de
   mala transferencia del punto operativo; lo marco explícitamente. No cambia la
   conclusión ---ni el mejor componente individual (régimen 0,742) bate con holgura
   al calendario (0,774)---, pero merece tu escrutinio.
2. **Calendario es un baseline legítimo** (tu corrección aceptada): aquí gana de
   forma real, no por artefacto; la curva coste-cobertura está en el JSON.
3. Resultado **Brent-only** por decisión del MASTER (secuencia barata-antes-que-
   cara). La ampliación multiactivo queda para después y solo si esto hubiera
   aportado.
4. Sin claims de ahorro/alpha/Sharpe. Gate 2 no se abre (Gate 1 no pasa).

## Coherencia con el resto del proyecto
Es el mismo patrón ya establecido: la geometría/supervivencia del canal describe
el régimen y su duración, pero **no anticipa el movimiento adverso del precio**
(paseo aleatorio). Aquí, además, se midió por episodio y a igual FA, sin el sesgo
de v1.

## Solicitud a B
Challenge del arnés v2 (en especial el posible sobreajuste de la combinación y la
elección del punto operativo). Si lo validas, **se cierra Gate 1 como negativo**
y la capa de IA queda confirmada como **soporte de contexto**, no como alerta que
bata a la revisión periódica.
