# Ficha, marcas visibles y archivo de boletines — 2026-10-06

Esta validación documenta la versión anterior con dos pestañas y generación bajo
demanda. Fue reemplazada, a petición del usuario, por un único resumen automático:
ver `docs/summary-only-validation.md`. Las observaciones científicas sobre
`section-overview-v3` siguen vigentes; los informes técnicos guardados se preservan.

## Comportamiento actual

La ficha tiene solo Resumen y Análisis técnico. Resumen presenta por qué puede
interesarte, abstract original, resúmenes de las secciones principales y apoyo
institucional explícito. Las secciones/apoyos se obtienen mediante una tarea
`overview` solicitada por un botón; abrir la ficha no inicia una inferencia ni una
descarga. Los resúmenes breves del boletín y los análisis técnicos siguen preservados.
No se cambió la automatización del análisis técnico mientras el usuario la evalúa.

Las marcas de interés ya no ocultan artículos del boletín. Se conservan visibles,
sin feedback al modelo. Biblioteca ofrece vista por boletín, todos los días con
artículos guardados, enlaces directos y botones para navegar fechas. Agrupa runs de
un día local, deduplica IDs y conserva selecciones históricas sin los cupos actuales.
Un mismo artículo puede pertenecer a varios días, con su resultado actual, no un
snapshot independiente de cada regeneración.

## Límites de lectura

Se prefieren marcadores del PDF para identificar capítulos; sin índice se usan
encabezados conservadores. La comprobación local del PDF de ParaKit localizó nueve
capítulos principales incluida la conclusión, sin descargarlo. El índice permite
reservar páginas iniciales/finales de capítulos aunque el PDF tenga más de 100 páginas.
Sin índice (por ejemplo IMPETOM I) la detección es menos fiable y puede omitir capítulos
o encontrar conclusiones parciales. No se garantiza reconocer la estructura completa.

El resumen usa extractos acotados, no todas las páginas de cada sección. No hay OCR,
interpretación de imágenes ni evaluación científica independiente. Se incluyen páginas
y citas, y se indica si no se encontró conclusión. No se deduce apoyo de afiliaciones:
el nombre y una señal de financiación/apoyo deben figurar en el mismo extracto.

## Pruebas y hallazgo real

**139 tests** y Ruff pasan. Cobertura añadida: agrupación de fechas locales y legadas,
deduplicación, días sin boletín, archivo sin recorte por cuotas/marcas, filtro de fuente,
tipo overview, uso de PDF sin abstract como sustituto, caché, ausencia de encabezados,
secciones en la misma página, páginas distantes, evidencia inventada, idioma y apoyos.

La primera prueba real de Qwen rechazó citas reescritas (espacios y fórmulas del PDF).
No se guardó un resumen final sin evidencia. El diagnóstico reprodujo el fallo y
conservó solicitudes/respuestas en `/tmp/opencode/sections-diagnosis-xalp3eft/`.

Se cambió a **section-overview-v2**: el modelo selecciona IDs de extractos y Python
copia la cita original, con su página. Una cita o página no se inventa al serializar;
los IDs deben existir y un resumen no vacío debe citar alguno. El nombre y señal de
apoyo se vuelven a validar contra el extracto. Esto evita exigir una transcripción
perfecta al modelo, pero no verifica que cada interpretación sea científicamente correcta.
Un diagnóstico real de la introducción pasó en el primer intento con ese formato;
se detuvo deliberadamente tras una sección, no fue una prueba completa.

Una segunda prueba completa generó siete secciones con v2, pero la inspección del
texto mostró un fallo de límites: el título espaciado `C ONCLUSION` no se encontraba,
y se enviaba texto de trabajo relacionado/bibliografía como conclusión. Ese resultado
intermedio se conserva en `live-arxiv-overview-v2.json`, no se presenta como validación
científica. **v3** reconoce líneas de encabezado con espacios internos y diacríticos,
sin confundir menciones en párrafos; la conclusión se corta al comenzar referencias.
Se añadió una regresión de secciones vecinas y bibliografía. El extracto determinista
final de conclusión se inspeccionó contra el PDF local antes de regenerar el resultado.

La interfaz se comprobó con una base separada y ejemplos simulados: exactamente dos
pestañas, cuatro bloques en el orden pedido, conclusión y apoyos visibles, navegación
entre los días 5 y 6, marca persistida sin desaparición y botón que encola overview.
No se aplicaron marcas ni resultados simulados a producción. Consola sin errores.
La navegación real por `localhost:8765` mostró 28 artículos del día 6 y 10 del día 5,
sin desbordamiento horizontal ni texto null.

## Despliegue

Se comprobó que el servicio estaba libre antes de reiniciar. Hay respaldo SQLite en
`data/validation/sections-20261006/`; la migración añade `papers.overview` sin reemplazar
filas ni cancelar tareas. Los ajustes y resultados anteriores se conservan.
Se solicitó una validación completa de las siete secciones principales de un PDF local
ya guardado (paper 2013), sin consulta a arXiv ni nueva descarga. Resultado capturado en
`data/validation/sections-20261006/live-arxiv-overview.json` al terminar.

La prueba completa **v3 terminó correctamente**: siete secciones, incluida la
conclusión, contenido en inglés y sin organizaciones de apoyo identificadas (no es
prueba de ausencia). La conclusión se ancló al párrafo correcto de la página 9,
conservando las condiciones «64 candidatos», «mismo checkpoint/presupuesto» y «sin
leer respuestas de referencia». Los contadores externos quedaron iguales: 0 arXiv
y 17 Colibrí en producción antes/después de la validación. No hubo descargas nuevas.
Las preferencias coinciden con las anteriores; el job 13 sigue cancelado. La comparación
con el respaldo de 2860 documentos no encontró cambios en sus briefs o análisis técnicos.
