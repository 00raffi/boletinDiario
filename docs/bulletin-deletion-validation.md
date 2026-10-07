# Eliminación de boletines y reconstrucción local — 2026-10-06

## Comportamiento

- `DELETE /api/bulletins/<día>/papers/<id>` elimina todas las pertenencias del artículo
  a búsquedas agrupadas en ese día local. La ficha recibe `bulletin_days` y permite
  elegir el boletín. Los enlaces desde un boletín llevan ese contexto a la ficha.
- `DELETE /api/bulletins/<día>` elimina todas las pertenencias del día, independientemente
  de los filtros visuales. El botón aparece únicamente en Biblioteca por boletines.
- Ambos botones piden confirmación. No se borran documentos, PDFs, resultados, marcas,
  tareas ni historial de consultas; tampoco se cambian filtros o preferencias.
- `bulletin_exclusions` conserva artículos eliminados por día y mantiene su consumo
  del cupo. `deleted_bulletins` impide reconstruir automáticamente un día eliminado,
  incluso si se elimina mientras una búsqueda espera metadatos de una fuente.
- El archivo y el boletín principal solo consultan pertenencias vigentes, no counters
  históricos de `runs`. El planificador no retrocede a generar trabajo de un boletín
  histórico por haber eliminado el vigente. Las tareas ya encoladas son independientes;
  el usuario puede cancelarlas por separado.
- `Engine.regenerate_today(clear_archive=True)` reemplaza, en una transacción, todas
  las pertenencias por una selección para hoy desde metadatos locales recientes,
  con filtros y cupos actuales. Reutiliza resultados y no reactiva tareas canceladas.
  No se añadió una opción de borrado masivo a la interfaz: se ejecutó una vez por
  petición explícita del usuario.

## Verificación

**154 pruebas automatizadas** y Ruff pasan. Las seis pruebas nuevas cubren:
eliminación por fecha local en runs repetidos, permisos/origin/fechas inválidas,
preservación de datos y trabajos, desaparición de fechas y fallback del boletín,
consumo de cupos sin reinserción, eliminación durante discovery y reconstrucción
local respetando filtros, fuentes, resultados y cancelaciones.

En una copia aislada sin coordinador ni tráfico externo, el navegador comprobó:

- La ficha mostraba el día correcto y solo el borrado individual.
- Borrar ParaKit redujo el boletín de ocho a siete artículos; el resumen permaneció
  guardado y el botón desapareció al dejar de tener pertenencias.
- Biblioteca mostró el botón de borrado completo. Cancelar la confirmación conservó
  las siete entradas; confirmar eliminó el día y deshabilitó el botón.
- La biblioteca mantuvo sus 2860 documentos. Sin errores de consola ni overflow.

## Aplicación real

Había un resumen de ParaKit en curso. Se pausó únicamente el inicio de nuevas tareas
y se esperó a que terminara, sin perder las nueve secciones confirmadas. Después se
detuvo el servicio de aplicación para actualizar y ejecutar la reconstrucción.
No se reinició el servicio Ollama dedicado.

Respaldos consistentes:

- `data/validation/bulletin-deletion-20261006/before-171827.sqlite3` (inicio de mantenimiento).
- `data/validation/bulletin-deletion-20261006/before-rebuild-172308.sqlite3` (justo antes del borrado).

Se borraron las pertenencias de los boletines anteriores (5 y 6 de octubre, cuatro
runs con contenido). El archivo ahora contiene solo **6 de octubre de 2026**, con un
run regenerado y **8 artículos: 6 Colibrí + 2 arXiv**, IDs
2847, 2848, 2849, 2850, 2851, 2852, 1998, 1999.

La comparación inmediata de todas las columnas de los 2860 documentos contra el
respaldo más reciente fue idéntica. El ledger de solicitudes permaneció idéntico;
la reconstrucción no modifica cursores de fuentes. Job 13 siguió cancelado. Se restauró
la preferencia de pausa original; GET settings coincide con la configuración inicial.

Ambos servicios quedaron activos. IMPETOM I continuó automáticamente como job 52;
la comprobación mostró un resumen terminado, uno en curso y seis pendientes. No se
afirma que los ocho resúmenes de PDF hayan terminado: el boletín ya está reconstruido,
y sus resultados pendientes se completan mediante el coordinador normal.

Artefactos `original-settings.json`, `regenerated.json` y `after.json` se guardaron en
la misma carpeta de validación. Se verificó en producción que Biblioteca muestra
únicamente la nueva fecha, con ocho entradas y el control de eliminación completo.
