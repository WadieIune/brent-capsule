# Arquitectura propuesta — framework DQ multicapa

## Propósito

Detectar y priorizar problemas de calidad en millones de series financieras de
tipologías distintas. El Risk Director recibe alertas contextualizadas para
decidir revisión/escalado. El framework no infiere que los movimientos extremos
sean errores y no corrige datos en automático.

## Flujo

```text
Feeds + metadatos + snapshots de procedencia
                  |
                  v
     Contrato de serie / clasificación
     (asset class, unidad, frecuencia, calendario, fuente)
                  |
                  v
 Capa 1: controles estadísticos y deterministas
  esquema · faltantes · duplicados · TRIM · 3σ/robustos
  rango/tick · retornos · reglas de curva y calendario
                  |
          señales y evidencias
                  v
 Capa 2: controles automáticos e inteligentes
  canal/supervivencia · pares cross-asset · CNN · XGBoost
  visión para localización cuando proceda · generativo para escenarios
                  |
                  v
 Alertas trazables y priorizadas para Risk Director
  serie/tramo · controles activados · score calibrado · explicación
                  |
                  v
 Revisión humana · decisión registrada · feedback etiquetado
                  |
                  +----> monitorización de drift, calidad y recalibración
```

La capa 2 complementa la capa 1. Canal/supervivencia representa geometría y
persistencia; XGBoost agrega evidencia tabular y puede combinar controles. CNN
aprende forma temporal/multivariante. Visión ayuda solo en objetos donde la
localización espacial importe, como curvas. Los generadores producen casos de
prueba, no etiquetas verdaderas por sí solos.

## Contratos de evaluación

- **Datos:** splits temporales y por fuente/activo; transformaciones *as-of*;
  datos limpios de estrés y defectos conocidos; eventos extremos legítimos como
  negativos de control.
- **Calidad DQ:** recall/precisión por familia, FPR e intervalos, retraso y
  localización; comparación con controles 3σ/TRIM y reglas especializadas.
- **Transferencia:** tipologías y familias no vistas; sensibilidad a régimen,
  calendario, frecuencia, fuente y escala.
- **Operación:** falsas alertas por serie-día, volumen de revisión, throughput,
  latencia, coste, trazabilidad, versionado, drift y fallback determinista.
- **Decisión:** desplegar una herramienta solo si aporta cobertura/automatización
  medida frente al baseline, con coste y carga de alertas aceptables.

La distribución de rendimientos (empírica vs referencia normal) sirve para
auditar supuestos de 3σ; no clasifica por sí sola un dato como bueno/malo. El
impacto sobre riesgo/capital puede estudiarse fuera del objetivo primario y no
se reporta sin posiciones, notional y método aprobados.

## Estado

Arquitectura de investigación, no sistema productivo validado. La escala de
millones de series y la generalización entre asset classes siguen pendientes de
demostración operacional.
