# Prompts, comunicación, persistencia y memoria

**Actualización 2026-10-06 — resumen único:** el flujo actual usa tareas `summary`:
`Ollama.brief` (si falta) → guardar `papers.brief` → `article_overview` (si falta) →
guardar `papers.overview` y `jobs.done` → un aviso y descarga del modelo.
`pause_summaries` pausa nuevas inferencias, no la búsqueda ni la tarea ya iniciada.
No hay análisis técnicos en el planificador ni en la interfaz; la API `jobs/analysis`
responde 410. Los informes y notas existentes permanecen guardados y exportables.
Las explicaciones de `detailed_analysis` y reciclado de fragmentos que siguen son
referencia histórica del módulo legado, no el flujo activo. Ver también
`docs/summary-only-validation.md`.

## No es un agente autónomo

El proyecto es un coordinador Python con una cola persistente. Decide qué documento
descargar, qué fragmento enviar, cómo validar y dónde guardar resultados. El modelo
no tiene herramientas, no consulta SQLite, no navega y no elige el siguiente paper.
Ollama sirve inferencia; `llama-server` es su proceso de ejecución del modelo.

## Mapa del código

| Archivo / símbolo | Responsabilidad |
| --- | --- |
| `radar/app.py`: `create_app`, `queue`, `cancel` | API de la interfaz, crear/cancelar tareas |
| `radar/engine.py`: `Engine.loop` | Planificador, selección de una tarea pendiente cada vez |
| `radar/engine.py`: `Engine.process_job` | Estado, llamada a resumen/análisis, transacción final, aviso, descarga |
| `radar/llm.py`: `SYSTEM` | Prompt de sistema común, reglas de fidelidad y seguridad |
| `radar/llm.py`: `Ollama.brief` | Prompt para resumen de título y abstract |
| `radar/llm.py`: `Ollama.generate` | Petición HTTP, opciones, esquema JSON, validación y un reintento |
| `radar/llm.py`: `HOST`, `Ollama.__init__` | Endpoint local configurable por `RADAR_OLLAMA_HOST` |
| `radar/llm.py`: `Brief`, `Evidence`, `ChunkNotes` | Esquemas y límites de la respuesta |
| `radar/llm.py`: `validate_brief_fidelity` | Guardia conservadora contra intensificar competitividad a superioridad |
| `radar/llm.py`: `Ollama.unload` | Descarga mediante `POST /api/generate`, `keep_alive: 0` |
| `radar/analysis.py`: `extract_pdf`, `make_chunks` | Extracción en subproceso y fragmentación |
| `radar/analysis.py`: `fragment_prompt` | Prompt literal de extracción técnica por fragmento |
| `radar/analysis.py`: `detailed_analysis` | Reanudación de notas, inferencia por fragmento y reciclado |
| `radar/analysis.py`: `verify_evidence` | Comprobar página/cita, quitar duplicados y ruido literal inequívoco |
| `radar/analysis.py`: `build_report` | Agrupar notas por secciones sin otra llamada al modelo |
| `radar/db.py`: `Database.connect`, `set_meta`, `queue`, `recover` | SQLite, commits y recuperación |
| `radar/config.py`: `Settings` | Modelo, presupuesto y frecuencia de descarga |
| `radar/catalog.py`: `CATEGORIES` | Catálogo local de arXiv y alias canónicos |
| `radar/languages.py`: `text_language` | Indicación heurística en/es sin inferencia adicional |
| `radar/interests.py`: `propose_interests`, `InterestProposal` | Compilación puntual de texto libre a filtros revisables |
| `radar/interests.py`: `propose_colibri_interests`, `TermProposal` | Términos independientes para comunidades elegidas de Colibrí |
| `radar/colibri.py`: `ColibriSource` | Descubrimiento por depósito, catálogo y PDF público ORIGINAL |
| `radar/sources.py`: `RequestSource.get` | Serialización por fuente, contador persistente, Retry-After y pausas |
| `radar/engine.py`: `Engine.compile_interests` | Reserva de inferencia, caché persistente de propuestas y descarga |
| `radar/pdf_worker.py` | Límites de extracción; no contiene inferencia |

## Flujo anterior (referencia histórica)

```text
Interfaz o planificación diaria
  → fila en jobs (queued)
  → Engine.loop elige una tarea
  → Engine.process_job marca running
     ├─ brief: título + abstract → Ollama.brief → Ollama.generate
     └─ analysis:
         PDF en data/documents/<id>.pdf
         → extraer texto y dividir en fragmentos de hasta 4000 caracteres
         → leer notas confirmadas en SQLite
         → para cada fragmento pendiente:
             construir fragment_prompt
             → Ollama.generate → HTTP local /api/chat → runner
             ← JSON del modelo
             validar esquema y citas
             guardar notas + COMMIT
              descargar runner cada N fragmentos nuevos, si N > 0 y quedan más
         → build_report (Python, sin inferencia)
  → transacción: guardar papers.brief/analysis + marcar jobs.done + COMMIT
  → notificación opcional
  → descargar modelo al terminar, si está habilitado
```

