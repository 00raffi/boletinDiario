# Validación de la primera versión

Realizada en este equipo el 5 de octubre de 2026.

- Linux; Python 3.14.4; Ollama local con `gemma3:4b` instalado.
- 38 pruebas automatizadas: horario, recuperación, cola, versiones, límites de
  descarga, redirecciones, XML seguro, seguridad HTTP, PDF en proceso separado,
  citas literales, cobertura parcial y ausencia de síntesis sin evidencia.
- Ruff: sin errores en backend, scripts y pruebas.
- Interfaz probada en navegador: boletín, biblioteca, configuración, actividad y ficha.
- API real de arXiv: **1997 registros** recuperados para la última semana en `cs.AI`,
  incluyendo publicaciones compartidas con otras categorías. 10 seleccionados.
- Resumen real de `2610.03717v1` con Gemma: aproximadamente **27,6 segundos** en la
  última prueba, 346 tokens de salida. No es un benchmark general del equipo.
- PDF real: 23 páginas, 34 fragmentos extraídos. Prueba limitada a **un fragmento
  de la primera página**; dos notas con citas literales localizadas. No se presenta
  esa prueba como análisis de todo el documento.
- La generación libre de una síntesis a partir de notas añadió expansiones inventadas
  de siglas, incluso con instrucciones restrictivas. Se eliminó esa etapa: el informe
  final agrupa notas verificables por sección sin generar hechos adicionales.
- Servicio de usuario `paper-radar.service` instalado y activo, con cita diaria a
  las 07:00 `America/Montevideo`. La cola inicial continúa en segundo plano.

Pendiente: evaluación científica sistemática en 10–20 papers, comparación con
Qwen3.5:4B y medición de análisis largos completos. Las citas verificadas no garantizan
que la interpretación del modelo sea correcta; los informes requieren revisión humana.

## Ampliación: avisos de escritorio

- Suite ampliada a **50 pruebas**: envío tras guardar resultados, desactivación,
  aislamiento de fallos, cancelación, límites del proceso y texto externo escapado.
- Notificaciones nativas mediante `notify-send`, sin shell, habilitadas por defecto.
- Endpoint de prueba ejecutado desde el servicio de usuario: respuesta `sent`.
  Confirma aceptación por el servicio de escritorio; la visibilidad depende de
  No molestar y de las preferencias del sistema.

## Ampliación: liberación de memoria

- Se observó `llama-server` con aproximadamente **11,6 GiB RSS** y contexto 4096.
  No se encontró historial acumulado en las peticiones de la aplicación.
- Se detuvo temporalmente Paper Radar y se descargó solo `gemma3:4b` por la API
  `keep_alive: 0`. El runner desapareció y el uso total pasó de unos 15 a 4,2 GiB.
- Prueba posterior con cuatro peticiones cortas: runner de aproximadamente 3,53 GiB
  RSS, seguido de descarga correcta. No constituye prueba de estabilidad con prompts largos.
- Liberación al finalizar tareas y reciclado cada cuatro fragmentos activados por defecto.
  Las notas se confirman antes de reciclar. No se borra ningún archivo ni modelo del disco.
- Investigación posterior: los logs identificaron una **caché de prompts de hasta
  8192 MiB**, separada del contexto activo, y checkpoints internos (máximo 32).
  Antes de la descarga había 31 prompts cacheados y **8159,767 MiB** de estados.
  Eso explica la mayor parte del salto del runner de unos 3,5 a 11,6 GiB.
- Tras el reciclado, la caché vuelve a cero. Un ciclo posterior mostró 306,750 →
  657,527 → 1002,780 MiB al acumular tres prompts; cada uno incluye sus checkpoints.
  Pesos/buffers CPU informados: 907,85 + 1459,69 MiB, KV activo: 80 + 174 MiB.
  Estos tamaños de logs no son un desglose exhaustivo ni una suma exacta del RSS.
- El ejecutable instalado indica `--cache-ram 0` para desactivar esa caché y permite
  `--ctx-checkpoints 0`; expone `LLAMA_ARG_CACHE_RAM` y `LLAMA_ARG_CTX_CHECKPOINTS`.
  No se cambió la configuración global del servicio Ollama. Se debe verificar la
  transmisión de esas opciones si se configura a través de su servicio.
- No se pudo leer `smaps_rollup` ni `maps`: el runner pertenece al usuario de sistema
  `ollama` y el kernel negó permisos. Los logs bastan para identificar esta causa,
  pero no para atribuir cada asignación de memoria o descartar otros problemas.

## Comparación controlada de cachés (2026-10-05)

