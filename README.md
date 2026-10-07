# boletinDiario

Proyecto personal local: Colibrí / arXiv → boletín y resúmenes por secciones mediante Ollama.
Primera versión para Linux, Python 3.11+ y un modelo local instalado. Por defecto:
`qwen3.5:4b`, categoría `cs.AI`, 07:00 `America/Montevideo` y hasta 10 resúmenes diarios.

Consulta metadatos públicos, selecciona documentos según tus filtros y prepara un
resumen del abstract, de las secciones principales del PDF y de los apoyos explícitos.
La IA se ejecuta localmente; la instalación y las consultas a las fuentes requieren
Internet. Los resúmenes tienen cobertura parcial: no sustituyen la lectura del documento
ni una revisión científica. La aplicación es personal, sin autenticación multiusuario,
y no debe exponerse a una LAN ni a Internet.

## Índice

- [Instalación y primera ejecución](#instalación-y-primera-ejecución)
- [Uso cotidiano](#uso-cotidiano)
- [Configuración](#configuración)
- [Servicios y resolución de problemas](#servicios-y-resolución-de-problemas)
- [Datos y respaldos](#datos-y-respaldos)
- [Límites y seguridad](#límites-y-seguridad)
- [Mapa del proyecto](#mapa-del-proyecto)
- [Pruebas](#pruebas)
- [Documentación técnica y validaciones](#documentación-técnica-y-validaciones)

## Instalación y primera ejecución

Este procedimiento es para **Linux y una instalación nueva**. Usa el Ollama
habitual en **11434** y la aplicación en **8765**. Si ya tienes servicios instalados,
consulta después [Instalación existente](#instalación-existente).
No ejecutes más de una instancia de la aplicación sobre la misma biblioteca.

### 1. Instalar los requisitos

Necesitas **Git, Python 3.11 o posterior, venv, pip, curl y Ollama**, además de
Internet para instalar dependencias y consultar las fuentes.

En Ubuntu/Debian puedes instalar las herramientas básicas así:

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip curl
python3 --version
```

Comprueba que la versión de Python sea al menos 3.11. En otras distribuciones usa
su gestor de paquetes. Las notificaciones de escritorio son opcionales; en
Ubuntu/Debian puedes habilitar su herramienta con `sudo apt install libnotify-bin`.

Si no tienes Ollama, instálalo siguiendo la [guía oficial para Linux](https://docs.ollama.com/linux).
Comprueba que esté disponible:

```bash
ollama --version
```

### 2. Descargar el repositorio

```bash
git clone https://github.com/00raffi/boletinDiario.git
cd boletinDiario
```

Si ya lo descargaste, entra en esa carpeta en lugar de clonarlo otra vez. Todos
los comandos siguientes se ejecutan allí: debes ver `pyproject.toml`, `radar/` y
`scripts/`. No uses la carpeta padre.

### 3. Crear el entorno e instalar el proyecto

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m boletinDiario --help
```

No hace falta activar el entorno con `source`: los comandos utilizan su Python
explícitamente. **No avances si pip termina con un error.** Si falta `ensurepip`
o `venv`, revisa el paquete `python3-venv`. No reutilices un entorno virtual movido
desde otra carpeta: créalo dentro de este repositorio.

### 4. Comprobar que Ollama está funcionando

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama list
```

Si el comando muestra los modelos, el servidor ya funciona: **no inicies otro**.
Si indica que no puede conectarse, abre una segunda terminal y ejecuta:

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

Deja esa segunda terminal abierta y vuelve a ejecutar `ollama list` en la primera.
También puedes usar tu servicio existente de Ollama en vez del servidor manual.
`ollama list` **no inicia** Ollama; solo consulta el servidor.

### 5. Comprobar el modelo local

El modelo predeterminado es **`qwen3.5:4b`**. Si figura en la lista anterior, no tienes
que descargarlo de nuevo. Si no está y quieres instalarlo, este paso es una
**descarga manual y opcional**, que debes ejecutar tú:

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3.5:4b
```

Si prefieres usar otro modelo que ya tienes, omite la descarga y selecciónalo
en **Configuración → Modelo local de Ollama → Guardar configuración** después
del arranque. El proyecto no descarga modelos automáticamente ni utiliza
proveedores externos de IA. Debes disponer de RAM suficiente para el modelo elegido.

### 6. Arrancar la aplicación

Desde la primera terminal, dentro de `boletinDiario`:

```bash
RADAR_OLLAMA_HOST=http://127.0.0.1:11434 \
RADAR_DATA_DIR="$PWD/data" \
.venv/bin/python -m boletinDiario
```

Deja esa terminal abierta. Debe aparecer:

```text
Uvicorn running on http://127.0.0.1:8765
```

### 7. Abrir y configurar la aplicación

Abre **http://localhost:8765** o **http://127.0.0.1:8765**. Para comprobar el servidor
desde otra terminal:

```bash
curl --fail http://127.0.0.1:8765/api/status
```

En **Configuración**, revisa el modelo, horario, fuentes, intereses y cupos; pulsa
**Guardar configuración** para aplicar tus cambios. Colibrí está desactivado en
una biblioteca nueva: actívalo y elige sus comunidades si quieres usarlo.
La programación está activada por defecto y puede recuperar una búsqueda pendiente
al arrancar, antes de que edites la configuración. Los errores de inferencia quedan
en Actividad para reintento manual; cambiar modelo no los reactiva por sí solo.

### 8. Arrancar de nuevo en otro momento

No repitas el clonado, la creación del entorno ni la instalación. Con Ollama
funcionando, entra en el repositorio y repite únicamente el comando del paso 6.
Si quieres que la aplicación siga funcionando al cerrar la terminal y se inicie al
entrar en tu sesión, sigue [Activación automática al iniciar sesión](#activación-automática-al-iniciar-sesión).

## Uso cotidiano

### Recorrido inicial

1. En **Configuración**, selecciona un modelo instalado, las fuentes y tus filtros;
   revisa los cupos y pulsa **Guardar configuración**. Las propuestas de intereses
   deben revisarse y guardarse: pedir una propuesta no aplica sus filtros.
2. En **Boletín diario**, pulsa **Buscar novedades** para consultar las fuentes
   habilitadas sin esperar al horario automático. La búsqueda respeta los cupos del
   día y las pausas de cada fuente; no garantiza novedades en cada ejecución.
3. Consulta **Actividad** y el indicador lateral para seguir los documentos en cola
   o en procesamiento. Encontrar metadatos y terminar un resumen son etapas distintas.
4. Abre **Ver resumen** en un artículo del boletín. El resumen del abstract puede
   estar disponible antes que las secciones del PDF; revisa la cobertura y despliega
   las citas. **Ver PDF** abre el documento oficial cuando está disponible.
5. Para un documento de **Biblioteca** que todavía no tenga resumen, abre su ficha y
   pulsa **Generar resumen**. Si una tarea falló, corrige la causa y usa **Reintentar**
   en Actividad o **Reintentar resumen** en la ficha. Abrir una ficha no inicia tareas.
6. Usa las marcas de interés, favorito y leído/no leído para organizar la biblioteca.
   **Exportar Markdown**, en la ficha, exporta los resultados guardados del artículo;
   no ejecuta una nueva inferencia.

Para empezar, prueba con un documento: el resumen por secciones puede tardar bastante
en CPU y depende de la extracción del PDF. No se garantiza aceleración AMD.

### Pantallas y estado

- **Boletín diario:** últimas publicaciones seleccionadas y resúmenes del abstract.
- **Biblioteca:** todos los metadatos encontrados, filtros por fuente e interés, favoritos, leído/no leído.
- **Ficha:** un único resumen, abstract original, secciones principales, apoyos y citas.
  **Ver PDF** también está disponible para Colibrí: resuelve el archivo ORIGINAL/primario
  al pulsar el botón y guarda el enlace sin descargar el contenido para resolverlo.
  Si no hay un único PDF identificable o el repositorio restringe el acceso, se indica
  el problema y se mantiene el enlace a la ficha original; no se eluden permisos.
- **Actividad:** artículos en procesamiento y procesados, errores y reintentos, sin
  listados de búsquedas ni estadísticas de consultas por fuente. Muestra como máximo
  tantos artículos como el cupo diario configurado del boletín (por ejemplo, 15),
  priorizando los que están en curso o en cola y después los más recientes.
  El historial completo de tareas y búsquedas se conserva en disco.
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
en PDFs extensos. Por defecto se resumen hasta 24 secciones, con extractos de hasta
4000 caracteres por sección; la búsqueda de apoyos usa extractos adicionales acotados.

No se promete cubrir toda sección, hallar todos los capítulos ni detectar siempre la
conclusión de una tesis mal extraída. La cobertura y las citas se muestran; los vacíos
no se rellenan con el abstract. Las organizaciones necesitan nombre y declaración de
apoyo explícitos en una cita. Una afiliación no es patrocinio; no encontrar apoyo en
los extractos no prueba que no exista. Los resúmenes conservan el idioma del PDF.

**Pausar resúmenes** detiene el inicio de nuevas inferencias, no las búsquedas ni
una tarea ya en curso; esta última puede cancelarse individualmente.

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

### Marcas personales

**Me interesa** y **No me interesa** mantienen el documento visible en el boletín y
la biblioteca con su marca. **Quitar marca** borra solo esa marca. Las marcas no se
envían al modelo, no modifican búsquedas, no cancelan tareas ya iniciadas y no rellenan
el cupo con documentos nuevos.

### Idioma de los documentos

Los nuevos resúmenes conservan el idioma del texto: inglés para documentos en inglés
y español para documentos en español. La indicación de idioma usa una heurística local;
los textos ambiguos se dejan al criterio del modelo, sin una llamada adicional para
detectar idioma. Se valida de forma conservadora que el modelo no cambie entre inglés
y español, con un único reintento.

Los resultados anteriores no se traducen ni regeneran automáticamente. Los reintentos
completan los bloques que faltan y reutilizan secciones confirmadas.

## Configuración

### Opciones de arranque

Estas opciones se definen antes de iniciar el proceso. Las preferencias de fuentes,
modelo, horario y presupuesto se editan en la interfaz y se guardan en SQLite.

| Opción | Valor predeterminado | Uso |
| --- | --- | --- |
| `RADAR_DATA_DIR` | `data/` en la raíz del proyecto | Carpeta de biblioteca, PDFs, preferencias, resultados y cola. Usa una ruta absoluta para evitar ambigüedades. |
| `RADAR_OLLAMA_HOST` | `http://127.0.0.1:11434` | Endpoint HTTP de Ollama, exclusivamente local, sin ruta ni credenciales. El servicio dedicado utiliza `http://127.0.0.1:11435`. |
| `--port` | `8765` | Puerto de la interfaz web; la escucha sigue limitada a `127.0.0.1`. |

Ejemplo de arranque manual con otro puerto:

```bash
RADAR_DATA_DIR="$PWD/data" \
RADAR_OLLAMA_HOST=http://127.0.0.1:11434 \
.venv/bin/python -m boletinDiario --port 8766
```

En ese caso, abre **http://127.0.0.1:8766** y usa ese puerto también en las
comprobaciones con `curl` o `ss`. Cambiar estas opciones en una terminal no actualiza
un servicio systemd ya instalado: este usa su propia unidad y sus complementos.

`OLLAMA_HOST` configura los comandos de Ollama; `RADAR_OLLAMA_HOST` configura el
cliente de la aplicación. Deben apuntar al mismo servidor al comprobar sus modelos.

### Valores iniciales y reparto diario

Estos valores se aplican a una **biblioteca nueva**, no sustituyen las preferencias
guardadas de una instalación existente:

| Preferencia | Valor inicial |
| --- | --- |
| Modelo | `qwen3.5:4b` |
| Fuentes | arXiv activado; Colibrí desactivado |
| Categorías de arXiv | `cs.AI` |
| Búsquedas automáticas | Activadas, a las 07:00 de `America/Montevideo` |
| Periodo inicial / solapamiento | 7 días / 7 días |
| Resúmenes automáticos totales por día | Hasta 10 |
| Reserva de Colibrí al habilitarlo | 8 de los 10; los 2 restantes corresponden a arXiv |
| Máximo de secciones por documento | 24 |
| Tamaño máximo de PDF | 100 MB |
| Liberar el modelo al terminar | Activado |
| Notificaciones de escritorio | Activadas, si el sistema permite enviarlas |

Con Colibrí desactivado, el cupo total corresponde a arXiv. Para usar ambas fuentes,
un ejemplo de reparto es **8 Colibrí + 2 arXiv**; puedes modificarlo en Configuración.
Los límites se respetan también al repetir búsquedas manuales. Son máximos: si no hay
suficientes novedades pertinentes, se muestran menos documentos, sin transferir cupos
de una fuente a la otra. Las cuotas de Colibrí se reservan dentro del total diario;
el resto corresponde a arXiv si está habilitado.

### arXiv: categorías y selección

`cs.AI` no cubre toda la IA: se pueden agregar `cs.LG`, `cs.CL`, `cs.CV`, `cs.RO`,
`cs.NE` y `stat.ML`. Está disponible el catálogo local de arXiv, incluyendo matemáticas,
física, biología cuantitativa, estadística, economía y otras áreas. Cambiar categorías
o filtros de consulta reinicia el periodo de descubrimiento de esa fuente, sin borrar
artículos ni resúmenes.

La selección inicial usa palabras preferidas y actualidad, no una clasificación
exhaustiva de toda la literatura. Después el modelo asigna afinidad 1–5 y prepara
secciones y apoyos para los seleccionados. Los restantes documentos se pueden resumir
bajo demanda. En arXiv, una nueva versión tiene ficha independiente.
Si el resumen del abstract supera 150 palabras, se acorta a un final de oración
dentro de ese límite (o se indica con puntos suspensivos si no hay un final), y
la ficha muestra que se acortó. El abstract original siempre está disponible.

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
gráfica de Linux. En Ubuntu/Debian instala la herramienta con
`sudo apt install libnotify-bin`. El modo **No molestar** y las preferencias del
escritorio pueden ocultar el aviso o enviarlo
solo al centro de notificaciones; no hace falta permiso de notificaciones del navegador.
Puedes desactivarlas o pulsar **Probar notificación** en Configuración. Los avisos
muestran títulos, por lo que conviene apagarlos si compartes la pantalla.

Se envían después de guardar el resultado. Un fallo al notificar no afecta al resumen;
queda registrado en los logs y en `last_notification` del estado del servicio. No hay
reintentos ni entrega garantizada si se cierra la sesión justo después de guardar.

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

Con **Exigir coincidencia de término en la consulta a arXiv** activado, se consulta
por categorías y frases en título/abstract; basta una categoría y un término (OR dentro
de cada grupo, AND entre grupos). Sin esa opción, se consulta por categorías y los
términos solo priorizan el boletín. Las exclusiones afectan a la selección del boletín,
no borran metadatos ni filtran los trabajos que pidas procesar manualmente.
La comparación local es literal, ignora mayúsculas y exige límites de palabra;
no hace búsqueda semántica ni expansión diaria de sinónimos. Revisa los filtros:
una frase demasiado específica puede dejar fuera trabajos pertinentes.

No hay un tope numérico fijo de categorías, intereses o términos; las categorías
deben existir en el catálogo, y las frases deben ser cortas y literales. Más variantes
pueden ampliar cobertura, pero términos genéricos o repetidos aumentan ruido.
La compilación puntual usa contexto 8192 y hasta 4096 tokens de salida; no cambia el
contexto 4096 de los documentos. No se solapa con otra inferencia del coordinador y
libera el modelo al terminar. Las propuestas antiguas incompatibles no se reutilizan.
Se mantienen límites técnicos de texto, peticiones y extracción: no equivalen a un
tope de temas. Ninguna fuente garantiza cubrir todos los intereses.

La validación estructural no garantiza el significado de las categorías. La prueba
real con `qwen3.5:4b` mejoró idiomas y términos positivos, pero todavía encontró
asignaciones temáticas incorrectas y cobertura parcial. Los resultados y una
referencia revisada, no aplicada y separada de Ollama, se describen en
[`docs/positive-interests-validation.md`](docs/positive-interests-validation.md).

### Control de memoria de Ollama

Cada solicitud de resumen usa instrucciones y extractos acotados, con contexto de
4096 tokens: no se acumula una conversación del documento. El proceso que ejecuta
el modelo puede retener buffers o cachés entre peticiones.

Por defecto, la aplicación solicita descargar el modelo de RAM mediante la API local
(`keep_alive: 0`) al terminar cada resumen, también ante errores o cancelaciones de
inferencia. Se puede desactivar en **Modelo y presupuesto → Liberar el modelo de RAM
al terminar cada resumen**. Recargar añade latencia; liberar al terminar no garantiza
un máximo exacto de RAM durante una solicitud y no borra modelos ni PDFs del disco.

La descarga afecta al modelo compartido en Ollama y puede interferir con otras
aplicaciones que lo utilicen. No reinicia ni detiene todo Ollama. Para aislarlo, puedes
usar el [servicio dedicado](#ollama-exclusivo-para-la-aplicación). La caché de archivos
de Linux puede permanecer después de descargar el modelo, pero es memoria recuperable.
Las mediciones específicas y el historial de ajustes están en
[`docs/validation.md`](docs/validation.md) y [`docs/inference-flow.md`](docs/inference-flow.md).
El reciclado intermedio por fragmentos es un ajuste legado del análisis técnico
retirado; no interviene en el resumen por secciones actual.

## Servicios y resolución de problemas

### Detener la aplicación

**Si la ejecutaste manualmente**, pulsa **Ctrl+C** en la terminal de la aplicación.
Si necesitas detenerla desde otra terminal, identifica el PID que escucha en 8765:

```bash
ss -ltnp 'sport = :8765'
```

Solo si corresponde a tu proceso **manual** de la aplicación, envíale SIGINT,
sustituyendo `PID` por el número mostrado (no escribas `PID` literalmente):

```bash
kill -INT PID
```

**Si la ejecutaste como servicio de usuario**, detenla con:

```bash
systemctl --user stop boletinDiario.service
```

Para detenerla **y desactivar** el inicio automático:

```bash
systemctl --user disable --now boletinDiario.service
```

Detener la aplicación no borra PDFs, preferencias ni resultados, y no detiene Ollama.
El avance confirmado se conserva; un trabajo interrumpido por el apagado puede
recuperarse al volver a iniciar. Para cancelar una tarea sin que se retome, usa
**Cancelar** en la interfaz antes de detener la aplicación. No borres
`data/service.lock`: el proceso libera el bloqueo al terminar.

### Activación automática al iniciar sesión

Requiere una sesión de usuario con systemd. Detén primero el servidor manual
(Ctrl+C) y ejecuta:

```bash
bash scripts/install-service.sh
systemctl --user status boletinDiario.service
journalctl --user -u boletinDiario.service -n 50 --no-pager
```

El instalador crea un servicio **de usuario**, no modifica Ollama ni requiere sudo.
No sobrescribe una unidad existente. La aplicación sigue trabajando aunque cierres
la pestaña del navegador. Se inicia al iniciar sesión; no se configura `linger`
ni ejecución antes del login. El equipo debe estar despierto para trabajar.

El servicio instalado usa la carpeta `data/` del proyecto y el Ollama habitual en
11434, salvo que su unidad o sus complementos indiquen otros valores. No hereda las
opciones usadas en un arranque manual. Un bloqueo de archivo evita dos coordinadores
sobre la misma base de datos: no utilices múltiples workers ni `--reload` para la
ejecución habitual.

### Ollama exclusivo para la aplicación

Esta opción aísla la configuración y las descargas de RAM de otras aplicaciones.
Requiere el servicio de la aplicación ya instalado y `qwen3.5:4b` disponible en la
carpeta de modelos elegida. Cuando no haya tareas activas, ejecuta:

```bash
bash scripts/install-ollama-service.sh
systemctl --user restart boletinDiario.service
```

Instala `boletinDiario-ollama.service` en el usuario, en `127.0.0.1:11435`, con
`LLAMA_ARG_CACHE_RAM=0`, `LLAMA_ARG_CTX_CHECKPOINTS=0`, un modelo y una solicitud
simultáneos, y modo sin proveedores cloud. Usa los modelos instalados en
`/usr/share/ollama/.ollama/models`; admite otra ruta mediante `OLLAMA_MODELS_DIR`
al ejecutar el instalador. Rechaza sobrescribir unidades o complementos existentes.
No cambia el servicio de sistema, no copia ni descarga pesos y no requiere sudo.

El complemento `boletinDiario.service.d/ollama.conf` dirige la aplicación a ese endpoint
y establece su dependencia del servicio dedicado. Los límites de memoria del servicio
de Ollama son `MemoryHigh=6G` (presión/reclamación) y `MemoryMax=10G` (límite duro:
el kernel puede terminar la inferencia si se alcanza). No equivalen a un consumo
esperado ni evitan por sí solos el swap. Una tarea fallida conserva las secciones
confirmadas para reintento.

Para comprobarlo:

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama list
systemctl --user status boletinDiario-ollama.service
journalctl --user -u boletinDiario-ollama.service -n 80 --no-pager
```

**Importante:** si otra aplicación carga un modelo en el Ollama de sistema a la vez,
habrá dos procesos de ejecución y se sumará su consumo. La instancia dedicada no
desactiva ni limita otras aplicaciones. La liberación de RAM al terminar cada resumen
sigue siendo una preferencia de boletinDiario, independiente de la caché del servidor.

### Instalación existente

Antes de actualizar, detén la aplicación y haz un respaldo de los datos. Después de
obtener la nueva versión del código, reinstala el proyecto desde su raíz:

```bash
.venv/bin/python -m pip install -e .
```

El arranque público es `.venv/bin/python -m boletinDiario` y el comando instalado es
`.venv/bin/boletinDiario`. Se conservan el módulo interno `radar` y la biblioteca
`radar.sqlite3` para reutilizar los datos existentes. Las preferencias guardadas no
se reemplazan por los valores iniciales de una biblioteca nueva.

Los nombres `boletinDiario.service` y `boletinDiario-ollama.service` corresponden a
unidades instaladas con esta versión. Las unidades anteriores no se renombran ni
detienen automáticamente. Comprueba sus nombres reales:

```bash
systemctl --user list-unit-files --type=service
```

Si tu unidad tiene otro nombre, úsalo para detenerla y revisar su configuración.
No actives una unidad nueva mientras otra instancia esté usando la misma biblioteca
o puerto. Los instaladores no sobrescriben unidades existentes; conserva sus archivos
y complementos como respaldo antes de editarlos.

Si vas a arrancar manualmente, detén primero el servicio. Si usas Ollama dedicado,
comprueba los modelos en 11435 y ejecuta:

```bash
RADAR_OLLAMA_HOST=http://127.0.0.1:11435 \
RADAR_DATA_DIR="$PWD/data" \
.venv/bin/python -m boletinDiario
```

Después de actualizar, reinicia la aplicación y recarga la pestaña del navegador;
cambiar solo la ruta `#...` no carga los archivos nuevos de la interfaz.

**Compatibilidad con versiones anteriores:** no se generan análisis técnicos;
su API antigua responde 410. Los informes y notas existentes se conservan en disco
y en las exportaciones, pero sus tareas pendientes se retiran. Las tareas pendientes
antiguas `brief`/`overview` pasan a un solo resumen sin reactivar cancelaciones explícitas.
Solo se completan automáticamente los artículos visibles del boletín vigente según
los cupos actuales, no todo el archivo histórico. Ver
[`docs/summary-only-validation.md`](docs/summary-only-validation.md).

### Horario, recuperación y reintentos

Con las búsquedas automáticas activadas, la aplicación comprueba las citas pendientes
al arrancar y tras reanudarse el equipo. Puede consultar antes de las 07:00 si quedó
pendiente la cita del día anterior. Varios días apagado producen una consulta de
recuperación, no una ejecución por cada día.

Cada consulta vuelve a mirar siete días anteriores al cursor por defecto y deduplica
por identificador y versión. El solapamiento es configurable (3–30 días): arXiv fecha
envíos y actualizaciones antes de su disponibilidad pública, por lo que un solo día
no cubre bien los fines de semana. Se consulta por última actualización para detectar
nuevas versiones de documentos antiguos.

La fecha de consulta se guarda tras persistir metadatos, selección y cola. Las tareas
de resumen son independientes y sobreviven a reinicios. Las secciones confirmadas se
reutilizan en reintentos con el mismo modelo, PDF y presupuesto. Los errores de búsqueda
se reintentan tras 30 minutos, salvo las pausas específicas de la fuente descritas en
[Límites y seguridad](#límites-y-seguridad). Los errores de inferencia requieren
reintento manual para evitar bucles que saturen la CPU.

### Errores comunes al arrancar

| Error o síntoma | Qué comprobar |
| --- | --- |
| `No module named boletinDiario` | Estás dentro de `boletinDiario` y ejecutaste `.venv/bin/python -m pip install -e .` con el mismo entorno. |
| `No module named uvicorn` u otra dependencia | La instalación de pip terminó correctamente; no estás usando otro Python o un entorno movido. |
| `Ya hay una instancia de la aplicación usando esta base de datos` | Detén el servicio anterior o la otra terminal; no elimines el archivo de bloqueo. |
| `Address already in use` / puerto 8765 ocupado | No arranques otra instancia. Comprueba `systemctl --user status boletinDiario.service` y `ss -ltnp 'sport = :8765'`. |
| `unable to open database file` | Revisa `RADAR_DATA_DIR` y los permisos de la carpeta de datos; si usas un servicio, comprueba también su configuración. |
| Ollama no responde / `Connection refused` | Comprueba el servidor y puerto correctos: 11434 habitual o 11435 dedicado. `ollama list` no inicia Ollama. |
| Modelo no encontrado | El nombre guardado debe aparecer en el `ollama list` del endpoint elegido; selecciona uno instalado y guarda. |
| El instalador dice que la unidad ya existe | No la borres ni repitas la instalación: inspecciona la unidad existente y sus complementos. |

Para diagnosticar el servicio:

```bash
systemctl --user cat boletinDiario.service
journalctl --user -u boletinDiario.service -n 80 --no-pager
```

Si el problema continúa, conserva el **traceback completo** de la terminal, no solo
la última línea. El traceback del arranque manual no se guarda automáticamente en
el journal del servicio. Revisa si contiene rutas o información personal antes de compartirlo.

## Datos y respaldos

`data/radar.sqlite3` conserva configuración, metadatos, boletines, resultados y cola;
`data/documents/` conserva PDFs analizados. Se crean con permisos de usuario. Para
otra ubicación, define `RADAR_DATA_DIR` antes de iniciar.

`data/` está excluido de Git: un clon nuevo **no trae tus datos personales** y crea
una biblioteca nueva. No borres la carpeta, no cambies sus permisos a `777` ni la
reemplaces para resolver un error de arranque. No hay borrado ni límite automático
de disco en esta versión: revisa el tamaño periódicamente.

Para hacer un respaldo consistente, detén la aplicación y copia la carpeta de datos
completa a otra ubicación; después vuelve a iniciarla. Conserva tanto la base SQLite
como los PDFs. Si configuraste `RADAR_DATA_DIR`, respalda esa carpeta, no necesariamente
el `data/` del repositorio. Al restaurar, mantén la aplicación detenida y conserva una
copia de los datos actuales antes de reemplazarlos.

## Límites y seguridad

- Solo HTTPS a hosts oficiales fijados en código; cada conector restringe sus propias
  redirecciones y reconstruye las URLs de PDF, sin seguir destinos del modelo.
- El modelo no dispone de herramientas, navegador ni shell; no se ejecutan adjuntos.
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
- Inferencia de resúmenes secuencial, contexto 4096, hasta 24 secciones por defecto,
  con extractos de hasta 4000 caracteres por sección. La extracción de apoyos usa un
  presupuesto adicional acotado. No se envía todo el PDF en una única conversación.
- Cobertura explícita de páginas consultadas y secciones detectadas/resumidas. Leer
  extractos no equivale a cubrir todo el texto ni a comprender gráficos, tablas,
  fórmulas o material suplementario.
- Cada resumen de sección no vacío requiere referencias a extractos proporcionados.
  El modelo selecciona identificadores y Python copia las citas originales con su
  página; también se comprueba su coincidencia literal. Los apoyos requieren una cita
  con el nombre y una declaración explícita de apoyo o financiación. El formato se
  valida y se permite un reintento acotado. Estas comprobaciones
  **no verifican la veracidad ni el respaldo de todas las afirmaciones generadas**.
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
  El estado interno distingue avances parciales de recorridos completos. Cambiar filtros
  invalida el punto de continuación, no borra documentos ni elude pausas de la fuente.
  Se conserva el filtrado local por actualización para incluir revisiones recientes
  de envíos antiguos. Validación: [`docs/arxiv-resume-validation.md`](docs/arxiv-resume-validation.md).
- Pausa mínima 3,1 s entre peticiones de una fuente, también entre redirecciones
  y con búsqueda/descarga concurrentes. Colibrí mantiene su recorrido independiente.
- Las peticiones externas de producción quedan registradas en `source_requests`
  (incluye intentos fallidos, catálogo y PDFs). El estado interno conserva el contador
  diario UTC por fuente; no reconstruye tráfico anterior a la instalación de ese contador.
- Ante 429/503 se detiene el intento y se respeta `Retry-After`, con espera creciente
  de 30 minutos hasta 24 horas ante fallos consecutivos. La pausa persiste tras reiniciar
  y cambiar filtros no la borra. Una fuente fallida no bloquea la otra. Los errores de
  otro tipo usan espera de 30 minutos. Esto reduce riesgo, no garantiza ausencia de bloqueo.
- Sin autenticación multiusuario: no exponer a una LAN ni Internet mediante un proxy.
- Los modelos con etiquetas cloud o metadatos remotos se rechazan. Mantén Ollama configurado
  para uso local; no crear etiquetas locales que oculten modelos remotos.

## Mapa del proyecto

| Ruta | Función |
| --- | --- |
| `boletinDiario/` | Punto de entrada público: `python -m boletinDiario`. |
| `radar/` | Implementación interna: API, planificación, fuentes, inferencia y persistencia. |
| `radar/static/` | Interfaz web: HTML, JavaScript y CSS. |
| `scripts/` | Instaladores de servicios y comprobaciones manuales. |
| `tests/` | Pruebas automatizadas con fuentes y respuestas simuladas. |
| `docs/` | Documentación técnica, límites y evidencias de validación. |
| `data/` | Biblioteca y archivos locales, excluidos de Git; puede cambiarse con `RADAR_DATA_DIR`. |
| `pyproject.toml` | Metadatos, dependencias, empaquetado y configuración de pytest. |

El nombre público es **boletinDiario**. Se mantienen `radar/`, las variables `RADAR_*`
y `radar.sqlite3` como nombres internos para conservar compatibilidad. El mapa de
módulos, los prompts, el flujo HTTP y la persistencia se amplían en
[`docs/inference-flow.md`](docs/inference-flow.md), que distingue el flujo actual
de la referencia histórica del análisis técnico retirado.

## Pruebas

### Pruebas automatizadas sin red

Instala las dependencias opcionales de pruebas y ejecuta:

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
```

Las pruebas usan fuentes y respuestas de Ollama simuladas, sin red ni descarga de
modelos. No requieren tener Ollama funcionando.

### Comprobaciones reales opcionales

Estas comprobaciones se ejecutan explícitamente: pueden consultar fuentes, descargar
un PDF o consumir CPU mediante Ollama. No son necesarias para el uso cotidiano.

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

Requiere la aplicación en 8765 sin inferencias activas y el modelo `qwen3.5:4b`
instalado en el endpoint elegido; consume CPU y consulta arXiv. Conserva respuestas
y peticiones en `/tmp/opencode/reading-design-*/`. Incluye comprobaciones de notas
del módulo técnico legado, no una validación completa del resumen por secciones actual.

El ejemplo de intereses usa el Ollama dedicado en 11435; si utilizas el habitual,
cambia el endpoint a 11434. No lo ejecutes en paralelo con otras inferencias.
Los experimentos de memoria y validación del modelo, incluidos los del flujo técnico
legado, se explican en [`docs/inference-flow.md`](docs/inference-flow.md).
Los casos controlados requieren revisar el significado de las respuestas, no solo
sus citas coincidentes. Ninguna prueba automática certifica calidad científica.

## Documentación técnica y validaciones

Los documentos de validación registran pruebas concretas y sus límites; las mediciones
de un equipo o modelo no son requisitos ni garantías para otras instalaciones.

| Documento | Contenido |
| --- | --- |
| [`docs/inference-flow.md`](docs/inference-flow.md) | Mapa de código, prompts, comunicación, persistencia y experimentos de memoria; separa el flujo actual del legado. |
| [`docs/summary-only-validation.md`](docs/summary-only-validation.md) | Resumen único, retirada del análisis técnico y conservación de datos anteriores. |
| [`docs/sections-validation.md`](docs/sections-validation.md) | Resúmenes por secciones, citas, apoyos y límites de cobertura. |
| [`docs/colibri.md`](docs/colibri.md) | Conector de Colibrí y comprobaciones de metadatos y PDF. |
| [`docs/positive-interests-validation.md`](docs/positive-interests-validation.md) | Propuestas de intereses, idiomas y errores temáticos observados. |
| [`docs/arxiv-resume-validation.md`](docs/arxiv-resume-validation.md) | Continuación de búsquedas de arXiv y persistencia de avances. |
| [`docs/bulletin-deletion-validation.md`](docs/bulletin-deletion-validation.md) | Archivo por boletín y eliminación de pertenencias sin borrar documentos. |
| [`docs/pdf-limit-validation.md`](docs/pdf-limit-validation.md) | Límites de descarga de PDF y reintentos. |
| [`docs/validation.md`](docs/validation.md) | Historial de pruebas y mediciones de memoria de instalaciones concretas. |