**Una solicitud por fragmento, no por cada cuatro.** Un fallo de validación del
formato permite un segundo intento. El cuarto fragmento no envía las notas de los
tres anteriores. Al reanudar, el contador de reciclado empieza en cero para esa
ejecución; no depende de que el índice absoluto sea múltiplo de cuatro.

## Qué se envía a Ollama

El cuerpo HTTP lo construye `Ollama.generate`:

```python
{
    "model": model,
    "stream": False,
    "think": False,
    "format": schema.model_json_schema(),
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt + correction},
    ],
    "options": {
        "temperature": 0.1,
        "presence_penalty": 0,
        "num_ctx": 4096,
        "num_predict": output_tokens,
    },
    "keep_alive": "5m",
}
```

Por defecto se usa `http://127.0.0.1:11434/api/chat`; la instalación dedicada usa
`http://127.0.0.1:11435/api/chat`. El plazo HTTP de inferencia es
600 segundos. `num_predict` es 1100 para boletines y 1500 para notas técnicas.
`keep_alive: "5m"` retiene el runner tras una solicitud; el coordinador puede
descargarlo antes mediante `keep_alive: 0`.

En el reintento `correction` contiene errores del esquema o de la guardia de fidelidad, no una conversación
completa ni la respuesta anterior. El historial tiene siempre esos dos mensajes.
Las citas no coincidentes se descartan después de generar; eso no dispara otro
intento de inferencia. También se eliminan duplicados exactos y patrones literales
inequívocos de ruido editorial (“Equal contribution”, “Work done during…”) o
resultados exclusivamente previos (“Prior work…”, sin mención `we`/`our`). Es un
filtro conservador y limitado, no un clasificador general de procedencia.
Coincidencia literal no equivale a validación científica.

El boletín pasa además por una comprobación literal de competitividad/superioridad
que puede activar el mismo reintento acotado. También se comprueba conservadoramente
que resumen, contribución y afinidad no cambien entre inglés y español. Las notas
técnicas comprueban el idioma de `claim`; `quote` conserva siempre el texto literal.
Si el segundo intento incumple, no
se guarda el resumen: la tarea queda en error. No es una evaluación científica
general. `validation_attempts` registra ambos tipos de validación; `format_attempts`
se conserva como campo compatible y también cuenta intentos totales.

Para ver el texto exacto, leer `SYSTEM`, `Ollama.brief` y `fragment_prompt`.
La prueba de memoria conserva además el JSON **real enviado**, incluido cualquier
reintento, en `<directorio de prueba>/<modo>/requests.json`.

## Estado persistido y recuperación

Base principal: `data/radar.sqlite3` (o la carpeta `RADAR_DATA_DIR`).

- `papers.brief`: resultado del resumen como JSON.
- `papers.analysis`: informe final, evidencia y cobertura como JSON.
- `jobs`: `kind`, `status`, `progress`, errores y fechas.
- `meta`: configuración, cursores y notas técnicas intermedias.

Las notas usan una clave:

```text
grounded-notes-v4:<paper_id>:<modelo>:<max_chunks>:<hash_del_pdf>
```

Su valor es una lista JSON de resultados por fragmento, incluidos aquellos con
`facts=[]`. Se guarda la lista y se confirma la transacción **en cada fragmento**.
Al recuperar notas se reaplican los filtros de validación y se persiste la lista
depurada; no se requiere generar de nuevo para eliminar esos casos conocidos.
`len(notes)` indica el siguiente índice pendiente. Al reiniciar no se necesita
ningún estado del runner para continuar. Cambiar modelo, PDF o presupuesto cambia
la clave y no reutiliza la lista anterior. Las notas v2/v3 se conservan pero no se
reutilizan tras el cambio de idioma del prompt v4. Cambios futuros del prompt deben
versionar también esta clave para no reutilizar notas incompatibles.

La aplicación mantiene copias temporales de texto/notas del paper activo y de los
datos que muestra la interfaz. No es memoria conversacional ni un almacenamiento
permanente de toda la biblioteca. Las conexiones SQLite se cierran tras cada
operación y confirman o revierten los cambios. Las tareas interrumpidas durante
el cierre del servicio vuelven a `queued`; las canceladas por el usuario quedan
`cancelled` para reintento manual.

Una eventual revisión por modelo sería otra etapa: leer notas seleccionadas desde
SQLite, construir un prompt acotado, generar y guardar un nuevo resultado. **No está
implementada ahora**: la síntesis libre se retiró por afirmaciones sin respaldo.
No hace falta agregar esta etapa para resolver el crecimiento de RAM del runner.

