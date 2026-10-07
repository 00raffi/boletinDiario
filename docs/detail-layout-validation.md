# Simplificación de la ficha y ancho del resumen — 2026-10-07

## Cambios

- Se quitó de la ficha el texto «Las marcas se conservan visibles en el boletín y la
  biblioteca. No cambian búsquedas ni cancelan tareas» y el bloque «En boletín» con
  selector de fecha. Las marcas y la pertenencia guardada no se alteran.
- El botón **Eliminar de este boletín** permanece junto a las acciones principales.
  Usa el día del enlace de entrada o, sin contexto, el más reciente. Tooltip y
  confirmación indican la fecha. Si se abrió con un día al que ya no pertenece,
  no se ofrece eliminarlo de otro día por defecto. Tras eliminar sin contexto,
  se conserva el contexto del día eliminado en la URL para no cambiar de objetivo.
- La ficha tiene clase `paper-detail`; el resumen agrega `article-summary` y el
  render establece `main[data-view]`. Solo en la ficha se elimina el max-width del
  área principal. El resumen anula el máximo legado de 900 px de `.technical`,
  ocupa todo el ancho interior y ajusta palabras largas sin overflow.
- Se mantienen los paddings simétricos y breakpoints existentes; biblioteca,
  configuración y boletín no cambian sus límites de ancho.

## Verificación

**160 pruebas** y Ruff pasan. En la ficha real de ParaKit se verificaron ausencia
del aviso, etiqueta y selector, presencia del botón con fecha correcta y resumen
con `max-width: none`. No se ejecutó ninguna eliminación para validar la UI.

Se probaron copias del DOM de la ficha con el CSS real en documentos aislados,
sin scripts de aplicación, para estos anchos de viewport:

| Ancho | Margen izquierdo interior | Margen derecho interior | Overflow horizontal |
| ---: | ---: | ---: | --- |
| 375 px | 16 px | 16 px | No |
| 1280 px | 42 px | 42 px | No |
| 2100 px | 60 px | 60 px | No |

No se modificaron parámetros, resultados ni procesamiento. Son cambios estáticos:
no requieren reiniciar servicios o interrumpir inferencias; sí recargar la página
para cargar el JavaScript y CSS nuevos.
