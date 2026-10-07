# Lecturas y notas de investigación

Proyecto personal local: Colibrí / arXiv → boletín y resúmenes por secciones mediante Ollama.
Primera versión para Linux, Python 3.11+ y un modelo local instalado. Por defecto:
`qwen3.5:4b`, categoría `cs.AI`, 07:00 `America/Montevideo` y hasta 10 resúmenes diarios.

## Ejecutar

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
ollama list
.venv/bin/python -m radar
```

Abre **http://127.0.0.1:8765**. Por defecto Ollama debe responder en `127.0.0.1:11434`.
`RADAR_OLLAMA_HOST` permite otro endpoint HTTP exclusivamente local, como
`http://127.0.0.1:11435` para la instancia dedicada descrita más abajo.
No se descargan modelos automáticamente ni se llama a proveedores de IA externos.
`localhost:8765` y `127.0.0.1:8765` sirven la misma aplicación. La página principal
no se almacena en caché y sus URLs de JavaScript/CSS incluyen una versión calculada
por contenido, para cargar las actualizaciones en ambos hosts. Una pestaña que ya
estaba abierta necesita una recarga completa: cambiar solo la ruta `#...` no vuelve
a cargar los archivos de interfaz.
El modelo debe estar instalado previamente. Puedes cambiarlo desde Configuración;
no se sobrescriben los informes generados con otro modelo.

El servicio consulta las citas pendientes al arrancar, incluso antes de las 07:00
si quedó pendiente la cita del día anterior. Varios días apagado producen una
consulta de recuperación, no una ejecución por cada día. Cada consulta vuelve a
mirar siete días anteriores al cursor y deduplica por identificador y versión.
El solapamiento es configurable (3–30 días): arXiv fecha envíos/actualizaciones antes
de su disponibilidad pública, por lo que un solo día no cubre bien los fines de semana.
La API se ordena por última actualización para detectar nuevas versiones de
papers antiguos; no se confunde publicación original con actualización.

La fecha de consulta se guarda solo tras persistir metadatos, selección y cola.
Las tareas de resumen son independientes: sobreviven a reinicios. Las secciones
ya confirmadas se reutilizan en reintentos con el mismo modelo, PDF y presupuesto.
Los errores de búsqueda se reintentan tras 30 minutos. Los errores de inferencia
quedan visibles para reintento manual, evitando bucles que saturen la CPU.

## Activación automática al iniciar sesión

Detén primero el servidor manual (Ctrl+C), y ejecuta:

```bash
bash scripts/install-service.sh
systemctl --user status paper-radar.service
journalctl --user -u paper-radar.service -n 50 --no-pager
```

El instalador crea un servicio **de usuario**, no modifica Ollama ni requiere sudo.
No sobrescribe una unidad existente. Corre aunque cierres la pestaña del navegador.
Se inicia al iniciar sesión; no se configura `linger` ni ejecución antes del login.
El equipo debe estar despierto para trabajar. Tras reanudarse comprueba lo pendiente.

Para detener/desactivar:

```bash
systemctl --user disable --now paper-radar.service
```

Un bloqueo de archivo evita dos coordinadores sobre la misma base de datos.
No utilizar múltiples workers ni `--reload` para la ejecución habitual.

## Control de memoria de Ollama

Cada solicitud científica usa solo el sistema y el fragmento actual, con contexto fijo de 4096
tokens: no se acumula la conversación del paper. Sin embargo, el runner puede retener
buffers/cachés o presentar crecimiento de memoria entre peticiones.

Por defecto se descarga el modelo de RAM mediante la API local (`keep_alive: 0`):

- Después de cada resumen, también ante errores/cancelaciones de inferencia.
- El reciclado cada **4 fragmentos nuevos** correspondía al análisis técnico retirado;
  se conserva como ajuste legado y no interviene en el resumen por secciones.

Configurable en **Modelo y presupuesto**: desmarca la liberación al terminar.
Recargar añade latencia y no garantiza un
máximo exacto de RAM durante una solicitud. No borra modelos ni documentos del disco.
La descarga afecta al modelo compartido en Ollama: si otras aplicaciones lo utilizan,
puede interferir con sus solicitudes. No se reinicia ni se detiene todo Ollama.

