# Arquitectura histórica del sistema de riesgo — no usar como fuente DQ

> **SUPERSEDED para el paper actual de Data Quality.** Esta arquitectura y su
> figura describen un trabajo previo de riesgo/capital; no son el framework DQ
> multicapa acordado ahora y no deben usarse como fuente de cifras de capital.
> La fuente actual es [`ARQUITECTURA_DQ_MULTICAPA.md`](ARQUITECTURA_DQ_MULTICAPA.md)
> junto con `PLAN_DQ_IA.md` y `PROPUESTA_DQ_REPRESENTACION_CANAL.md`. Los
> porcentajes de capital del documento histórico quedan retirados.

- **Autor:** Agente A (sugerente) · **Fecha:** 2026-09-11 · validada por el MASTER
- **Figura:** [`figuras/sistema_productivo_cnn_gate_capital.svg`](figuras/sistema_productivo_cnn_gate_capital.svg)
- **Regla:** esta es la versión acordada del sistema. Cualquier figura o párrafo
  de arquitectura en el paper, el HTML o el deck debe salir de aquí.

## La idea en una frase

Dos **gates en serie** sobre el dato, y dos **palancas de capital** que empujan en
direcciones opuestas y por eso se complementan: medir el capital sobre el dato
correcto (no infradotarse) y luego mantenerlo de forma eficiente (no sobredotarse).
En **paralelo** a los modelos corre el **backtest**, que valida cada uno (CNN,
XGB-AFT y VaR) y es lo que da credibilidad a lo que llega al Risk Director —ver
[`BACKTEST_METODOLOGIA.md`](BACKTEST_METODOLOGIA.md).

## El flujo, de arriba abajo

```
DATO CRUDO
   │
   ▼
GATE 1 · CALIDAD DE DATO   ── control geométrico (regresión móvil + ATR + rachas)
   │                          · ve stale / precio no positivo que un control de
   │                            cola NO ve (decisión #7)
   │                          · CAPITAL POR DATO: el dato sucio infradota 13,4 %
   │                            (decisión #13) → limpiarlo lo corrige al alza
   ▼
DATO LIMPIO  ───────────────┬───────────────────────────────┐
   │ (alimenta TODO)         │                               │
   ▼                         ▼                               │
GATE 2 · DETECCIÓN CANAL   VaR FHS-EWMA                      │
· CNN AUC 0,97 (dec. #1)   · condicional a volatilidad       │
· gate de entrada al modelo· CAPITAL POR MODELO: −22,7 %     │
   │                         a igual cobertura (eficiencia)  │
   ▼                                                         │
EPISODIOS DE CANAL                                           │
   │                                                         │
   ▼                                                         │
XGB-AFT SUPERVIVENCIA ── C-index 0,664 (dec. #3)             │
· ordena la vida del canal → horizonte de liquidez           │
   │                           (evidencia de apoyo FRTB)     │
   └─────────────────────────────┬───────────────────────────┘
                                  ▼
                           RISK DIRECTOR
          capital correcto (exactitud) + capital eficiente
          (eficiencia) + mapa de régimen + vida del canal
```

## El backtest, en paralelo, valida los modelos

La banda discontinua de la derecha de la figura **no es una etapa del flujo de
datos**: es la capa de validación que se aplica sobre los tres modelos (CNN,
XGB-AFT y VaR). Por eso se dibuja en paralelo, no en serie. El *gauntlet*
—walk-forward purgado, DSR, PBO/CSCV, nulo de paseo aleatorio,
Kupiec/Christoffersen, semáforo de Basilea— es lo que descartó las hipótesis de
fantasía y aceptó las cuatro que sobreviven. Sin esa capa, los números de los
modelos no significan nada ante un comité.

## Dónde está la CNN, y el matiz que NO puede faltar

La ordenación es: **detección de canal ANTES que supervivencia**. Sin canal
detectado no hay episodios, y sin episodios el XGB-AFT no tiene nada que ordenar.
La CNN ocupa esa casilla de **gate de entrada al modelo**.

**Matiz obligatorio ante un comité** (ya nos ha pasado por no decirlo):

- Hoy, en el código, el detector que alimenta a la supervivencia **y** al control
  de calidad de dato es el **detector geométrico de reglas** (`extract_episodes`
  → `label_price_window`; el módulo declara explícitamente que corre «sin
  arrastrar torch»).
