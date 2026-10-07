# Colibrí con las fuentes ampliadas — 2026-10-07

La persona guardó 19 ámbitos de Colibrí y solicitó repetir la búsqueda para completar
el boletín del día, conservando los cinco documentos ya seleccionados. Los cupos
guardados eran 15 totales, hasta 12 de Colibrí y tres de arXiv.

## Incidencia y corrección

El programador intentó buscar automáticamente tras el cambio. La comunidad
**Convenios** (`f1de19bf-63a3-4af8-b929-9ecb4e030054`) respondió HTTP 422,
`Invalid search request`, con la configuración de búsqueda implícita.
Una prueba controlada y registrada usando `configuration=default`, conservando
ese mismo ámbito, respondió HTTP 200 y confirmó `dc.date.accessioned,DESC`.

`radar/colibri.py` ahora indica esa configuración pública explícitamente. No elimina
ámbitos, no amplía comunidades por su cuenta ni deja de verificar el orden de
depósito. La prueba regresiva simula una comunidad que rechaza la configuración
implícita y comprueba la conservación del scope. **194 tests y Ruff pasan.**

## Repetición real

Se respaldó la base en
`data/validation/colibri-expanded-20261007/before-132111.sqlite3`.
Se reinició la aplicación solo después de verificar que no había inferencia,
búsqueda o propuesta de intereses activa. No se reinició Ollama. Se eliminó la
espera local correspondiente al 422 corregido; no había pausa de red HTTP vigente.
El programador retomó únicamente Colibrí, que estaba pendiente.

- 18 peticiones de metadatos, todas HTTP 200; Fing incluye InCo, por lo que no se
  repite la consulta para esos dos ámbitos.
- 23 documentos nuevos guardados.
- Siete documentos añadidos al boletín, conservando los cinco anteriores.
- Resultado del 7 de octubre: **12 de Colibrí + 3 de arXiv = 15 artículos**.
- Estado del recorrido: completo, sin error.
- Siete jobs nuevos de resumen; no se reactivaron errores ni cancelaciones previas.

`preservation-check.json` conserva todas las filas anteriores de runs, jobs,
boletines, solicitudes y exclusiones/tombstones. La configuración, el estado de
arXiv y su punto de continuación permanecen idénticos al respaldo. No hubo
peticiones de arXiv durante esta repetición.

Respuestas diagnósticas, configuración, estado, run, selección y comprobación de
preservación están en `data/validation/colibri-expanded-20261007/`. El boletín del
6 de octubre permanece sin cambios. Los 12 siguen siendo un cupo máximo diario,
no una garantía para futuras fechas sin suficientes novedades elegibles.
