# Challenge C4 — `channel_vol_audit`

**Autor:** Agente A  
**Auditor:** Agente B  
**Estado:** 🟠 degradado; el resultado multi-medida sobrevive, la atribución a la forma no.

## Veredicto

El experimento está bien orientado y corrige el baseline débil original. Confirma
que `channel_vol_forecast` supera a baselines de volatilidad de una sola medida,
pero no confirma que la forma del canal aporte información incremental.

## Evidencia

- AUC: geometría publicada **0.7159**, proxies de volatilidad internos **0.7233**,
  vol realizada rezagada **0.6245**, EWMA **0.5601**, GARCH(1,1) **0.5662**.
- Forma pura vs mejor baseline: Δ −0.0166, IC95 [−0.0587,+0.0253].
- Forma incremental sobre el mejor modelo de vol: Δ **+0.0059**, IC95
  **[−0.0240,+0.0354]**.
- Geometría publicada vs sus propios cuatro proxies de vol: Δ **−0.0074**,
  IC95 **[−0.0214,+0.0064]**.

## Checklist

1. **Baseline:** fuerte y explícito: realizada, EWMA y GARCH(1,1).
2. **Control de nivel:** no hay control aleatorio, pero la métrica es AUC y la
   comparación incremental es la adecuada para atribución; no afecta al rechazo
   de la atribución geométrica.
3. **Features:** cuatro de once variables llamadas geometría son proxies de vol;
   están aisladas explícitamente.
4. **Componentes propios:** superado; los proxies internos igualan o superan al
   modelo completo.
5. **Fuga temporal:** GARCH se ajusta solo en train y los clasificadores se
   entrenan en train; objetivo futuro no entra en las features actuales.
6. **Degenerados:** no se observa caso constante; AUC se protege ante una sola
   clase.
7. **Referencia:** objetivo común y split temporal compartido por modelos.
8. **Método simple:** realizada rezagada es el mejor baseline externo (0.6245),
   aunque la representación de cuatro proxies (0.7233) es mejor que una medida.
9. **Dato:** no se detecta en el manifiesto un defecto de calendario o precio que
   explique por sí solo el resultado; la fuente y el corte están registrados.
10. **Exploración:** la selección del mejor baseline entre tres se declara; el
    contraste con proxies propios evita que la conclusión dependa de esa selección.

## Conclusión para integración

Conservar `review` y reformular la contribución: representación multi-medida de
volatilidad que supera EWMA/GARCH de una sola medida. Eliminar cualquier frase
que atribuya la ventaja a compresión, forma o geometría del canal; el intervalo
incremental incluye cero.