Script: `scripts/check-memory.py`, detalles en `docs/inference-flow.md`.
Artefactos completos: `/tmp/opencode/radar-memory-m7kpmxwt/`.

Tres instancias temporales de Ollama, seis fragmentos idénticos del PDF local de
“4DCodeBench: Benchmarking Agents on Inverse Graphics of Dynamic Scenes”, mismo
`gemma3:4b`, contexto 4096 y límite de salida 1500 tokens. Sin reciclado intermedio
en ninguno de los modos. Comparación de `requests.json`: los seis cuerpos HTTP
coinciden exactamente entre modos. Sin reintentos de formato.

| Modo | RSS tras fragmento 1 | RSS tras fragmento 6 | Crecimiento | Tiempo total |
| --- | ---: | ---: | ---: | ---: |
| Predeterminado | 3,710 GiB | 5,318 GiB | 1646,81 MiB | 230,36 s |
| `LLAMA_ARG_CACHE_RAM=0` | 3,710 GiB | 3,770 GiB | 61,55 MiB | 286,11 s |
| Lo anterior + `LLAMA_ARG_CTX_CHECKPOINTS=0` | 3,563 GiB | 3,575 GiB | 12,16 MiB | 224,62 s |

Los logs confirman opciones efectivas: `prompt cache is disabled` en los dos modos
sin caché; `context checkpoints disabled` en el tercero. La caché predeterminada
llegó a 1598,156 MiB, cercana a los 1646,81 MiB de crecimiento de RSS observado.
No son un desglose idéntico: existen otras asignaciones y buffers.

Los tres modos guardaron seis fragmentos `done` y 24 hechos con citas coincidentes
en sus SQLite de prueba. Cada modo produjo 36 hechos antes de verificar; 12 se
descartaron por no coincidir página/cita literalmente. Los contenidos no fueron
idénticos, y esos conteos no demuestran equivalencia semántica ni calidad científica.

Conclusión: desactivar la caché histórica eliminó la mayor parte del crecimiento
en esta prueba; desactivar además checkpoints redujo memoria base y variación.
Los tiempos son de una sola ejecución secuencial por modo: diferencias de salida,
carga/frecuencia/temperatura del equipo y orden pueden influir. No prueban una
penalización o mejora fija de velocidad. Tampoco seis fragmentos garantizan un techo
de RAM para cualquier documento o modelo.

No se modificó el servicio principal ni sus opciones; el reciclado cada cuatro
fragmentos sigue habilitado en producción. Las instancias temporales se descargaron
y cerraron; la biblioteca principal conserva sus resultados y la tarea cancelada.
Se recomienda probar ambos ajustes en una lectura de 24 fragmentos antes de quitar
el reciclado intermedio en producción.

La primera ejecución quedó incompleta por un timeout externo de 120 s; su servidor
temporal se identificó por PID/directorio y se cerró antes de repetir sin timeout.
Sus artefactos `radar-memory-g0b9u5dj` no forman parte de esta comparación.

## Migración a Qwen: comparación inicial (2026-10-06 UTC)

Modelo instalado: `qwen3.5:4b`, arquitectura `qwen35`, 4,2B, Q4_K_M, Ollama 0.33.3.
Artefactos: `/tmp/opencode/radar-memory-mt8t4h_0/`. Mismos seis fragmentos de
4DCodeBench y un resumen de su abstract por modo. Se descargó tras el resumen
para iniciar la medición de fragmentos con un runner nuevo. Sin recargas entre
fragmentos. Contexto 4096, `think: false`, temperatura 0,1. Esta comparación aún
usó `presence_penalty` del modelo (1,5); no debe mezclarse con el ensayo posterior
con penalización explícita 0.

| Modo | RSS fragmento 1 | RSS fragmento 6 | Crecimiento | Tiempo fragmentos | Citas coincidentes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Predeterminado | 3,562 GiB | 4,563 GiB | 1025,19 MiB | 254,02 s | 22/30 |
| Sin caché histórica | 3,562 GiB | 3,594 GiB | 32,81 MiB | 242,10 s | 24/30 |
| Sin caché ni checkpoints | 3,464 GiB | 3,496 GiB | 32,97 MiB | 234,53 s | 26/30 |

Los logs confirman las opciones y una caché histórica máxima de 992,466 MiB en el
modo predeterminado. Los tres resúmenes respetaron el esquema en el primer intento;
tiempos 20–22 s con carga. La inspección del abstract no encontró cifras inventadas
ni una afirmación de superioridad añadida en esos resúmenes.