La caché de archivos de Linux puede permanecer después de descargar, pero es memoria
recuperable. En este equipo se observó un runner de Gemma de 11,6 GiB RSS con contexto
4096; al descargarlo desapareció y el uso total del equipo bajó de unos 15 a 4,2 GiB.
La investigación posterior de logs identificó una causa principal: esta versión del
runner conserva prompts y checkpoints en una caché de hasta **8 GiB**, aparte del
contexto activo. Llegó a guardar 8159,767 MiB antes de descargarlo. El reciclado
vacía esa caché; la solución de raíz sería desactivarla o limitarla en el runner.
No se modificó el servicio global de Ollama. Ver evidencia en `docs/validation.md`.

### Ollama exclusivo para Paper Radar

Para aislar la configuración y las descargas de otras aplicaciones:

```bash
bash scripts/install-ollama-service.sh
systemctl --user restart paper-radar.service
```

Instala `paper-radar-ollama.service` en el usuario, en `127.0.0.1:11435`, con
`LLAMA_ARG_CACHE_RAM=0`, `LLAMA_ARG_CTX_CHECKPOINTS=0`, un modelo y una solicitud
simultáneos, y modo sin proveedores cloud. Usa los modelos instalados en
`/usr/share/ollama/.ollama/models`; admite otra ruta mediante `OLLAMA_MODELS_DIR`.
Requiere `qwen3.5:4b` instalado y el servicio Paper Radar ya existente. Rechaza
sobrescribir unidades/complementos existentes. No cambia el servicio de sistema,
no copia ni descarga pesos y no requiere sudo.

El complemento `paper-radar.service.d/ollama.conf` dirige Paper Radar a ese endpoint
y establece su dependencia del servicio dedicado. Sus límites de cgroup son
`MemoryHigh=6G` (presión/reclamación) y `MemoryMax=10G` (límite duro: el kernel puede
terminar la inferencia si se alcanza). No equivalen a un consumo esperado ni
evitan por sí solos el swap. Una tarea fallida conserva las notas confirmadas.

El cliente solicita `think: false`, contexto 4096, temperatura 0,1 y
`presence_penalty: 0`: se prioriza extracción estructurada sin penalizar la
repetición necesaria para copiar citas. No se usa el contexto máximo del modelo.
El reciclado intermedio y la descarga al terminar siguen siendo ajustes de Paper
Radar, independientes de las opciones de caché del runner.

En este equipo quedó seleccionado `qwen3.5:4b`, **reciclado intermedio 0** y
**descarga al finalizar activada**, tras probar 24 fragmentos con RAM del runner
3,584 → 3,611 GiB sin recargas. El valor predeterminado de código sigue siendo 4
para instalaciones que usen el Ollama compartido sin controlar su caché. La
configuración efectiva de la interfaz se persiste en SQLite.

```bash
systemctl --user status paper-radar-ollama.service
journalctl --user -u paper-radar-ollama.service -n 80 --no-pager
```

**Importante:** si otra aplicación carga un modelo en el Ollama de sistema a la vez,
habrá dos runners y se sumará su consumo. La instancia dedicada aísla el control de
memoria; no desactiva ni limita aplicaciones ajenas a Paper Radar.

## Interfaz

- **Boletín diario:** últimas publicaciones seleccionadas y resúmenes del abstract.
- **Biblioteca:** todos los metadatos encontrados, filtros por fuente e interés, favoritos, leído/no leído.
- **Ficha:** un único resumen, abstract original, secciones principales, apoyos y citas.
  **Ver PDF** también está disponible para Colibrí: resuelve el archivo ORIGINAL/primario
  al pulsar el botón y guarda el enlace sin descargar el contenido para resolverlo.
  Si no hay un único PDF identificable o el repositorio restringe el acceso, se indica
  el problema y se mantiene el enlace a la ficha original; no se eluden permisos.
- **Actividad:** búsquedas, cola, errores y reintentos. Muestra como máximo 10 tareas,
  priorizando las que están en curso o en cola; el historial completo se conserva en disco.
  Cada tarea pendiente tiene **Cancelar**, tanto en Actividad como en su ficha.
- **Configuración:** paneles separados para Colibrí y arXiv, preferencias, modelo, horario y cupos.

