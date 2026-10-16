# Respuesta al challenge B · calibración por clase y discriminación DQ

- **Fecha:** 2026-10-16
- **Challenge:** `docs/auditorias/2026-10-16-B-challenge-dq-calibracion-por-clase.md`
- **Veredicto que acepto:** 🟠 **degradado**. Los seis puntos, sin reservas. El
  tercero además **corrige una cifra que yo ya había publicado**.

## El punto 3 invalida mi atribución, y corregirlo da el número que faltaba

Tienes razón: contar 236 puntuaciones consecutivas como independientes
**sobreestima la resolución por un factor de 4**. Las ventanas son de 20 sesiones
con paso 5, así que solo una de cada cuatro está en fase no solapada. La muestra
efectiva es **59**, no 236.

Mi test comparaba el share con `1/ventana` y daba por resuelto algo que no lo
está: **verificaba aritmética de ventanas, no tamaño muestral efectivo**, como
escribes literalmente. Corregido en `effective_sample_size`, con dos pruebas que
lo fijan y una que declara el límite en vez de fingir que no existe.

Y al corregirlo aparece la cifra que explica todo lo demás:

```
muestra efectiva                         59   (no 236)
α mínimo representable con 7 controles   7/59 = 0,119
α configurado                            0,050  →  NO representable
```

**Por debajo de 0,119 la petición no es representable**: el umbral por control
cae en el máximo empírico y el gate entrega su suelo, se pida lo que se pida. Eso
explica exactamente la observación que publiqué sin entender del todo —pedir
0,005 o 0,010 da el mismo 0,083— y convierte el suelo en una consecuencia
derivable, no en una curiosidad empírica.

**Lo que queda retirado:** mi afirmación de que «la resolución está corregida y
el exceso residual es deriva de 2,6×». Con la muestra efectiva, el término de
resolución **sigue activo** y no puedo atribuir el exceso a deriva. La
descomposición hay que rehacerla, y mientras tanto no debe citarse.

**Lo que sobrevive:** el **suelo medido de 0,083 ± 0,004** y la curva de
operación. Son observaciones, no atribuciones causales, y son lo que sostiene la
decisión del MASTER de declarar el presupuesto real en vez de prometer un 5 %.
De hecho el challenge la refuerza: ahora hay una razón estructural para no
prometer por debajo de ~0,12.

## Los otros cinco, aceptados

1. **FPR emparejada es oráculo.** De acuerdo, y así está rotulado. El 0,613 del
   combinador es capacidad discriminante en protocolo sintético, no resultado
   operativo. No lo presentaré de otro modo.
2. **LOFO no equivale a test por activo/fuente/tiempo.** Cierto: reserva
   familias, pero el activo base y el bloque de calibración son los mismos. La
   generalización a series externas sigue abierta.
4. **El gate mejora modestamente e incumple el objetivo.** De acuerdo con
   reportar 0,129→0,116 y 0,629→0,646 **descriptivamente**: 124 ventanas
   solapadas no son 124 ensayos y tres semillas no reparan la dependencia.
5. **«Determinista no consume FPR» es condicional al contrato.** Es la
   observación que menos había pensado y la acepto entera. Vintage y retícula
   tienen score constante **en este panel limpio**; un tick mal declarado, un
   cambio legítimo de convención o una revisión de snapshot sí producirían
   alertas. `assert_degenerate` verifica la degeneración contra los datos —y
   rompe si no se cumple— pero eso **no garantiza FPR cero en producción**. La
   semántica evita calibrar una constante por cuantil; no promete nada más.
6. **La contaminación es insuficiente.** Contaminé con una sola familia y modo
   (`stale|restated`). No basta para afirmar robustez ante mezcla real.

## Enunciado que adopto

> Hay señal discriminante complementaria entre representaciones; la
> transferencia de calibración es el cuello de botella observado **en este
> panel**. No se afirma que la IA supere el estado del arte.

## Lo pendiente, en el orden que propongo

1. **Rehacer la atribución del exceso** con inferencia por bloques y
   sensibilidad a las cuatro fases del stride. Es lo que corrige la cifra
   retirada.
2. **Contaminación amplia**: varias familias y direcciones, inyecciones pareadas
   y purga, sin usar el bloque evaluado para fijar su propio umbral.
3. **Medir la FPR de los deterministas con contratos perturbados** —tick mal
   declarado, cambio de convención, revisión de snapshot—, que es tu punto 5 y
   hoy no está medido.
4. **Comparar esquemas de calibración** sin dar por bueno que repartir α entre
   siete sea óptimo: marginal por score, calibración directa de la unión, y
   subconjunto elegido solo en validación.
5. **Test externo por activo, fuente y periodo** con adjudicación de incidencias
   y carga de revisión real. Es el gate que de verdad decide.

## Corrección pendiente en material ya publicado

El resumen ejecutivo y el Excel subidos a `main` llevan la descomposición
«resolución corregida + deriva 2,6×», que este challenge invalida. Hay que
sustituirla por el límite de representabilidad —α mínimo 0,119 con la muestra
efectiva— manteniendo el suelo y la curva, que no se tocan. Lo haré en cuanto
confirmes que el enunciado de arriba te vale.
