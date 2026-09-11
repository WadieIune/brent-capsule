# Hallazgo · `EURUSD=X` de Yahoo viene desfasado un día, y el panel commiteado ya lo llevaba

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-09-11
- **Gravedad:** alta — es *look-ahead*, el error que este proyecto persigue
- **Estado:** corregido en el panel; `EURUSD` queda sin extender
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

## Decisión tomada

`EURUSD` vuelve a la fuente original (exacta, 0 días de desviación) y **termina
el 2026-03-06**. El resto del panel queda extendido a 2026-09-10.

`BRENT_EURUSD_RATIO`, que deriva de ella, hereda el mismo corte.

## Impacto en WP-V3

**Acotado.** La variable «dólar» de la capa exógena es `DTWEXBGS` (índice de
dólar amplio), extendida a 2026-09-04. `EURUSD` no era variable de la lista de
WP-V3. El hueco no bloquea el paquete.

## Lección para el procedimiento

Las seis series que validaron a 0,0000 % lo hicieron con la misma rutina que la
que falló. **La validación por correlación de niveles no detecta un desfase de
un día**: en el primer contraste `EURUSD` dio correlación 0,9989 y error mediano
0,07 %, números que parecen buenos. Lo que lo destapó fue mirar la cobertura por
día de la semana y hacer el barrido de desplazamientos.

**Propuesta a B (decide él):** que el barrido de desplazamiento en −1/0/+1 sea
requisito obligatorio para toda serie que entre al panel, no comprobación
opcional. Está implementado en `data/verify_panel.py` §5.
