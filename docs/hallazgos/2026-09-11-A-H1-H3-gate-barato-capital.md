# Hallazgo · gate barato de H1 y H3 — dónde SÍ se optimiza capital, y dónde no entra la CNN

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-09-11
- **Autorizado por el MASTER** a arrancar H1, H3 y consolidar supervivencia de canal.
- **Reproducción:** `scratchpad/h1_cheap.py` y `scratchpad/h1_attrib_h3.py`
  (serie `data/brent_fred_daily.csv`, α=0.99, ventana 250, corte out-of-time 2020-08-20).
- **Naturaleza:** gate **barato** (features tabulares de geometría, sin reentrenar la
  CNN). Si no supera este filtro, no se invierte en el reentreno. Si lo supera, va al
  backtest completo pre-registrado (DSR/PBO). **H1 no lo supera; H3 sí, pero por la vol.**

## Resumen en una línea

La palanca de capital que funciona y pasa el filtro es **condicionar el VaR a la
volatilidad** (FHS-EWMA): **−22.7 % de capital** frente al VaR estático, a igual
cobertura. **La geometría del canal / la CNN no añade nada sobre la volatilidad**
para esto: H1 muere en el gate.

## H1 — ¿la geometría anticipa el *clustering* de excepciones? **NO**

Objetivo: predecir la excepción de mañana (el término que mata Christoffersen y
dispara el multiplicador). Logística out-of-time, 1.526 días de test, 21 excepciones.

| Modelo | AUC-PR | AUC-ROC |
|---|---|---|
| Baseline (vol EWMA + VaR + excepción_hoy) | **0.0753** | 0.785 |
| + geometría completa | 0.0721 | 0.757 |
| + solo proxies de vol | 0.0737 | 0.786 |
| + solo geometría pura | 0.0697 | 0.762 |

- Incremento de la geometría: **ΔAUC-PR −0.0032** (empeora).
- **Nulo** (block-bootstrap de 20 días, 60 repeticiones, preserva el clustering de
  vol): Δ medio −0.002, **p95 +0.015**. El incremento real **no supera** el p95 del
  nulo → ni siquiera el signo es distinguible del ruido.

**Atribución del capital.** Un overlay que sube el VaR un 40 % en el decil de mayor
riesgo reduce las excepciones peor-250d de 8 a 5 (capital 0.298 → 0.279). Pero:

| Overlay guiado por | peor-250d | capital_worst | Kupiec |
|---|---|---|---|
| solo volatilidad | 5 | 0.27872 | ok |
| volatilidad + geometría | 5 | 0.27859 | ok |

Diferencia: **0.05 %**. La mejora de capital es **100 % volatilidad, 0 % geometría**.

**Veredicto H1:** no supera el gate. Consistente con las decisiones #5 (fragilidad
lift 0.00), #6 (geometría +0.006, IC incluye 0) y el resultado GPU (la CNN no captura
vol; la persistencia la bate). **Recomiendo NO gastar el reentreno de la CNN en H1.**
Puerta que queda abierta y que **decide B**: que la *textura 2D de la imagen* capture
algo que las features escalares no; la evidencia previa dice que es poco probable.

## H3 — ES condicional vs incondicional. **El capital baja, pero por la VOL**

| Especificación | avg VaR | peor-250d | multiplicador | capital_worst | cobertura |
|---|---|---|---|---|---|
| Estático (simulación histórica) | 0.0795 | 8 | 3.75 (ámbar) | **0.29792** | ok |
| Condicional a vol (FHS-EWMA) | 0.0677 | 5 | 3.40 (ámbar) | **0.23026** | ok |

**−22.7 % de capital** a cobertura Kupiec aceptable. Es un positivo real y presentable.
Pero el «régimen» que importa es el de **volatilidad**, que FHS-EWMA captura de forma
continua — **no** una etiqueta geométrica de la CNN. H3 en su versión CNN-regime
colapsa a condicionamiento por vol.

## Lectura para la presentación al Risk Director

1. **Positivo robusto y nuevo:** condicionar el VaR a la volatilidad recorta el capital
   regulatorio ~23 % frente al incumbente estático, a igual cobertura. Debe ir al
   **backtest completo** (DSR/PBO + independencia) como entregable confirmatorio.
   Es zona de B (dueño de volatilidad/régimen).
2. **Dónde entra la CNN en capital, con evidencia:** NO como predictor que bate a la
   vol. Solo donde ya está aceptado — el **control geométrico de calidad de dato**
   (decisión #7) que ve defectos que un control de cola no ve, y que alimenta el
   titular DQ → capital (subestimación del 13.4 %). Esa es la conexión CNN↔capital
   defendible ante un comité.
3. **Honestidad metodológica como activo:** H1 se probó y se cerró en el gate barato
   antes de gastar el reentreno. Es el mismo rigor que sostiene el resto del paper.

## Pendiente que decide B
- ¿Formaliza H3 (vol-conditional capital) como experimento registrado con backtest
  completo? Es su zona.
- ¿Da por cerrado H1, o quiere la prueba cara de textura de imagen pese a la evidencia?
