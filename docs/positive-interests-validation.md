# Intereses positivos por fuente — 2026-10-07

## Cambios

- `radar/interests.py` separa instrucciones de arXiv (inglés) y Colibrí (español).
  Ambos reciben un system prompt propio, sin el prompt de lectura científica.
- La salida contiene intereses positivos desglosados. Cada tema conserva un
  fragmento literal `source_text`, términos y, para arXiv, categorías.
- Python reúne y deduplica las listas. Los esquemas rechazan campos adicionales,
  incluidos `excluded_keywords`, tanto en la raíz como dentro de cada tema.
- Los códigos de arXiv están enumerados en el JSON Schema usado por Ollama.
- Se retiraron los topes de 24 categorías, 80 términos y 40 exclusiones guardadas.
  Permanecen el catálogo válido, la longitud de cada término y los límites técnicos
  de texto, contexto, salida y solicitudes. Esto no garantiza cobertura ilimitada.
- Proponer no modifica las exclusiones manuales ni activa el filtro obligatorio
  de palabras. La interfaz permite inspeccionar el desglose antes de guardar.
- `positive-interests-v6` invalida las propuestas anteriores sin borrarlas.

## Comprobaciones automatizadas y de interfaz

- 179 tests aprobados; Ruff aprobado.
- Pruebas con 35 categorías y 160 términos, sin truncar términos de las consultas.
- Tests del esquema enum, fragmentos originales, idiomas y rechazo de exclusiones.
- Test del cliente HTTP real con transporte simulado: system prompt y corrección
  en el idioma de cada fuente; un resultado con exclusiones exige reintento.
- Prueba de navegador con respuestas simuladas: ambos botones muestran el desglose,
  conservan las exclusiones manuales y los filtros obligatorios desactivados; sin
  desbordamiento horizontal. No se guardó la configuración simulada.

## Modelo real

Se usa el texto original facilitado por la persona con `qwen3.5:4b` instalado,
en el Ollama dedicado de puerto 11435, sin descargar modelos ni aplicar filtros.

La primera prueba (`positive-interests-v3`) devolvió HTTP 422: el modelo inventó
`cs.HO` para historia de la computación y repitió el código durante el reintento.
Ese resultado se conserva en
`data/validation/positive-interests-20261007/arxiv-live-v3-rejected.json`.
La versión v4 añade el enum del catálogo al esquema de generación. Ambas fuentes
devolvieron HTTP 200, pero la revisión encontró fallos que impiden considerar esas
salidas una validación satisfactoria:

- arXiv conservó los nombres de temas en español. La detección de idioma no tenía
  suficientes marcadores en cada etiqueta corta; ahora también valida las etiquetas
  juntas y el esquema especifica explícitamente el idioma de los nombres.
- Colibrí concatenó disciplinas y omitió sus términos independientes; expresiones
  como `inteligencia artificial inteligencia humana` son débiles como filtros
  literales. También eliminó preposiciones de algunas variantes.
- arXiv trató matemáticas generales como `math.GM`, que no equivale a todo el campo,
  y eligió solo algunas ramas de física. También infirió ramas concretas de la
  palabra ambigua «abstracto».

La versión v5 refuerza esas instrucciones, pide citas mínimas, fusionar menciones
duplicadas y conservar las expresiones académicas naturales. Los resultados se
guardan por separado para revisar cobertura y fidelidad, además de validez formal.
Una salida válida no basta para probar que todos los intereses están bien
representados ni que una consulta remota encuentre documentos pertinentes. La
detección en/es sigue siendo heurística, no una garantía para cada etiqueta corta.

Las dos respuestas v5 devolvieron HTTP 200. arXiv escribió los temas en inglés, pero
colocó códigos de categorías en **todos** los términos de búsqueda, incluido el
código inventado `cs.HO`. Eso produciría una consulta formalmente válida pero inútil
para títulos/abstracts. La versión v6 rechaza códigos reales o inventados en las
palabras clave, incluso en variantes de mayúsculas o acompañados de otros términos.
El prompt y el esquema explicitan la diferencia con un ejemplo. Los tests cubren
estos casos; la respuesta v5 se conserva como evidencia de fallo, no de éxito.