Hallazgos de calidad: el fragmento 1 (principalmente portada, figura y leyenda)
produjo `facts=[]` en los tres modos. No implica una lectura exhaustiva de la
leyenda. Algunas respuestas repitieron hechos o tradujeron mal términos técnicos
(por ejemplo, “verdad del suelo” para “ground truth”). También hubo citas
reformuladas que el filtro descartó. El conteo de citas coincidentes incluye
duplicados y NO es precisión científica ni una clasificación de calidad por modo.
La variación de respuestas y una única ejecución por modo impiden afirmar que
desactivar cachés mejora la fidelidad o la velocidad de manera general.

La lectura de 24 fragmentos, la recuperación y las regresiones de contenido terminaron.
Se reforzaron los prompts y se añadieron comprobaciones conservadoras tras detectar
errores semánticos en pasajes controlados.
El modelo ya se seleccionó en la configuración principal; con la estabilidad de
RAM confirmada se desactivó el reciclado intermedio y se mantiene la descarga al
finalizar cada tarea.

Ollama dedicado instalado como servicio de usuario en `127.0.0.1:11435`:
`paper-radar-ollama.service`, complemento `paper-radar.service.d/ollama.conf`.
No modifica el servicio de sistema. Ajustes anteriores respaldados en
`data/settings-before-qwen-20261006T005300Z.json`.

### Qwen: lectura de 24 fragmentos sin recargas

Artefactos: `/tmp/opencode/radar-memory-jxsixqo5/`. Mismo PDF, temperatura 0,1,
contexto 4096, `think: false`, `presence_penalty: 0`, sin caché histórica ni
checkpoints opcionales. Un único PID de runner en las 24 solicitudes.

- RSS inicial tras fragmento 1: **3,584 GiB**.
- RSS final y pico muestreado: **3,611 GiB**.
- Crecimiento: **27,79 MiB**; se estabilizó en los últimos fragmentos.
- Tiempo: **697,89 s** (11 min 38 s).
- 24 resultados persistidos; cero reintentos, cero errores de esquema o truncación.
- 77 hechos generados, 62 con cita/página coincidente, 59 únicos exactos.
- 15 hechos rechazados por la comprobación literal. No equivale a medir veracidad.

Los fragmentos 12–18 contienen referencias bibliográficas y devolvieron `facts=[]`;
21–24 son principalmente figuras/leyendas y también devolvieron notas vacías.
La estabilidad se observó tanto en fragmentos con texto denso (hasta 1948 tokens de
entrada) y generación extensa como en solicitudes breves. No se debe extrapolar
la duración a 24 fragmentos todos igualmente densos.

La penalización 0 permitió recuperar cinco notas en la portada donde el ensayo
anterior devolvió cero; no implica que esas cinco sean todas útiles. La inspección
detectó una clasificación incorrecta: una nota sobre prácticas de verano se
etiquetó como `author_limitations`, y otra lista de modelos se etiquetó como
`results`. Las citas son reales, pero esas categorías no representan el significado
científico de la información. También persisten duplicados y traducciones torpes.
Es necesaria revisión humana; no se certifica el informe como revisión científica.

### Primera validación de contenido y recuperación

Artefactos: `/tmp/opencode/radar-model-mv8fpfld/`. Endpoint dedicado de producción,
`scripts/check-model.py`, prompt técnico v2.

- Los casos de cifras y cautelas conservaron 120 tareas, 72% frente a 68% y el
  carácter preliminar; el de competitividad no inventó una expansión de XYZ ni
  convirtió “competitive” en superioridad universal.
- Ante la instrucción maliciosa devolvió notas vacías y no reportó el 99,9%
  solicitado por el texto. También perdió el dato benigno de 40 tareas: abstención
  conservadora, no prueba de inmunidad general frente a inyección.
- Referencias sin resultados propios: notas vacías.
- **Fallo semántico:** incluyó “Smith reporta 95%” como `author_limitations` pese
  a ser un resultado ajeno. La cita coincide pero la nota no pertenece a esa sección.
- Tres resúmenes reales guardados mediante `Engine.process_job`, todos `done` y
  descargando el modelo al terminar, 21–25 s por resumen con carga.
- **Fallo de alcance en un resumen:** conservó las cifras de marcas de agua pero
  omitió las hipótesis de simetría e independencia de detectores de la garantía
  teórica, además del carácter preliminar de la evaluación de imágenes.
- Recuperación real de las 24 notas v2: informe de 62 hechos guardado, tarea `done`,
  cobertura parcial explícita (24 de 45 fragmentos/páginas), sin nueva inferencia.

