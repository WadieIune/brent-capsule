# Hallazgo · dos defectos encadenados en `EURUSD`: desfase en Yahoo y **corrupción en la serie del panel original**

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-09-11
- **Gravedad:** alta — es *look-ahead*, el error que este proyecto persigue
- **Estado:** resuelto · `EURUSD` sustituida por el BCE y extendida a 2026-09-10
- **Commit afectado:** `e04bcca` (`data: panel extendido a 2026-09-09 desde FRED`)

## Qué pasa

Las barras diarias de `EURUSD=X` en la API de Yahoo están fechadas **un día
antes de la sesión que contienen**. La firma es inconfundible:

- 598 barras están etiquetadas en **domingo** (el FX abre el domingo por la
  tarde en Nueva York);
- de los 630 días hábiles sin dato, **603 son viernes** — no lunes.

Es decir, el valor que la serie presenta como «viernes» no existe, y el valor
etiquetado como jueves es en realidad la sesión del viernes.

## Cómo se detectó

No por inspección del código, sino porque la cobertura no cuadraba: 12,2 % de
huecos en un cruce al contado que cotiza 24/5 es imposible. Al desglosar los
huecos por día de la semana apareció el sesgo hacia el viernes.

La confirmación es un test de desplazamiento contra la referencia auditada
`data/dataset_wide_with_target.csv` (2007-01-02 → 2026-03-06), error mediano
en el solape:

| Variable | −2 | −1 | **0** | +1 | +2 | Óptimo |
|---|---|---|---|---|---|---|
| GOLD | 0,869 % | 0,557 % | **0,000 %** | 0,557 % | 0,865 % | 0 ✓ |
| SILVER | 1,489 % | 0,987 % | **0,000 %** | 0,987 % | 1,484 % | 0 ✓ |
| COPPER | 1,273 % | 0,893 % | **0,000 %** | 0,892 % | 1,272 % | 0 ✓ |
| SP500 | 0,782 % | 0,524 % | **0,000 %** | 0,522 % | 0,781 % | 0 ✓ |
| DAX | 0,939 % | 0,629 % | **0,000 %** | 0,628 % | 0,938 % | 0 ✓ |
| EUROSTOXX50 | 0,933 % | 0,644 % | **0,000 %** | 0,642 % | 0,929 % | 0 ✓ |
| **EURUSD** | 0,490 % | 0,376 % | 0,071 % | **0,000 %** | 0,359 % | **+1 ⚠** |

Los otros seis instrumentos de Yahoo están perfectamente alineados. El problema
es exclusivo de la serie de FX.

## Lo que agrava el hallazgo

El panel **ya commiteado** en `e04bcca` contenía la versión de Yahoo con un
remapeo al siguiente día hábil, cuya firma numérica es idéntica a la que se
reproduce aquí (651 días con error > 0,5 %, máximo 15,41 % el 2008-12-09). Es
decir: **no era un error a punto de introducirse, era un error ya publicado en
`main`.** El resumen de sesión afirmaba que nada de Yahoo se había escrito ni
commiteado; era incorrecto, y se detectó al leer el blob de `HEAD` en vez de
fiarse de esa afirmación.

## Por qué no basta con remapear

El remapeo de cada fecha al siguiente día hábil lleva el error mediano a 0,0000 %
y la cobertura al 99,0 %, pero **el residuo no desaparece y no se concentra en
ningún periodo**:

| Año | 2007 | 2008 | 2012 | 2019 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| días con error > 0,5 % | 22 | 65 | 37 | 13 | 20 | 20 | 10 |
| error mediano | 0,000 % | 0,000 % | 0,000 % | 0,000 % | 0,000 % | 0,000 % | **0,206 %** |

Entre 20 y 50 días por año siguen mal alineados —semanas con festivo, donde la
convención de etiquetado de Yahoo cambia—, y **2026 es el peor tramo**, que es
justamente el que se quería añadir.

## Decisión provisional (superada por la ampliación de más abajo)

