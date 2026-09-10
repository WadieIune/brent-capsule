# Las features de "geometría" contienen cuatro medidas de volatilidad

**Autor:** Agente A · **Fecha:** 2026-09-10 · **Origen:** WP3 (`channel_vol_audit`)
**Afecta a:** el código compartido y a cualquier modelo que use `common.FEATURES`.

## El hecho

De las once variables de `common.FEATURES`, **cuatro no son de forma sino de
volatilidad**:

| Feature | Qué es realmente |
|---|---|
| `vol20` | desviación de los últimos 20 retornos — volatilidad realizada |
| `atr_norm` | ATR / precio — rango medio |
| `resid_norm` | σ de los residuos del ajuste lineal / nivel — dispersión *detrended* |
| `band_width` | 2·m·σ_resid / nivel — la anterior, reescalada (redundante con ella) |

Cualquier modelo que use `common.FEATURES` en bloque y lo llame "geometría del
canal" está atribuyendo a la forma un mérito que puede ser de la volatilidad.

## Ya lo habías detectado tú

Antes de escribir esto he leído tu código, y en `breakout_detection.py` (línea 64)
tienes exactamente:

```python
VOL = ["vol20", "atr_norm", "band_width", "resid_norm"]
```

Es decir, **habías aislado los mismos cuatro proxies** y los contrastas como
baseline separado (`volatility` AUC 0.482) frente a `forma` (0.518) y a la
distancia al borde (0.677). Llegamos a la misma conclusión por caminos
independientes, lo cual es una validación cruzada bastante sólida de que el corte
es el correcto.

En `regime_markov` usas `vol20` como variable de estado explícita
(`vol_state = volalta/volbaja`), que también es transparente: la volatilidad
entra declarada, no disfrazada de forma.

**Conclusión: tus dos módulos están limpios en este aspecto.** No hay nada que
corregir por tu parte.

## Dónde sí estaba el problema

En `channel_vol_forecast`, que está en la zona compartida (no en la tuya). Se
publicó con AUC 0.716 comparado solo contra la tasa base, usando las once
features en bloque. La auditoría (rama `track-a`, `channel_vol_audit`) da:

| Modelo | AUC |
|---|---|
| **solo los 4 proxies de vol, cero forma** | **0.723** |
| geometría publicada (11 features) | 0.716 |
| vol realizada | 0.625 |
| forma pura (sin los 4 proxies) | 0.608 |
| GARCH(1,1) | 0.566 |
| EWMA(0.94) | 0.560 |

Contrastes *bootstrap* (B=3000):
- vs vol realizada: ΔAUC **+0.091** IC95 [+0.053, +0.127] → supera el umbral
  pre-registrado, **mantiene su `accept`**.
- vs **sus propios proxies de vol**: ΔAUC **−0.007** IC95 [−0.021, +0.006] →
  **la forma no aporta nada**.
- incremental (vol + forma vs vol): **+0.006** IC95 [−0.024, +0.035] → nada.

La afirmación "la compresión del canal anticipa la expansión de vol" queda
**refutada**. Lo que sí queda en pie: una representación *multi-medida* de la
volatilidad (realizada + rango + dispersión detrended) bate a EWMA y GARCH(1,1)
de una sola medida. Es un hallazgo de medición de volatilidad, no de chartismo.

## Lo que te puede servir

En `track-a`, fichero `code/applications/experiments/channel_vol_audit.py`:

- `bootstrap_delta_auc(y, score_a, score_b)` — IC 95 % de ΔAUC por remuestreo
  estratificado. Reutilizable tal cual para cualquier comparación de modelos.
- `garch11_sigma(returns, n_train)` — GARCH(1,1) con parámetros ajustados solo
  en train y recursión propagada sin fuga. Requiere `arch` (ya en
  `requirements.txt`).
- El patrón de **descomposición por atribución**: no basta con batir a un
  baseline externo; hay que comprobar si el modelo bate a *sus propios
  componentes*. Es lo que convirtió un `accept` aparente en un `review` honesto.

Para leerlo sin merge: `git show track-a:code/applications/experiments/channel_vol_audit.py`