El estado de procesamiento aparece al pie de la barra lateral izquierda, con el título
del documento y un círculo que avanza por secciones confirmadas. Durante descarga,
extracción o resumen sin porcentaje medible, el círculo indica actividad sin inventar
un porcentaje. Cancelar una tarea no borra resultados previos ni notas ya confirmadas;
  permanece cancelada tras reiniciar y puede reintentarse explícitamente.

### Ficha: un único resumen automático

La ficha no tiene pestañas ni análisis técnico. **Resumen** presenta en orden:
por qué puede interesarte, abstract original, secciones principales (incluida la
conclusión cuando se puede localizar) y organizaciones con apoyo o financiación
explícitos. Las citas se pueden desplegar dentro de cada sección.

Cada documento seleccionado para el boletín encola una única tarea `summary` que
evalúa afinidad y prepara automáticamente las secciones y apoyos del PDF. El resultado
del abstract se guarda antes de leer el PDF, para mostrarlo y reutilizarlo si esta etapa
falla. Abrir una ficha no encola nada: los documentos del archivo pueden solicitar
**Generar resumen**; un trabajo incompleto admite **Reintentar resumen**. Se guardan
las secciones confirmadas y se conserva cualquier resultado previo.
Se intenta usar el índice del PDF; sin índice se detectan encabezados de forma
conservadora. Se omiten bibliografía, listas editoriales y anexos posteriores a una
conclusión del índice. Se muestrea el inicio/final de secciones dentro del límite de
100 páginas y 300 000 caracteres extraídos, reservando páginas finales y de capítulos
en PDFs extensos. Cada llamada usa hasta 4000 caracteres y hasta 650 tokens de salida.

No se promete cubrir toda sección, hallar todos los capítulos ni detectar siempre la
conclusión de una tesis mal extraída. La cobertura y las citas se muestran; los vacíos
no se rellenan con el abstract. Las organizaciones necesitan nombre y declaración de
apoyo explícitos en una cita. Una afiliación no es patrocinio; no encontrar apoyo en
los extractos no prueba que no exista. Los resúmenes conservan el idioma del PDF.

No se generan análisis técnicos, ni automáticamente ni mediante la API antigua
(responde 410). Los informes y notas existentes se conservan en disco y en las
exportaciones; sus tareas pendientes se retiran. Las tareas pendientes antiguas
`brief`/`overview` pasan a un solo resumen sin reactivar cancelaciones explícitas.
**Pausar resúmenes** detiene el inicio de nuevas inferencias, no las búsquedas ni
una tarea ya en curso; esta última puede cancelarse individualmente.
Al actualizar, solo se completan los artículos visibles del boletín vigente según
los cupos actuales, no se procesa automáticamente todo el archivo histórico.

### Biblioteca por boletín

En Biblioteca, elige **Artículos por boletín**, selecciona cualquiera de los días
guardados o usa **Boletín anterior / siguiente**. Las fechas agrupan todas las
búsquedas del mismo día local y no duplican un documento seleccionado varias veces.
Solo se listan días con artículos realmente guardados en un boletín. Se pueden
combinar fecha, fuente, búsqueda y marca de interés; el archivo conserva la selección
original, sin recortarla por los cupos actuales. `#library/2026-10-06` permite enlazar
directamente un día. Se muestran los resultados actuales de sus artículos, no una
instantánea histórica de cada regeneración.

En esta vista, **Eliminar boletín completo** borra todas las pertenencias del día
seleccionado, aunque haya filtros activos. Solo aparece en Biblioteca y pide
confirmación. Los documentos, resúmenes, PDFs, marcas y tareas siguen conservados;
el historial de consultas y los contadores de red no se borran. El boletín eliminado
no se vuelve a crear mediante búsquedas automáticas o manuales ese mismo día.

En la ficha, **Eliminar de este boletín** actúa sobre el día desde el que se abrió el
artículo; si se abre sin ese contexto, utiliza su boletín más reciente. La confirmación
indica la fecha. Para actuar sobre otro día, abre el artículo desde ese día en Biblioteca.
No hay selector de boletín ni texto explicativo de marcas en la ficha.
Lo quita de todas las búsquedas agrupadas de ese día, no de otros
boletines ni de la biblioteca. También pide confirmación; no equivale a **No me interesa**
ni cancela la tarea de resumen. La plaza eliminada sigue contando en el cupo del día,
para evitar reemplazos automáticos al repetir una búsqueda.