Colibrí v5 incluye ahora `inteligencia artificial` e `inteligencia humana` como
términos separados y conserva todos los temas mencionados, sin exclusiones. Quedan
variantes poco naturales, demasiado genéricas y una mención duplicada de matemáticas;
la deduplicación de términos evita repetir la misma palabra en la lista plana, pero
no equivale a una revisión semántica completa de cada variante o tema.

### Resultado final v6

Ambas llamadas reales devolvieron HTTP 200 al primer intento; los resultados están
en `arxiv-live-v6-response.json` y `colibri-live-v6-response.json` dentro del
directorio de validación. Se revalidaron localmente contra el esquema actual.

- arXiv: 13 temas, 40 categorías distintas y 38 términos reales en inglés.
- Colibrí: 13 temas y 29 términos distintos, con explicación en español.
- Ninguna salida contiene un campo de exclusiones. Ambas incluyen las disciplinas
  explícitas, astronomía, física, historia y los temas de cursos; la formación y el
  año de carrera no aparecen como temas.

**La corrección semántica no está plenamente validada.** Qwen todavía:

- asigna `math.FA` (análisis funcional) a teoría de lenguajes y `cs.HC` (interacción
  humano-computadora) a historia de la computación, sin respaldo suficiente;
- omite `q-bio.NC` en la relación IA/inteligencia humana;
- no cubre de forma general todas las familias matemáticas y físicas;
- interpreta «lo abstracto» como preferencias matemáticas más concretas de lo que
  establece la descripción;
- mantiene variantes poco naturales y duplicación de temas en Colibrí.

Por tanto, estas salidas prueban validez formal y mejoras de comportamiento, pero
no que el modelo traduzca los intereses a filtros semánticamente correctos sin
revisión. No se modificaron resultados del modelo para presentarlos como exitosos.

### Referencia revisada, separada del modelo

`arxiv-reviewed-draft.json` identifica explícitamente su origen como referencia
revisada por el asistente, **no producida por Ollama**. El resultado aplanado está en
`arxiv-reviewed-reference.json`: 12 temas, 95 categorías y 90 términos en inglés.
Se revisaron categorías para los temas concretos, se conservaron las áreas amplias
y se advirtieron las interpretaciones provisionales. No se aplicó a Settings ni se
insertó como caché de una propuesta del modelo.

La cobertura amplia de matemáticas y física incorpora las ramas del catálogo como
alternativas de descubrimiento, no afirma preferencias individuales por cada rama.
Conviene dejar desactivada la coincidencia obligatoria de palabras para esa
referencia amplia. Historia de la computación no tiene una categoría propia;
`cs.GL` y `cs.OH` son puntos de partida imperfectos.

`reviewed-reference-check.json` registra validación de códigos/citas/idioma, generación
local de consultas y coincidencias literales en 12 ejemplos sintéticos, uno por tema.
No es una comprobación de aceptación remota ni de relevancia de artículos reales.
No se hicieron búsquedas adicionales en arXiv o Colibrí.

## Preservación

Respaldo previo:
`data/validation/positive-interests-20261007/before-013204.sqlite3`.
La comparación posterior conservó configuración, 2860 documentos, 58 jobs,
5 runs, 37 solicitudes de fuentes y las exclusiones/tombstones del boletín.
Evidencia: `preservation-check.json` en el mismo directorio. Las propuestas
añaden solo sus cachés en `meta`; no activan trabajos científicos ni consultan
arXiv/Colibrí para descubrir documentos.

La comprobación final `preservation-check-final.json` compara todas las tablas
de contenido contra el respaldo y conserva también las 8 membresías de `bulletin`.
La configuración continúa idéntica. Al terminar no hay inferencia o compilación
activa; permanecen los siete resúmenes completados y el error anterior, sin reintentos
ni reactivación de cancelaciones.
