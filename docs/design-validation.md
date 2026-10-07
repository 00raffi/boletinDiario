# Idioma e intereses: validación del 2026-10-06

## Alcance

- Interfaz sin nombre de aplicación ni eslogan: descripción breve de uso personal.
- Nuevos resúmenes y notas en el idioma original; resultados existentes conservados.
- Propuesta puntual de filtros desde texto libre, revisable antes de aplicar.
- Catálogo local de arXiv y consultas por categorías/términos, sin reanalizar gustos a diario.

## Pruebas y fallos conservados

La primera ejecución real (`/tmp/opencode/reading-design-qv5t0pz6/`) pasó el caso inglés
pero falló el español. El diagnóstico guardado en
`/tmp/opencode/reading-design-spanish-diagnosis/` mostró que el contenido estaba en
español y el modelo omitía el campo opcional `language`: el valor predeterminado `en`
activaba incorrectamente el rechazo en ambos intentos.

Se retiró ese campo del esquema de inferencia. La etiqueta ahora se determina en
Python a partir del texto original, y la validación compara el idioma detectable del
contenido generado. No hay otra llamada al modelo para detectar el idioma.
Una regresión prueba respuestas españolas sin etiqueta y el reintento por traducción.

La primera propuesta de intereses decía incluir `cs.CR`, pero no figuraba en la lista;
además generaba variantes poco naturales, como “privacy differential”. Se reforzó el
prompt con términos habituales y se añadió una comprobación literal de los códigos
citados en la explicación. No es una validación semántica exhaustiva: la persona debe
revisar términos, categorías, omisiones y advertencias.

## Validación automatizada e interfaz

**94 pruebas automatizadas** y Ruff pasan. Incluyen catálogo y alias, frases literales,
límites de palabra, consultas agrupadas y deduplicación, idiomas, caché de propuestas,
no aplicación automática, no reinterpretación durante búsquedas, reserva de inferencia,
liberación ante fallo/cancelación y regeneración sin perder el resultado anterior.
Persiste un aviso de deprecación de Starlette/TestClient, sin fallo de prueba.

La interfaz se probó en navegador: descripción sin marca, campo de intereses,
propuesta editable con advertencias, y serialización correcta al guardar. Para comprobar
los eventos de propuesta/guardado se interceptaron esas respuestas en una pestaña de
prueba; la configuración real no se modificó y la pestaña se recargó después.
No se dispone de Node en el equipo; el navegador cargó y ejecutó el JavaScript.

## Segunda ejecución real

`/tmp/opencode/reading-design-np1534jt/` conserva la propuesta y las cinco peticiones
reales a Qwen (propuesta, dos resúmenes y dos extracciones). Todas se aceptaron en el
primer intento. Ambos resúmenes y notas mantuvieron inglés/español, respectivamente;
la propuesta volvió a pedirse desde caché sin inferencia y no modificó Settings.

La propuesta ya incluyó `cs.CR` de forma coherente y términos habituales. Aun así,
eligió `cs.NE` para neurociencia computacional en lugar de `q-bio.NC`, no añadió variantes
españolas y produjo advertencias demasiado generales. Esto confirma que la revisión
previa a aplicar es necesaria, no que el modelo clasifique siempre correctamente.

Se verificaron dos citas inglesas y cuatro españolas. Una cita inglesa generada como
“We report…” no aparecía literalmente en el texto (“…and report…”), y se descartó sin
alterar el original. Los resúmenes conservan el alcance sintético y preliminar, pero
estas pruebas no prueban fidelidad de cada formulación.

La consulta real con los filtros propuestos recibió **HTTP 429 de arXiv**; la ejecución
terminó en error en esa etapa y no demuestra aceptación de la consulta por el servidor.
No se insistió ante el límite. La composición, división y deduplicación de consultas sí
están cubiertas por tests con transporte simulado. Producción conserva su reintento
de búsquedas tras 30 minutos, con cursor sin avanzar cuando hay error.

Los artefactos y el diagnóstico del fallo inicial se conservan en
`data/validation/design-20261006/`. Los filtros de ejemplo no se aplicaron a producción.

## Límites

La detección en/es es heurística, no identificación universal de idiomas. La coincidencia
de búsqueda es literal y puede omitir sinónimos o variantes; las exclusiones afectan solo
al boletín. El modelo puede proponer categorías o frases poco pertinentes. arXiv no cubre
todos los intereses y Colibrí continúa sin integrar. Los casos controlados no certifican
fidelidad científica de resúmenes ni calidad general de los filtros.