- La CNN (EfficientNet sobre GASF/GADF) es el **detector aprendido**, validado a
  **AUC 0,97 out-of-time** contra esa misma definición de canal (decisión #1).
- En producción la CNN es el detector desplegable de ese gate: generaliza a más
  instrumentos sin reglas ajustadas a mano. Pero son **implementaciones
  intercambiables del mismo paso**.

Por tanto:

- ✅ Es correcto decir: «la CNN es el gate de detección de canal».
- ❌ Es falso decir: «la CNN limpia el dato» — eso es el Gate 1, geométrico, y la
  CNN **no interviene** en la ruta de calidad de dato (decisión #12, verificado
  por traza de importaciones: 0 módulos de deep learning).

**Extensión de investigación DQ (2026-10-07, no productiva):** el paper evalúa
el espacio de canal como una segunda representación para auditar si defectos
en las series alteran régimen, geometría, episodios o supervivencia estimada y
sesgan métricas de riesgo. Esto no cambia el diagrama ni la afirmación anterior:
la CNN de canal y XGBoost-AFT existentes siguen siendo detector de régimen y
supervivencia, respectivamente; no son detectores DQ hasta entrenarse y pasar
una evaluación específica a FPR controlada. El protocolo está en
`PROPUESTA_DQ_REPRESENTACION_CANAL.md`.

## Qué aporta cada caja, y qué NO

| Caja | Qué es | Aporta | NO es |
|---|---|---|---|
| Gate 1 · DQ | control geométrico | capital correcto (+13,4 %) | no es la CNN |
| Gate 2 · Detección | CNN AUC 0,97 / regla | régimen + episodios | no predice capital |
| XGB-AFT | supervivencia | ordena vida del canal (C-index 0,664) | no es un modelo de capital |
| VaR FHS-EWMA | modelo de volatilidad | capital eficiente (−22,7 %) | no es ML, no es la CNN |

## La frase honesta sobre la IA

La IA (CNN → episodios → XGBoost) **no está en la caja del capital**: está en la
cadena que da **criterio** al Risk Director (régimen y horizonte). El capital lo
mueven las dos cajas verdes. Esa es la razón defendible por la que la CNN está
dentro del sistema sin fingir que predice capital — probamos esa vía (H1/H3) y no
pasa el backtest (ver `hallazgos/2026-09-11-A-H1-H3-gate-barato-capital.md`).

### La IA como capa de soporte a la decisión (estado, con reservas del supervisor)

Se está probando si la IA puede **parametrizar el motor de cálculo** de capital.
Estado actual, con el **nivel de evidencia de cada vía marcado explícitamente**
(no todas están al mismo nivel, y una está en disputa):

| Vía | Lo observado | Nivel de evidencia |
|---|---|---|
| ES condicional a régimen (H3) | no mejora sobre la vol | ✅ **backtest completo** (cerrado) |
| Horizonte adaptativo (WP-AI1) | sin diferencia detectable | 🟠 **exploratorio**; el gate tiene defectos de alineación (look-ahead de 1 sesión) y nulo no temporal — *challenge* de B. **NO cierra la vía** |
| Estrés por régimen (WP-AI2) | la vol selecciona mejor el estrés | 🟡 comparación **descriptiva**, no backtest pre-registrado |

**Lo que SÍ se puede afirmar hoy:** ninguna de las vías probadas ha mostrado que
la IA mejore la fórmula de capital sobre las líneas base (vol / √h), pero **solo
H3 está cerrado con backtest completo**. WP-AI1 requiere un test confirmatorio
corregido (señal *as-of*, nulo temporal por bloques y binomio capital-cobertura
con la señal de supervivencia) antes de poder cerrar la vía de parametrización;
ver `auditorias/2026-10-03-B-challenge-wpai1-gate.md`.

**Conclusión de trabajo (sujeta a ese test):** el valor con evidencia de la IA es
como **capa de contexto para quien decide** ---mapa de régimen automático
(detección AUC 0,97), estimación de *cuánto durará* el régimen (supervivencia
C-index 0,664) y calidad de dato (control geométrico, que sí mueve capital por la
vía del dato)---, no como coeficientes de la fórmula. Es la lectura más probable,
pero **no se declara cerrada** hasta el test confirmatorio.

## Estado de validación de cada pieza

| Pieza | Métrica | Estado backtest |
|---|---|---|
| Detección de canal (CNN) | AUC 0,97 / 0,956 OOT | ✅ pasado (dec. #1) |
| Supervivencia (XGB-AFT) | C-index 0,664 ± 0,007 | ✅ pasado (dec. #3) |
| DQ → capital | infradotación 13,4 % | 🟡 confirmatorio (dec. #13) |
| VaR vol-condicional | −22,7 % capital (IC95 [−28,9; −1,3]) | ✅ **backtest completo pasado** (Kupiec + Christoffersen + DQ); además arregla la independencia |
| CNN → predicción de capital (H1/H3) | sin señal sobre el nulo | ❌ no pasa el gate |