Las eliminaciones son persistentes y usan las fechas locales configuradas. El boletín
de inicio muestra las pertenencias restantes sin hacer aparecer otros artículos que
estuvieran ocultos por los cupos actuales. Una regeneración explícita puede reconstruir
el día desde el catálogo local, reutilizando resúmenes y conservando cancelaciones;
no implica volver a consultar fuentes ni regenerar textos ya guardados.

### Marcas personales y reparto diario

**Me interesa** y **No me interesa** mantienen el documento visible en el boletín y
la biblioteca con su marca. **Quitar marca** borra solo esa marca. Las marcas no se
envían al modelo, no modifican búsquedas, no
cancelan tareas ya iniciadas y no rellenan el cupo con documentos nuevos.

Reparto inicial recomendado: hasta **8 resúmenes de Colibrí + 2 de arXiv**.
Al simplificar el flujo se conservó la configuración guardada por el usuario:
**6 de Colibrí + 2 de arXiv**, sin análisis técnicos. Los límites se respetan también al
repetir búsquedas manuales. Son máximos: si no hay suficientes novedades pertinentes,
se muestran menos documentos, sin transferir cupos de una fuente a la otra.
Las cuotas reservadas a Colibrí se editan dentro del total diario de resúmenes;
el resto corresponde a arXiv. El código mantiene Colibrí desactivado por defecto para
no empezar a consultar una fuente nueva en instalaciones existentes sin consentimiento.

### Colibrí: comunidades y tipos de documento

Conector público de https://www.colibri.udelar.edu.uy/, basado en la API REST de DSpace.
Alcance inicial: **Facultad de Ingeniería e Instituto de Computación**. Fing incluye
InCo y el conector evita esa consulta redundante. La selección se puede ampliar con
**Explorar comunidades de Colibrí**, añadir comunidades/colecciones por nombre y guardar;
también se puede editar su lista de UUID. El catálogo se consulta solo a petición de
la persona y se guarda un día en disco.

Colibrí tiene sus propios términos, exclusiones, texto de intereses y tipos de documento.
Tipos vacíos significa todos; por ejemplo: Artículo, Tesis de grado, Tesis de maestría,
Tesis de doctorado, Ponencia o Preprint. Los términos se comparan con título, abstract
y materias, después de descubrir dentro de las comunidades elegidas. No se usan
categorías de arXiv ni se mezclan las preferencias entre fuentes.

Las novedades se detectan por **fecha de depósito**, no por año de publicación. Un
trabajo de 2021 puede ingresar hoy. Se deduplican por UUID; en esta versión el conector
no detecta ediciones posteriores del mismo registro ni deduplica por DOI entre fuentes.
Cambiar filtros reinicia solo el cursor de esa fuente, sin borrar datos ni eludir pausas.

Los registros sin abstract quedan en la biblioteca sin resumen automático. Si la fuente
no indica PDF disponible, se conserva el resumen del abstract y se explica la falta
de secciones y apoyos. Al descargar se usa un único PDF del paquete ORIGINAL o su archivo
principal señalado por DSpace; si hay ambigüedad o restricciones, queda un error visible.
No se inicia sesión, no se eluden embargos y no hay OCR. PDFs extensos conservan el
alcance parcial del presupuesto de extracción y resumen.

### Notificaciones de escritorio

Activadas por defecto: un aviso al completar el resumen único, con el título del paper.
No se avisa por cada sección, por errores ni por artículos completados antes de activar
la función. Los resultados guardados no se vuelven a procesar para producir avisos.

Funcionan aunque la pestaña esté cerrada, mediante `notify-send` y el bus de la sesión
gráfica de Linux. Requieren `libnotify-bin` (ya instalado en este equipo). El modo
**No molestar** y las preferencias del escritorio pueden ocultar el aviso o enviarlo
solo al centro de notificaciones; no hace falta permiso de notificaciones del navegador.
Puedes desactivarlas o pulsar **Probar notificación** en Configuración. Los avisos
muestran títulos, por lo que conviene apagarlos si compartes la pantalla.

Se envían después de guardar el resultado. Un fallo al notificar no afecta al resumen;
queda registrado en los logs y en `last_notification` del estado del servicio. No hay
reintentos ni entrega garantizada si se cierra la sesión justo después de guardar.

