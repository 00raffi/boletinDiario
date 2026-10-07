# Cola y estado de procesamiento — 2026-10-06

## Cambios

- `/api/activity` devuelve hasta 10 tareas con prioridad: en curso, en cola, historial
  reciente. Incluye `jobs_total` y `job_limit`. No borra ni limita tareas almacenadas.
- `POST /api/jobs/{id}/cancel` cancela solo la tarea identificada, tanto resumen como
  análisis. Una tarea en cola cambia de estado antes de iniciar. Una tarea en curso
  se interrumpe y termina su limpieza antes de confirmar la respuesta.
- Responde 404 si no existe y 409 si ya terminó, está finalizando o no es cancelable.
  Conserva las protecciones de origen y cabecera de las demás operaciones locales.
- Cancelar no borra el resultado previo ni las notas confirmadas. La recuperación al
  reiniciar no reactiva tareas canceladas. Un reintento es una acción explícita.
- La barra lateral muestra estado, título enlazado y círculo de progreso al pie.
  El arco representa fragmentos confirmados: leyendo 19/24 significa 18/24 completos
  (75 %), no 19/24. Descarga, extracción y resumen sin medida muestran actividad
  indeterminada; se respeta la preferencia de reducir movimiento.
- Se retiraron los textos «Procesamiento local» y «Resúmenes y notas para uso personal».
- Las ramas de la ficha que añadían `null` directamente a `Element.append` usan el
  constructor seguro de nodos; no convierten valores vacíos en texto visible.

## Comprobación

125 pruebas automatizadas y Ruff pasan. Se añadieron regresiones para límite y orden,
preservación de historial/resultados, cancelación individual en cola y en curso,
cancelación antes de iniciar inferencia, doble cancelación, limpieza y recuperación.

Prueba de navegador aislada mediante `/tmp/opencode/check-queue-ui-20261006.py`, con
16 tareas guardadas e inferencia simulada, sin solicitudes a arXiv, Colibrí ni Ollama:

- 10 filas visibles y 3 botones Cancelar (1 en curso + 2 en cola).
- Se cancelaron una tarea en cola y otra en curso usando los botones; la tercera quedó
  en cola, las demás tareas se conservaron, y el estado lateral volvió a reposo.
- Círculo al 75 %, accesibilidad `aria-valuenow=75`, sin estado duplicado sobre contenido.
- Ficha «Solo abstract» sin nodos de texto `null` o `undefined`.
- Consola sin errores y vista de escritorio sin desbordamiento horizontal.

Se comprobó además la ficha real de ParaKit en producción, incluyendo la pestaña de
fuente, sin `null` visible. No se cancelaron tareas reales durante las pruebas.

El despliegue esperó a que terminara el análisis de IMPETOM I (job 49). El servicio
se reinició con la nueva API y se restauró `pause_detailed=false`, su valor previo al
mantenimiento. Verificación de producción: 10 filas devueltas de 49 tareas guardadas;
jobs 48 y 49 completados, job 13 todavía cancelado. No se hicieron consultas nuevas
a arXiv/Colibrí para validar estos cambios.
