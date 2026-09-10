# Challenge C3 — `dq_synthetic_validation`

**Autor:** Agente A  
**Auditor:** Agente B  
**Estado:** ✅ confirmado como `reject`, con alcance acotado a las familias interpretables.

## Veredicto

El rechazo pre-registrado es reproducible y no depende de una comparación débil:
la geometría pierde materialmente frente a Hampel/MAD en `outlier_de_cola`, y no
supera al detector de rachas en `stale_fill`. Por tanto no puede sostenerse la
afirmación de superioridad general del control geométrico.

## Evidencia

- `stale_fill`: AUC-PR geométrica 0.9453 vs detector de rachas 0.8229; recall
  0.7594 vs 0.6922. El criterio ciego exige recall del baseline <0.10, por lo
  que falla.
- `salto_reversible`: ΔAUC-PR +0.1977, IC95 [+0.0445,+0.3554].
- `outlier_de_cola`: ΔAUC-PR −0.5074, IC95 [−0.6349,−0.3703] frente a Hampel/MAD.
- `precio_no_positivo`: AUC geométrica 1.0, pero falta el rival de dominio
  directo `price <= 0`; el resultado solo prueba que supera los detectores
  estadísticos incluidos.
- `desfase_calendario`: la propia desviación registrada indica que la verdad
  etiqueta todo el bloque desplazado aunque solo los bordes sean observables;
  esta familia no debe usarse para una conclusión de capacidad.

## Checklist

1. **Baseline:** fuerte para las familias estadísticas; incompleto para precio
   no positivo, donde un validador de dominio sería el comparador natural.
2. **Control de nivel:** presente: detector aleatorio con igual volumen.
3. **Features:** el score combina banda, salto ATR y rachas; no hay evidencia de
   fuga hacia el futuro en la descripción del detector.
4. **Componentes:** el score combinado no permite atribuir qué regla produce la
   ventaja en cada familia, pero eso no rescata el criterio global fallido.
5. **Fuga temporal:** la inyección se hace sobre serie base limpia y posiciones
   conocidas; no se observa fuga temporal decisiva.
6. **Degenerados:** el proyecto corrigió explícitamente el caso de score
   constante mediante presupuesto fijo de alertas.
7. **Verdad:** correcta para las cuatro familias salvo el desfase, que está
   reconocido como error de diseño.
8. **Especializado:** el detector de rachas alcanza recall 0.6922 en stale; la
   hipótesis de ceguera frente a un método especializado queda refutada.
9. **Dato:** serie base limpia y sin forward-fill, conforme al diseño.
10. **Exploración:** 3 tasas × 10 semillas y una configuración geométrica,
    declaradas; el veredicto usa los umbrales congelados.

## Conclusión para integración

Mantener `reject`. Puede afirmarse que la geometría ayuda en saltos reversibles,
pero no que domine detectores especializados ni baselines robustos en todas las
familias. La familia `desfase_calendario` debe quedar explícitamente fuera de
las conclusiones cuantitativas.
