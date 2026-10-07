# Resumen único automático y PDF de Colibrí — 2026-10-06

## Resultado

- La ficha ya no tiene pestañas ni controles de análisis técnico. Muestra **Resumen**:
  afinidad, abstract original, secciones principales (incluida conclusión si se localiza)
  y organizaciones con declaraciones explícitas de apoyo/financiación.
- Cada artículo seleccionado encola una sola tarea `summary`. Guarda el brief antes
  de procesar el PDF y reutiliza resultados existentes y secciones confirmadas.
- Los endpoints anteriores de brief/overview encolan el resumen único. El endpoint
  de análisis técnico responde 410; el coordinador no inicia esos trabajos.
- Los informes y notas previos se conservan, también en las exportaciones. No se
  traducen resultados ni se reactivan cancelaciones explícitas.
- **Ver PDF** está en tarjetas y ficha de Colibrí. Resuelve el único PDF ORIGINAL o
  el archivo primario, guarda su URL y abre el enlace oficial en otra pestaña. Resolver
  no descarga el contenido ni llama a Ollama; el repositorio controla sus permisos.
- Se retiraron cupos, pestaña y pausas de análisis de la configuración. **Pausar
  resúmenes** evita iniciar nuevas inferencias; una tarea activa se cancela por separado.

## Verificación

**148 pruebas automatizadas** y Ruff pasan. La consola del navegador en producción
no mostró errores. La ficha de ParaKit mostró cero tabs, el enlace PDF correcto y
el círculo lateral avanzando por secciones confirmadas, sin desbordamiento horizontal.

Se probaron resolución/caché PDF sin descargar contenido de 30 MB, seguridad local,
generación única, conservación de informes, persistencia de brief ante fallo PDF,
reintento sin repetir brief, migración idempotente, PDF ausente explícito, bloqueo
de análisis legado, pausa y cancelación del resumen con recuperación.

En navegador, sobre una copia aislada sin coordinador:

- Paper 2013: cero tabs, los cuatro bloques en orden, siete secciones incluida Conclusion,
  texto en inglés conservado, sin `null` ni desbordamiento horizontal.
- Configuración: cero controles técnicos, pausa de resúmenes visible, cupos **6 + 2**.
- Paper 2849 de Colibrí: enlace oficial **Ver PDF** con apertura en otra pestaña; el
  informe técnico almacenado no aparece en la ficha.
- Paper 2850: respuesta PDF simulada solo en navegador para verificar reemplazo del
  botón por enlace y POST explícito, sin emitir solicitudes al repositorio.

La validación científica del generador v3 se conserva en `docs/sections-validation.md`.
Esta actualización no cambia prompts ni validación de citas y no afirma garantizar
estructura completa, interpretación correcta o hallar todos los apoyos.

## Despliegue y preservación

Se comprobó que no había búsqueda, inferencia ni compilación de intereses activa.
Respaldo consistente:
`data/validation/summary-only-20261006/before-171309.sqlite3`.

Tras reiniciar únicamente `paper-radar.service`, ambos servicios de usuario están
activos. Se encolaron ocho resúmenes para el boletín visible (6 Colibrí y 2 arXiv),
no para todo el archivo. Job 51 comenzó automáticamente con ParaKit, usando el PDF
ya guardado; el estado inicial detectó nueve secciones. Se dejó continuar sin
interrumpirlo: esta comprobación no es una afirmación de haber terminado las ocho tareas.

Comparación inmediata de los 2860 documentos con el respaldo: sin cambios a briefs,
informes técnicos, favoritos, leído/no leído ni marcas. Settings persistidos intactos;
los campos técnicos antiguos se ignoran en el nuevo flujo. Job 13 sigue cancelado.
PDF API de 2849 devolvió el enlace ya guardado sin tráfico externo; API de análisis
respondió 410. Contadores de fuentes al verificar: Colibrí 17 / arXiv 0, sin nuevas
consultas de prueba a arXiv. Las tareas normales siguientes pueden descargar sus PDFs.
Estados antes/después guardados en la misma carpeta de validación.