## Compilación puntual de intereses

`POST /api/interests/propose` envía el texto libre (hasta 4000 caracteres) y el catálogo
local al modelo guardado: contexto 8192, hasta 4096 tokens de salida. Es la única
excepción al contexto científico 4096; no mezcla intereses con fragmentos de papers.
La reserva `interest_task` impide iniciar otra inferencia del coordinador y la descarga
al finalizar libera el runner. El esquema limita los códigos a un enum del catálogo,
rechaza campos de exclusiones y valida los fragmentos originales que respaldan cada
interés, el idioma y la coherencia de los códigos de la explicación. No prueba
calidad semántica ni garantiza que estén todos los temas.

El resultado se persiste bajo `positive-interests-v6:<hash>` en `meta`, sin modificar
Settings. La persona revisa los campos y aplica con `PUT /api/settings`. Pedir la misma
propuesta reutiliza el resultado, incluso tras reiniciar. La búsqueda diaria lee solo
los filtros guardados: categorías OR, opcionalmente AND con términos OR en título/abstract.
No vuelve a enviar el texto libre al modelo. La selección local exige límites de palabra
y prioriza coincidencias; las exclusiones solo afectan al boletín.

El request indica `source=arxiv` o `source=colibri` (arXiv por defecto por compatibilidad).
La clave incorpora fuente; para Colibrí también incorpora las comunidades guardadas.
Su propuesta contiene intereses positivos desglosados, términos, explicación y
advertencias: no inventa comunidades ni usa categorías de arXiv. Ambas fuentes
conservan texto y filtros independientes. arXiv usa instrucciones y explicaciones
en inglés; Colibrí en español. Los fragmentos literales conservan el idioma original.
Python reúne y deduplica los términos/categorías de cada tema. No hay topes numéricos
fijos de intereses, categorías o términos, pero se conservan los límites técnicos
de contexto, salida y longitud de frases. Proponer no cambia las exclusiones manuales
ni activa la coincidencia obligatoria de términos.

## Boletín multifuente y marcas personales

Los runs guardan `bulletin_day`, `source_stats` y `detail_quotas`. Cada fuente tiene
`source:<nombre>` con cursor y estado; el arXiv antiguo se recupera de sus metadatos
legados. Colibrí no sobrescribe ese cursor. Se confirman cola y cursor en una transacción
por fuente. Un fallo de una fuente permite conservar la otra con estado `partial`.
El boletín reúne los runs del último día con entradas y respeta cuotas por fuente.
Las búsquedas repetidas no generan más resúmenes automáticos que el cupo diario.

`papers.interest` vale -1, 0 o 1; se actualiza por PATCH y el boletín mantiene las entradas
visibles con su marca. La biblioteca filtra `interested`, `not_interested` o `unrated`. El modelo no
recibe el campo: `Ollama.brief` serializa solo título/abstract y filtros guardados, y
`fragment_prompt` recibe título, idioma y fragmento. No se modifican criterios ni cola
por una marca, y no se rellenan puestos del boletín. La migración de SQLite es aditiva.

El archivo `/api/bulletins` enumera días con relaciones persistidas en `bulletin`,
agrupando todos sus runs y deduplicando paper_id. `/api/papers?bulletin_day=YYYY-MM-DD`
filtra por pertenencia al día y se combina con el resto de filtros; no aplica las
cuotas actuales a selecciones históricas. La biblioteca admite enlace `#library/<día>`.

## Resumen por secciones automático

`radar/overview.py` guarda en `papers.overview` secciones y apoyos, sin sobrescribir
`brief` ni `analysis`. Lo llama la única tarea `summary` después de guardar la afinidad
y el texto breve del abstract. Se encola para cada seleccionado del boletín, no por
abrir su ficha. En documentos del archivo puede solicitarse manualmente; los reintentos
reutilizan el trabajo confirmado. `brief` y `overview` son tipos legados: sus endpoints
encolan ahora `summary`, y las tareas pendientes se convierten al iniciar el servicio.

Se extrae PDF mediante el worker acotado, con preferencia por marcadores de capítulos;
sin ellos se buscan encabezados conservadores. Se consultan hasta 100 páginas, con
presupuesto de 300 000 caracteres, y extractos de inicio/final por sección. Se reservan
páginas finales y páginas de capítulos para no limitar las tesis extensas al comienzo.
No hay OCR ni garantía de identificar la conclusión o toda la estructura.