Estos hallazgos motivaron el prompt técnico **v3**: excluir resultados ajenos y
metadatos editoriales, definir mejor categorías y pedir hechos distintos. Se
eliminan duplicados exactos en la verificación, sin fusionar afirmaciones diferentes.
Las claves v2 se conservan pero no se reutilizan para nuevas tareas v3. También se
reforzó el boletín para conservar condiciones de garantías, alcance experimental,
resultados preliminares y atribución a autores. Se requiere nueva verificación;
no se consideran esos fallos resueltos solo por cambiar instrucciones.

La inspección inicial de v3 mostró que las instrucciones solas no bastaban: Qwen
todavía extrajo notas de autoría/prácticas en la portada. Se añadieron filtros
literales acotados para esos patrones editoriales y para citas exclusivamente de
“Prior work…” sin mención de resultados propios. La reaplicación al caso anterior
de Smith conserva las dos limitaciones propias y elimina el resultado ajeno.
Los filtros se prueban también con comparaciones que sí incluyen `our` para no
eliminarlas indiscriminadamente. Se reaplican al recuperar notas persistidas.
No detectan todos los errores de categoría, traducción, atribución o interpretación.

La evidencia resumida se copia además en `data/validation/qwen-20261006/` para no
depender exclusivamente de los artefactos temporales. Los JSON originales de cada
ensayo se conservan, incluidos los fallos; no se reescriben para aparentar mejoras.

### Regresión final y configuración seleccionada

- Prompt técnico v3: seis fragmentos, sin recargas, **3,464 → 3,538 GiB RSS**,
  artefactos `/tmp/opencode/radar-memory-wy940xwn/`. No errores ni reintentos.
  Estas notas se generaron antes de los filtros editoriales definitivos y se
  conservaron tal cual para auditarlas.
- Validación con código y filtros definitivos:
  `/tmp/opencode/radar-model-u9hzckiv/`. Los seis casos controlados preservaron
  cifras/cautelas, no inventaron superioridad ni expansión de XYZ, excluyeron el
  resultado de Smith y los metadatos editoriales. Referencias e instrucción
  maliciosa produjeron notas vacías. Persisten traducciones torpes y diferencias
  de categoría, por ejemplo competitividad etiquetada como evaluación.
- Recuperación del informe desde las seis notas v3, sin otra inferencia:
  **24 hechos** guardados, después de eliminar dos notas editoriales del conjunto
  previo de 26. Tarea `done`, cobertura parcial explícita. Las notas se depuran
  también en SQLite al recuperarlas.
- El nuevo prompt de boletín conservó las condiciones de la garantía, pero una
  ejecución volvió a convertir “competitive” en “supera” en el paper SNAP.
  Se añadió `validate_brief_fidelity`: cuando el abstract habla de competitividad
  sin palabras explícitas de superioridad, esa intensificación literal activa
  un reintento; si persiste, la tarea falla y no se guarda ese resumen.
  Es una heurística conservadora, susceptible a falsos positivos/negativos y no
  una prueba general de respaldo semántico.
- Prueba final de tres abstracts con esa comprobación:
  `/tmp/opencode/radar-model-ykt_wq_2/`. SNAP requirió **dos intentos** y terminó
  conservando “competitivo”. Los otros dos terminaron en el primero. El resumen
  de marcas de agua conserva supuestos de simetría/independencia, cuatro claves,
  cifras de texto y el carácter preliminar del estudio de imágenes.
  `stats.duration_ns` corresponde al último intento, no a la suma cuando hay retry.
- **78 pruebas automatizadas** y Ruff pasan; un aviso de deprecación de TestClient.
  Las unidades de usuario se validaron y la espera de disponibilidad de Ollama
  finalizó correctamente. No se verificó un reinicio físico del equipo.

Configuración efectiva, elegida por estabilidad y coste para este flujo:
`qwen3.5:4b`, contexto 4096, `think: false`, temperatura 0,1,
`presence_penalty: 0`, 1500 tokens de salida por fragmento y 1100 por boletín,
una tarea/modelo simultáneo, `LLAMA_ARG_CACHE_RAM=0`,
`LLAMA_ARG_CTX_CHECKPOINTS=0`, `recycle_every_chunks=0`,
`unload_after_paper=true`. Presupuesto habitual: 24 fragmentos de 4000 caracteres,
10 resúmenes y 3 informes diarios a las 07:00 America/Montevideo.
Instancia dedicada con `MemoryHigh=6G`, `MemoryMax=10G` y comprobación de API lista
antes de iniciar Paper Radar. El Ollama de sistema no se modificó.

Esta es la configuración **mejor validada en estos ensayos**, no una búsqueda
exhaustiva de hiperparámetros ni certificación científica de Qwen. La estabilidad
larga se probó en un PDF que incluye referencias y páginas principalmente gráficas;
no garantiza un techo universal ni el mismo tiempo para otros documentos.
