# Handoff WP4 — puente CNN → FRTB

El prototipo de `code/applications/experiments/frtb_data_quality_gate.py` está
publicado en `track-b` (commit `43ea45a`). El contrato de integración es:

`prob_ascending_channel`, `prob_descending_channel` y el
`weighted_outlier_score` de la inferencia CNN → señal de revisión por factor →
gate `pass/review/block` → evidencia RFET/NMRF → entrada controlada a ES/PLA.

La señal CNN no calcula capital, no sustituye ES y no certifica RFET. Un score
alto añade `cnn_channel_review`; precio no positivo o relleno severo bloquea.
La decisión `rfet_proxy_pass` sigue marcada como proxy y requiere procedencia
de precios reales y validación humana/regulatoria.

**Acción para A:** auditar este puente y preparar su integración en WP4; no
registrar el módulo como experimento hasta validar el contrato y sus baselines.
