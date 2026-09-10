# La CNN no interviene en el control de calidad de dato

**Autor:** Agente A · **Fecha:** 2026-09-10
**Origen:** pregunta directa del usuario: *«¿qué gano usando la CNN frente a una
librería estándar de calidad de dato con estadísticos normales: repetidos,
repetidos consecutivos, outliers a 3 desviaciones, máximo, mínimo, número de
registros?»*
**Afecta a:** la afirmación central del paper. Obliga a reescribirla.

## Respuesta corta

**Para calidad de dato, la CNN no aporta nada, porque no interviene.**

Verificado ejecutando la traza de importaciones: la ruta completa de calidad de
dato —`common.py`, `dq_price_control`, `dq_impact`, `dq_daily_monitor`,
`dq_synthetic_validation`, `dq_capital_impact`— carga **cero** módulos de
`torch`, `torchvision` o `timm`.

Lo que el control llama «canal» es:

```python
slope, intercept = np.polyfit(x, y, 1)      # regresión lineal de 32 puntos
resid_std       = np.std(y - (slope*x + intercept))
banda           = centro ± k · resid_std
```

Una **regresión lineal móvil con bandas de residuo**, más un ATR (media móvil de
|Δcierre|) y una regla de rachas. La red convolucional se usa **solo** en la 1ª
pata (`channel_detector.py`), para clasificar la figura chartista, y esa pata ya
está cerrada como sin valor económico (DSR ≈ 0).

Cualquier texto que sugiera que «la CNN detecta defectos de calidad de dato»
sería **falso**. Hay que decir «control geométrico» y no «CNN».

## Respuesta larga: ¿y frente a una librería estándar?

Comparación sobre la inyección sintética con verdad conocida (5 familias × 3
tasas × 10 semillas). La «librería estándar» implementa exactamente lo descrito:
repetidos, rachas de repetidos, 3 desviaciones sobre retornos y no positivos.

| Familia de defecto | Control geométrico | Librería estándar | Diferencia |
|---|---|---|---|
| `stale_fill` (relleno/congelado) | 0.945 | **0.879** | +0.066 |
| `salto_reversible` (fat finger) | **0.634** | 0.022 | **+0.612** |
| `outlier_de_cola` (salto persistente) | 0.079 | 0.022 | +0.057 |
| `precio_no_positivo` | 1.000 | **0.972** | +0.028 |
| `desfase_calendario` | 0.018 | **0.321** | **−0.303** |
| **Media** | 0.535 | 0.443 | +0.092 |

*(AUC-PR medio. Un aviso de método: la primera versión de esta comparación estaba
**sesgada a mi favor** porque `_rank01` repartía rangos altos entre los ceros de
una señal dispersa. Corregido con normalización por máximo en ambos lados. Es el
mismo defecto que detecté en WP2-A.)*

### Lectura honesta, familia por familia

- **Repetidos y precios no positivos: empate.** 0.879 frente a 0.945 y 0.972
  frente a 1.000. **El usuario tiene razón**: para esto basta un `diff()==0` y un
  `close<=0`. No hace falta geometría, y menos aún una CNN.
- **Desfase de calendario: gana la librería estándar** (0.321 frente a 0.018).
- **Salto persistente: pierden los dos** (0.079 y 0.022). Ninguno sirve.
- **Salto reversible: única ventaja real** (0.634 frente a 0.022). El motivo es
  concreto: un umbral de 3σ global sufre **enmascaramiento** —los propios saltos
  inflan la desviación típica y dejan de superar el umbral—, y además marca dos
  días (el salto y la reversión) por un solo defecto. La regla geométrica usa la
  **firma de reversión** («salta y vuelve»), que es información de forma.

### Matiz que me obliga a rebajar aún más la ventaja

El 3σ global es la versión **ingenua**. Una librería competente usa estadística
robusta. Frente a esos baselines (medidos en WP2-A):

| Familia | Geométrico | Mejor baseline robusto |
|---|---|---|
| `stale_fill` | 0.945 | 0.823 (detector de rachas) |
| `salto_reversible` | 0.518 | 0.367 (Hampel/MAD) |

La ventaja se estrecha mucho. Contra Hampel y un detector de rachas, el control
geométrico gana, pero por márgenes modestos.

## Lo que sí queda en pie

1. **La ceguera estructural es real y no es cuestión de calibración.** Los
   detectores de **cola** (Hampel, Tukey, isolation forest) tienen recall
   **0.00** en *stale* y en precio no positivo. Un retorno exactamente cero nunca
   es atípico de cola. Para verlo hace falta una regla específica —de rachas o
   geométrica—, y muchos controles desplegados en producción son de cola.
2. **La consecuencia en capital está cuantificada y no depende de qué detector se
   use:** consumir el panel sin depurar **subestima el capital un 13.4 %** e
   **infla ×1.46** la observabilidad declarada para el RFET. Ese número es el
   resultado práctico, y es válido tanto si los defectos se detectan con el
   control geométrico como con un `groupby` de tres líneas.
3. **Atribución y severidad.** El control geométrico dice *por qué* (fuera de
   banda / salto reversible / racha) y *cuánto* (en unidades de σ del canal
   proyectado), no solo *sí/no*. Es útil operativamente, pero es una ventaja de
   **usabilidad**, no de detección.

## Cómo debe reescribirse la afirmación del paper

> ❌ **No decir:** «una CNN detecta defectos de calidad de dato que los controles
> convencionales no ven».
>
> ✅ **Decir:** «los controles de calidad basados en la **cola** de la
> distribución de retornos son **ciegos por construcción** al precio congelado y
> al relleno de calendario, porque un retorno nulo nunca es un valor atípico. Un
> control de **rachas** o uno **geométrico** sí los detecta —con ventaja modesta
> del segundo, salvo en el salto reversible, donde es sustancial—. Y detectarlos
> importa: el dato sin depurar subestima el capital regulatorio un **13.4 %** e
> infla ×1.46 la observabilidad declarada para el RFET».

La contribución del paper por este lado **no es un detector nuevo**: es
**cuantificar en capital y en observabilidad regulatoria** la consecuencia de un
punto ciego conocido. Eso sigue siendo publicable y útil para la industria —pero
hay que enunciarlo así.

## Consecuencia para el conjunto del trabajo

La CNN queda como objeto de estudio de la 1ª pata —donde se demostró que detecta
la geometría con AUC 0.97 y que **eso no es monetizable**— y no como herramienta
de la aplicación práctica. El paper debe ser explícito en esa separación, porque
un revisor que abra el código lo verá en cinco minutos.