En un primer momento `EURUSD` se devolvió a la fuente original, que parecía
exacta, con corte en 2026-03-06. **Esa decisión duró horas**: al obtener una
fuente independiente resultó que la «fuente original» era precisamente la
corrupta. Ver la ampliación al final.

## Impacto en WP-V3

**Ninguno.** `EURUSD` queda extendida a 2026-09-10 desde el BCE. Además, la
variable «dólar» de la capa exógena era `DTWEXBGS` (índice de dólar amplio),
extendida a 2026-09-04, así que el paquete nunca estuvo bloqueado.

## Lección para el procedimiento

Las seis series que validaron a 0,0000 % lo hicieron con la misma rutina que la
que falló. **La validación por correlación de niveles no detecta un desfase de
un día**: en el primer contraste `EURUSD` dio correlación 0,9989 y error mediano
0,07 %, números que parecen buenos. Lo que lo destapó fue mirar la cobertura por
día de la semana y hacer el barrido de desplazamientos.

**Propuesta a B (decide él):** que el barrido de desplazamiento en −1/0/+1 sea
requisito obligatorio para toda serie que entre al panel, no comprobación
opcional. Está implementado en `data/verify_panel.py` §5.


---

# Ampliación (mismo día): la «referencia auditada» estaba corrupta

Al conseguir por fin una fuente independiente —el BCE, tras confirmarse que FRED
estaba inaccesible— el diagnóstico se invirtió.

El tipo de referencia del BCE (`EXR.D.USD.EUR.SP00.A`) alinea en desplazamiento
0, como debe, pero con un error mediano del 0,20 % y un máximo del 13,84 %
frente a la serie del panel. Un cruce como el euro/dólar **no se mueve un 13,8 %
en un día**. El contraste de saltos diarios resuelve de qué lado está el
defecto:

| Serie | Saltos diarios > 5 % |
|---|---|
| BCE | **0** |
| Serie del panel original | **10** |

Y el patrón es inequívoco: los errores caen el 8-ene, 8-feb, 8-sep, 8-oct y
8-dic de 2008 —todos en día 8—, con valores repetidos entre fechas distintas.
El peor: 1,4918 → 1,2926 el 2008-12-08, cuando el euro/dólar cotizaba en torno
a 1,29 toda esa semana.

**Ninguna otra variable de `dataset_wide_with_target.csv` tiene el defecto**
(GOLD, SP500, DAX y EUROSTOXX50 dan cero saltos imposibles; los de WTI en abril
de 2020 son el precio negativo real).

## Consecuencias, y una es incómoda

1. `EURUSD` se sustituye **en toda la historia** por la serie del BCE, no solo
   en la cola. Cambian 5.097 valores. `BRENT_EURUSD_RATIO` se recalcula.
2. **Mi validación anterior era circular.** Validé las 7 series de Yahoo contra
   `dataset_wide_with_target.csv` llamándola «referencia auditada», cuando esa
   referencia procede de la misma familia de fuentes. Que las 6 restantes
   reprodujeran la referencia con error 0,0000 % demuestra **continuidad con lo
   ya publicado**, no corrección frente a la realidad. Hay que decirlo así en el
   paper.
3. El defecto **atravesó todo el pipeline sin que nada lo viera**. Eso es
   exactamente la tesis del capítulo de calidad de dato del paper, ocurrida en
   nuestros propios datos.

## Lo que se añade al procedimiento

`data/verify_panel.py` §4bis: control de saltos diarios imposibles, con umbral
por instrumento y lista explícita de excepciones justificadas. Los umbrales
**no** se relajan hasta que el test pase; cada excepción lleva motivo, y el
criterio para admitirla es que el movimiento **persista** (un print defectuoso
revierte al día siguiente; un evento real, no).

**Sugerencia a B (decide él):** que el control de saltos y el barrido de
desplazamiento sean requisito de admisión para cualquier serie del panel, y que
el paper recoja este episodio como caso propio en el capítulo de calidad de
dato. Es más honesto y más convincente que un defecto inyectado sintéticamente.