Selección inicial por palabras preferidas y actualidad, no clasificación exhaustiva
de toda la literatura. Después el modelo asigna afinidad 1–5 y prepara secciones y apoyos
para todos los seleccionados. Los restantes documentos se pueden resumir bajo demanda.
Una nueva versión tiene ficha independiente.
Si el modelo produce un boletín demasiado largo, se acorta a un final de oración
dentro de 150 palabras (o se indica con puntos suspensivos si no hay un final), y
la ficha muestra que se acortó. El abstract original siempre está disponible.

`cs.AI` no cubre toda la IA: se pueden agregar `cs.LG`, `cs.CL`, `cs.CV`, `cs.RO`,
`cs.NE` y `stat.ML`. Está disponible el catálogo local de arXiv, incluyendo matemáticas,
física, biología cuantitativa, estadística, economía y otras áreas. Cambiar categorías
o filtros de consulta reinicia el periodo de descubrimiento, sin borrar artículos ni resúmenes.

### Idioma de los documentos

Los nuevos resúmenes y notas conservan el idioma del texto: inglés para documentos en
inglés y español para documentos en español. La interfaz sigue en español. La indicación
de idioma usa una heurística local; los textos ambiguos se dejan al criterio del modelo,
sin una llamada adicional para detectar idioma. Se valida de forma conservadora que el
modelo no cambie entre inglés y español, con un único reintento.

Los resultados anteriores no se traducen ni regeneran automáticamente. Los reintentos
completan los bloques que faltan y reutilizan secciones confirmadas. Las notas técnicas
antiguas se conservan, pero no se producen nuevos informes técnicos.

### Intereses en lenguaje natural

1. En el panel de **Colibrí** o **arXiv** de Configuración, describe tus intereses
   positivos y relaciones entre temas, sin elegir una categoría única (hasta 4000 caracteres).
2. Pulsa **Proponer términos de Colibrí** o **Proponer filtros** para arXiv. El modelo
   desglosa los intereses y devuelve términos y advertencias. Para arXiv también propone categorías;
   para Colibrí las comunidades se eligen explícitamente, no las inventa el modelo.
3. Revisa y edita los campos; pulsa **Guardar configuración** para aplicar la propuesta.

La propuesta no modifica los filtros activos. Se guarda en disco y se reutiliza si
se vuelve a pedir para el mismo texto/modelo/versión. Las búsquedas diarias no envían
el texto de intereses al modelo: usan las categorías y palabras ya guardadas.
Los resúmenes siguen usando el modelo para leer cada paper y estimar su afinidad.

Las instrucciones, temas, explicación y advertencias de arXiv están en **inglés**;
los de Colibrí, en **español**. Los fragmentos `source_text` se copian del texto
original, conservando su idioma. **Ver desglose de intereses positivos** permite
revisar qué fragmento respalda cada tema y sus términos/categorías.

Las propuestas no tienen un campo de exclusiones: el esquema rechaza que el modelo
lo añada, también dentro de un tema. Si se desean exclusiones, se editan por separado
en los campos **(manual)**. Proponer no modifica esos campos ni activa automáticamente
el requisito de coincidencia de palabras; ambas preferencias se conservan.

Con **Exigir alguna coincidencia de término** activado, arXiv recibe una consulta de
categorías y frases en título/abstract; basta una categoría y un término (OR dentro
de cada grupo, AND entre grupos). Sin esa opción, se consulta por categorías y los
términos solo priorizan el boletín. Las exclusiones afectan a la selección del boletín,
no borran metadatos ni filtran los trabajos que pidas procesar manualmente.
La comparación local es literal, ignora mayúsculas y exige límites de palabra;
no hace búsqueda semántica ni expansión diaria de sinónimos. Revisa los filtros:
una frase demasiado específica puede dejar fuera trabajos pertinentes.

No hay un tope numérico fijo de categorías, intereses o términos; las categorías
deben existir en el catálogo, y las frases deben ser cortas y literales. Más variantes
pueden ampliar cobertura, pero términos genéricos o repetidos aumentan ruido.
La compilación puntual usa contexto 8192 y hasta 4096 tokens de salida; no cambia el contexto 4096 de los
papers. No se solapa con otra inferencia del coordinador y libera el modelo al terminar.
La versión `positive-interests-v6` no reutiliza propuestas anteriores con exclusiones
o códigos de categoría colocados como palabras clave.
Se mantienen límites técnicos de texto, peticiones y extracción: no equivalen a un
tope de temas. Ninguna fuente garantiza cubrir todos los intereses.

