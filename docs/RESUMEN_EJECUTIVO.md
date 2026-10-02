# Resumen ejecutivo — sistema CNN + riesgo sobre Brent

> Pensado para acompañar a la figura `docs/figuras/sistema_productivo_cnn_gate_capital.svg`
> en un correo de resumen. Prosa lista para pegar; cifras verificadas y
> reproducibles en el repositorio `WadieIune/brent-capsule`.

## En dos líneas

Hemos construido —y, sobre todo, **validado con un backtest diseñado para
matarlo**— un sistema que usa reconocimiento de imágenes (CNN) sobre la geometría
del precio del Brent al servicio de un director de riesgos. El valor no está en
predecir el mercado (demostramos que no se puede), sino en **medir el capital
sobre el dato correcto y mantenerlo de forma eficiente**, con cada componente
certificado o descartado por el mismo filtro.

## El sistema en una imagen (adjunta)

Dos **puertas (gates) en serie** sobre el dato y dos **palancas de capital** que
se complementan, con el **backtest validando en paralelo** cada modelo:

1. **Gate 1 · Calidad de dato** (control geométrico): detecta defectos —precios
   estancados, no positivos— que un control estadístico de cola no ve. Consumir
   el dato «tal cual se recibe» **infradota el capital un 13,4 %**. Limpiarlo lo
   corrige al alza → **exactitud**: no quedarse corto de capital.
2. **Gate 2 · Detección de canal** (la CNN, AUC 0,97): es la **puerta de entrada
   al modelo**. Produce los episodios de canal que alimentan al modelo de
   supervivencia. En paralelo, el **VaR condicional a volatilidad** reduce el
   capital **−22,7 %** a igual cobertura → **eficiencia**: no pasarse.
3. **Backtest** (capa de validación, en paralelo): walk-forward purgado, DSR,
   PBO/CSCV, nulo de paseo aleatorio, Kupiec/Christoffersen, semáforo de Basilea.

## Lo que SÍ sostiene el backtest (presentable)

| Resultado | Métrica |
|---|---|
| La CNN detecta el canal con fiabilidad | AUC **0,97 / 0,956** fuera de muestra |
| La vida del canal es ordenable (XGB-AFT) | C-index **0,664 ± 0,007** |
| El dato sucio infradota el capital | **13,4 %** |
| El VaR condicional a volatilidad ahorra capital | **−22,7 %** a igual cobertura |

## Lo que el backtest DESCARTÓ (y por qué eso da credibilidad)

El mismo banco que aceptó lo anterior rechazó **diez** hipótesis que «parecían»
funcionar: que el canal diera ventaja direccional (DSR≈0), que acertar la ruptura
diera dinero (67,8 % de acierto pero Sharpe −0,48), que la geometría anticipara
la volatilidad (la persistencia gana) o el agrupamiento de pérdidas (sin señal
sobre el nulo). **Un banco que rechaza nueve de cada trece y aún deja pasar
cuatro es la razón por la que creemos esas cuatro.**

## El hallazgo que vale como caso propio

Durante el trabajo, un **defecto real de datos** (diez saltos imposibles en la
serie EUR/USD, de 2008) **atravesó todo el pipeline sin que nada lo detectara**,
hasta que lo cazamos al contrastar con una fuente independiente. Es la tesis del
capítulo de calidad de dato ocurriendo en nuestros propios datos: más convincente
que cualquier defecto inyectado a mano.

## Papel honesto de la IA

La CNN **no predice el capital** —lo probamos y no pasa el filtro—. Es un
**instrumento de medición**: detecta la estructura del mercado de forma
automática y consistente (puerta de entrada al modelo), sostiene el único modelo
de ranking que sobrevive (supervivencia del canal) y da legibilidad al marco.
El capital lo mueven el control de calidad de dato y el modelo de volatilidad.

## Estado y reproducibilidad

Todo está en el repositorio en formato **Code Ocean** (reproducible): datos con
inventario y verificación automática (`data/verify_panel.py`), código, resultados
publicados y documentación. El panel de mercado llega al **2026-09-10** (21
variables; EUR/USD servido por el BCE tras rechazar las fuentes defectuosas).
