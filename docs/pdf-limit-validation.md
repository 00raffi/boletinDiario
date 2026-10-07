# Tamaños PDF y límite de descarga — 2026-10-06

El límite anterior de 20 000 000 bytes bloqueó tres de las ocho tareas de resumen
antes de extraer el texto del PDF. Los briefs quedaron guardados y no hubo un fallo
de contexto del modelo. Se confirmó en logs que arXiv fallaba al comprobar Content-Length;
Colibrí rechazó el peso informado por sus metadatos.

Con aprobación del usuario, el máximo pasó a **100 MB**, con configuración persistida
`max_pdf_mb` y control visible de 1–250 MB. Colibrí y arXiv leen el mismo valor actual.
La extracción sigue acotada a 100 páginas/300 000 caracteres y el contexto a 4096;
no se cambiaron prompts, presupuesto por llamada, modelo ni filtros. Se preservó el
máximo de 40 secciones que el usuario había guardado durante la sesión.

## Tamaños informados por las fuentes

Se hicieron únicamente tres solicitudes HEAD a URLs oficiales, con validación de
destino/redirecciones, serialización por fuente, pausas y ledger persistente. No se
descargaron cuerpos PDF para medirlos ni se hicieron consultas al API de búsqueda.
Las tres respuestas fueron 200 con Content-Type PDF y Content-Length:

| ID | Documento | Bytes | MB decimales |
| --- | --- | ---: | ---: |
| 2848 | Métodos sísmicos aplicados al análisis estructural de turbinas eólicas terrestres | 20 372 116 | 20,37 |
| 1998 | The Universal Weight Subspace Hypothesis | 20 825 004 | 20,83 |
| 1999 | One Figure, Every Canvas: Editable Flowchart Relayout via Agentic Pipeline | 44 748 090 | 44,75 |

Los tres están por debajo del nuevo máximo. Sus tareas permanecen en error hasta un
reintento explícito: esta actualización no encola descargas ni cambia cancelaciones.
Los mensajes nuevos indican el tamaño declarado y el límite, o que se detuvo una
descarga sin tamaño conocido al exceder el máximo. Los errores antiguos se conservan
como registro de lo ocurrido bajo el límite anterior.

## Validación y despliegue

**160 pruebas** y Ruff pasan. Se cubrieron preferencias/default/límites, ambas fuentes,
rechazo por metadatos antes de descargar, errores explicativos, HEAD sin lectura de
cuerpo, registro de redirecciones y respeto de Retry-After tras 429.

Se reinició solo la aplicación tras comprobar que no había trabajo activo. Respaldo:
`data/validation/pdf-limit-20261006/before-175846.sqlite3`.
`sizes.json` conserva las cabeceras relevantes y `previous-settings.json` los ajustes
anteriores. El cambio persistido fue únicamente añadir `max_pdf_mb=100`.
