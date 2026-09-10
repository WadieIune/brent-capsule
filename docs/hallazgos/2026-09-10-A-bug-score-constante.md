# Bug a evitar: score constante → recall 1.0 espurio

**Autor:** Agente A · **Fecha:** 2026-09-10 · **Origen:** WP2-A
**Afecta a:** cualquier medición de recall/precisión con umbral por cuantil.

## El bug

Al medir recall a un "umbral operativo" es tentador escribir:

```python
thr = np.quantile(score, 0.99)
pred = score > thr if thr < score.max() else score >= score.max()   # <-- trampa
```

Si el detector devuelve un **score constante** (por ejemplo, un detector de
rachas frente a una serie que no tiene ninguna), entonces `thr == score.max()` y
la rama del `else` marca **todas** las observaciones como positivas. Resultado:
**recall = 1.0** para un detector que no ha detectado nada.

En mi caso lo produjo un baseline —el detector de rachas obtenía recall 1.00
sobre precios no positivos, que por construcción no puede ver—. Lo detecté
porque el número era absurdo, no porque el código fallara: no lanza excepción.

## La corrección

Semántica de **presupuesto fijo de alertas**: marcar el top-k del score, con
desempate aleatorio.

```python
n = len(score)
k = max(1, int(round((1.0 - q) * n)))
rng = np.random.default_rng(seed)
order = np.lexsort((rng.random(n), -np.asarray(score, dtype=float)))
pred = np.zeros(n, dtype=bool)
pred[order[:k]] = True
```

Así un detector sin capacidad de ordenación obtiene el recall que le corresponde
—el de marcar al azar— en lugar de un 1.0 artificial. Y además es la semántica
correcta desde el punto de vista operativo: un equipo de calidad de dato tiene un
presupuesto diario de alertas que puede revisar, no un umbral estadístico.

## Por qué lo comparto

La corrección iba **en contra de mi propio resultado** (mejoraba a los
baselines), y aun así había que hacerla. Si en tu track mides recall o precisión
a un umbral, merece la pena comprobar este caso límite: no da error, solo da un
número bonito y falso.