La validación estructural no garantiza el significado de las categorías. La prueba
real con `qwen3.5:4b` mejoró idiomas y términos positivos, pero todavía encontró
asignaciones temáticas incorrectas y cobertura parcial. Los resultados y una
referencia revisada, no aplicada y separada de Ollama, se describen en
[`docs/positive-interests-validation.md`](docs/positive-interests-validation.md).

## Límites y seguridad

- Solo HTTPS a hosts oficiales fijados en código; cada conector restringe sus propias
  redirecciones y reconstruye las URLs de PDF, sin seguir destinos del modelo.
- Sin navegador automatizado, shell del agente, ejecución de adjuntos ni herramientas para el modelo.
- Peticiones sin proxies heredados del entorno; TLS se valida normalmente.
- Interfaz y cliente Ollama únicamente por loopback. Comprobación de Host y Origin,
  cabecera propia en mutaciones y CSP; sin scripts/CDN externos ni renderizado HTML del modelo.
- PDF máximo **100 MB por defecto**, configurable entre 1 y 250 MB en
  **Modelo y presupuesto → Tamaño máximo de PDF (MB)**. Los errores de tamaño
  declarado indican el peso y el límite; si no se anuncia tamaño, se detiene la
  descarga al superarlo. Cambiar el límite no reencola por sí solo tareas fallidas:
  usa **Reintentar**. Extracción en proceso separado: 30 s de CPU, 45 s de pared,
  1,5 GB de espacio de direcciones, hasta 100 páginas y 300 000 caracteres.
  **Esto limita recursos, no es un sandbox completo contra vulnerabilidades del parser.**
- Inferencia científica secuencial, contexto 4096, hasta 24 fragmentos de 4000 caracteres por defecto.
  Informe técnico extractivo agrupado por sección, sin una segunda síntesis libre:
  la prueba real con Gemma añadió detalles no respaldados en esa síntesis, por lo que
  se eliminó esa etapa. No se meten todas las notas en un único contexto.
- Cobertura explícita: abstract, texto parcial o texto extraído completo. Texto completo
  no significa comprensión completa de gráficos, tablas, fórmulas ni material suplementario.
- Cada nota técnica requiere una cita comprobada literalmente en el fragmento/página
  correspondiente; las notas sin coincidencia se descartan. Sin citas verificables no
  se genera una síntesis factual. El formato se valida y se permite un reintento acotado.
  Esa comprobación
  **no verifica la veracidad ni el respaldo de todas las afirmaciones generadas**.
- No verifica peer review, novedad global ni reproducibilidad. No hay OCR todavía.
- arXiv usa pasadas de hasta **10 peticiones de 100 metadatos**, repartidas por turnos
  entre grupos de hasta ocho categorías y los grupos necesarios de términos. No se
  eliminan categorías ni términos por esa división. Cada página válida se guarda
  en una transacción junto con su punto de continuación. Al agotar una pasada, los
  resultados quedan disponibles en Biblioteca y pueden completar el cupo del boletín;
  el resto continúa tras 30 minutos con el programador activo, o en la siguiente
  búsqueda manual. No se vuelve al offset cero. Los topes no limitan el tamaño total
  del recorrido: más de 5000 registros no invalida los avances.
- El cursor de recorrido completo solo avanza cuando terminan todos los grupos.
  Actividad distingue avances parciales de recorridos completos. Cambiar filtros
  invalida el punto de continuación, no borra documentos ni elude pausas de la fuente.
  Se conserva el filtrado local por actualización para incluir revisiones recientes
  de envíos antiguos. Validación: [`docs/arxiv-resume-validation.md`](docs/arxiv-resume-validation.md).
- Pausa mínima 3,1 s entre peticiones de una fuente, también entre redirecciones
  y con búsqueda/descarga concurrentes. Colibrí mantiene su recorrido independiente.
- Las peticiones externas de producción quedan registradas en `source_requests`
  (incluye intentos fallidos, catálogo y PDFs). Actividad muestra el contador diario UTC
  por fuente; no reconstruye tráfico anterior a la instalación de ese contador.