La caché `section-overview-v3:<paper>:<modelo>:<límite>:<hashPDF>` confirma cada sección.
El modelo devuelve un texto breve y hasta 3 identificadores de extractos. Python copia
sus citas del texto original: no le exige al modelo reproducir fórmulas y espacios PDF.
Un ID ajeno o resumen sin evidencia no es válido; se comprueba idioma. Los apoyos también
usan IDs, y su nombre y señal de financiación/apoyo deben aparecer en la cita. Afiliación
no equivale a patrocinio. El anclaje prueba procedencia textual, no precisión semántica.
Los límites de secciones reconocen líneas de título con espacios internos de tipografía
PDF (por ejemplo `C ONCLUSION`); no usan una simple mención de la palabra dentro de
un párrafo para fijar el comienzo. La conclusión se corta antes de la bibliografía.

Las solicitudes externas de producción se registran en `source_requests`. Cada conector
serializa y espacia sus peticiones y redirecciones. `network:<nombre>` conserva la pausa
por 429/503, respetando `Retry-After` y con espera exponencial de 30 minutos hasta 24 h.
La pausa no se borra al cambiar filtros y el coordinador no insiste cada cinco segundos
en una fuente pausada. El contador no reconstruye tráfico de herramientas/scripts previos.

`scripts/check-design.py` es una prueba real opt-in que conserva requests y responses,
incluyendo intentos rechazados, prueba idiomas en/es y consulta arXiv con filtros propuestos.
No aplica las preferencias de ejemplo a la biblioteca de producción.

## Tres memorias diferentes

1. Pesos, buffers y KV del contexto activo: necesarios durante inferencia.
2. Caché histórica de prompts/checkpoints del backend: reutilización opcional,
   independiente de que nuestra aplicación envíe o no un historial.
3. Resultados y estado del trabajo: SQLite y PDFs, persistentes en disco.

`--cache-ram 0` afecta al punto 2, no al 3 ni a toda la memoria del punto 1.
`--ctx-checkpoints 0` desactiva además los checkpoints internos del contexto.
Descargar el runner elimina ambos tipos de caché y los pesos residentes, a costa
de una recarga. Las opciones del runner no están expuestas por nuestra pantalla
de configuración ni se deben confundir con `recycle_every_chunks`.

## Comparación reproducible sin modificar el servicio global

```bash
.venv/bin/python scripts/check-memory.py --paper-id 2 --chunks 6
```

Requiere la biblioteca local y el PDF descargado, Ollama principal sin modelos
cargados y Paper Radar sin tareas/búsqueda en curso. No ejecutar otras inferencias
simultáneas. Es opt-in; tarda varios minutos y consume CPU.

La prueba inicia una instancia temporal en loopback con los modelos ya instalados
en `/usr/share/ollama/.ollama/models` (ruta específica de este equipo). No descarga
modelos, no actualiza la biblioteca y no cambia `/etc/systemd/system/ollama.service`.
Cada modo empieza con un servidor/runner nuevo y no recicla entre fragmentos:

1. `baseline`: caché predeterminada.
2. `no_prompt_cache`: `LLAMA_ARG_CACHE_RAM=0`.
3. `no_cache_no_checkpoints`: lo anterior + `LLAMA_ARG_CTX_CHECKPOINTS=0`.

Se utilizan los mismos prompts y cliente de producción. Los logs permiten comprobar
si Ollama transmite realmente las opciones al runner; no basta con definir las
variables. Al terminar cada modo se descarga el modelo y se detiene su servidor.

En `/tmp/opencode/radar-memory-*/` quedan:

- `input.json`: título y fragmentos usados.
- `comparison.json`: métricas y configuración observada por modo.
- `<modo>/requests.json`: cuerpos reales enviados a `/api/chat`.
- `<modo>/responses.json`: respuestas reales, antes del filtrado de citas.
- `<modo>/results.sqlite3`: estado y notas verificadas por fragmento, con commit.
- `<modo>/metrics.json`: tiempos, tokens, reintentos, RSS final y máximo muestreado.
- `<modo>/samples.json`: memoria del runner y servidor cada 0,5 segundos.
- `<modo>/ollama.log`, `cache-evidence.txt`: logs y evidencia de cachés/buffers.
- `<modo>/smaps_rollup`, `maps`: desglose del kernel cuando está disponible.

RSS se mide en KiB, distinto del tamaño del modelo de `ollama ps`. El pico es
muestreado: puede no capturar asignaciones muy breves. Los tiempos no son un
benchmark estadístico y desactivar cachés no garantiza respuestas idénticas.
Verificar citas sigue sin demostrar que la interpretación sea correcta.

### Resultado observado

La comparación del 2026-10-05 terminó: predeterminado **3,710 → 5,318 GiB**;
sin caché histórica **3,710 → 3,770 GiB**; sin caché ni checkpoints
**3,563 → 3,575 GiB**, en seis fragmentos sin recargas. Los logs verificaron que
las variables se transmitieron al runner. Ver la tabla y límites de interpretación
en [`validation.md`](validation.md). Estos ajustes aún no se aplicaron al servicio
global: los defaults de `Settings` no fueron modificados por la prueba.