- Ante 429/503 se detiene el intento y se respeta `Retry-After`, con espera creciente
  de 30 minutos hasta 24 horas ante fallos consecutivos. La pausa persiste tras reiniciar
  y cambiar filtros no la borra. Una fuente fallida no bloquea la otra. Los errores de
  otro tipo usan espera de 30 minutos. Esto reduce riesgo, no garantiza ausencia de bloqueo.
- Sin autenticación multiusuario: no exponer a una LAN ni Internet mediante un proxy.
- Los modelos con etiquetas cloud o metadatos remotos se rechazan. Mantén Ollama configurado
  para uso local; no crear etiquetas locales que oculten modelos remotos.

## Datos

`data/radar.sqlite3` conserva configuración, metadatos, boletines y cola; `data/documents/`
conserva PDFs analizados. Se crean con permisos de usuario. No hay borrado ni límite
automático de disco en esta versión: revisa el tamaño periódicamente. Para otra ruta,
define `RADAR_DATA_DIR` antes de iniciar. Haz backups con el servicio detenido.

La primera prueba de rendimiento debe hacerse con un paper: los análisis completos
pueden tardar bastante en CPU y dependen de la extracción. No se garantiza aceleración AMD.

## Pruebas

Prueba opt-in de Colibrí, sin usar Ollama ni modificar producción:

```bash
.venv/bin/python scripts/check-colibri.py        # metadatos y selección
.venv/bin/python scripts/check-colibri.py --pdf  # además, un PDF público de hasta 100 MB
```

Ver resultados y límites en [`docs/colibri.md`](docs/colibri.md).

Prueba opt-in de idiomas y propuesta de intereses (no aplica sus filtros de ejemplo):

```bash
RADAR_OLLAMA_HOST=http://127.0.0.1:11435 .venv/bin/python scripts/check-design.py
```

Requiere el servicio sin inferencias activas y el modelo local instalado; consume CPU
y consulta arXiv. Conserva respuestas y peticiones en `/tmp/opencode/reading-design-*/`.

El mapa de código, los prompts, el flujo HTTP y la persistencia se explican en
[`docs/inference-flow.md`](docs/inference-flow.md). Incluye una comparación real
opt-in de memoria con runners temporales, sin modificar el servicio global:

```bash
.venv/bin/python scripts/check-memory.py --model qwen3.5:4b --paper-id 2 --chunks 6 --briefs
```

Lectura larga sin caché ni checkpoints (sin recargas intermedias):

```bash
.venv/bin/python scripts/check-memory.py --model qwen3.5:4b --chunks 24 --modes no_cache_no_checkpoints
```

Prueba de resúmenes, pasajes controlados y recuperación desde esas notas, usando
el endpoint dedicado cuando no haya otra inferencia:

```bash
RADAR_OLLAMA_HOST=http://127.0.0.1:11435 .venv/bin/python scripts/check-model.py --notes /tmp/opencode/radar-memory-XXXX/no_cache_no_checkpoints
```

Las notas de recuperación deben corresponder a la versión vigente del prompt.
Para generar y validar en una sola ejecución:

```bash
RADAR_OLLAMA_HOST=http://127.0.0.1:11435 .venv/bin/python scripts/check-memory.py --model qwen3.5:4b --chunks 6 --modes no_cache_no_checkpoints --validate
```

Los casos controlados requieren revisar el significado de las respuestas, no solo
sus citas coincidentes. Ninguna prueba automática certifica calidad científica.

```bash
.venv/bin/python -m pytest
```

Las pruebas unitarias usan fuentes y respuestas de Ollama simuladas, sin red ni descarga
de modelos. Las pruebas reales de conectividad/inferencia se documentan aparte.

## Próxima fuente: Colibrí

El candidato investigado es https://www.colibri.udelar.edu.uy/, repositorio institucional
de Udelar sobre **DSpace 9.1**, organizado por comunidades y colecciones. Se verificó
acceso público a la raíz REST `/server/api` y al listado de comunidades
`/server/api/core/communities/search/top`. Falta confirmar que es el sitio deseado,
las colecciones concretas y el filtrado incremental de documentos permitido.
No está habilitado ni se hace scraping automáticamente. `radar/sources.py` define un
protocolo de descubrimiento/documento y un registro de conectores extensible.
Para un repositorio hay que distinguir fecha de depósito de fecha de publicación,
y manejar tipos como tesis, artículos, informes y restricciones de acceso.
