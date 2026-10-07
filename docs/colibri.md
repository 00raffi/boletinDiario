# Conector Colibrí

Sitio: https://www.colibri.udelar.edu.uy/. Integración solicitada el 6 de octubre de 2026.
Inspección de endpoints públicos realizada los días 5 y 6, sin autenticación.

## Confirmado

- Repositorio institucional de la Universidad de la República.
- DSpace **9.1**, anunciado tanto en HTML como en la raíz de su API.
- API REST: https://www.colibri.udelar.edu.uy/server/api
- Comunidades: `/server/api/core/communities/search/top?size=30`, con paginación.
- Comunidades y colecciones tienen UUID estable y enlaces REST; no necesitan un
  modelo navegando ni interpretar visualmente la página.

## Alcance inicial y catálogo ampliable

Comunidad **Facultad de Ingeniería**:
`8de5ffef-1c73-4c9b-a83f-b75c953201ba`.

Colecciones verificadas directamente dentro de Ingeniería:

| Colección | UUID |
|---|---|
| Publicaciones académicas y científicas | `7072e541-9b63-4441-91b7-c1785264a870` |
| Tesis de grado | `68a652f1-4c0f-45df-82ee-7343441c404f` |
| Tesis de Posgrado | `23de5ca8-4345-45fe-b622-78dc9ec33793` |

Otras colecciones: libros, publicaciones históricas, planes de estudio y programas.

Subcomunidad **Instituto de Computación**:
`36bd9ee5-261b-4db6-8dd6-e96cafcb1fd4`.
También aparecen IMERL, Física, Ingeniería Eléctrica y otros institutos.
Todavía no se inspeccionaron las colecciones del Instituto de Computación ni se
verificó una colección específica de Inteligencia Artificial.

Consultas verificadas:

```text
/server/api/core/communities/8de5ffef-1c73-4c9b-a83f-b75c953201ba/collections?size=50
/server/api/core/communities/8de5ffef-1c73-4c9b-a83f-b75c953201ba/subcommunities?size=50
```

## Implementación

`radar/colibri.py` usa `/discover/search/objects?scope=<UUID>&sort=dc.date.accessioned,DESC`.
Se valida que el servidor confirme el orden y que las fechas recibidas no aumenten al
paginar. Se recorre hasta salir del periodo, con máximo 50 páginas de 100 registros
entre todos los scopes. Un fallo no avanza el cursor. Fing busca recursivamente y ya
incluye InCo: se elimina esa consulta redundante y se deduplican UUID entre scopes.

Fecha de novedades: `dc.date.accessioned`. Año de publicación: `dc.date.issued`, sin
inventar día/mes para años incompletos. Abstract: `dc.description.abstract`, priorizando
el idioma declarado si hay varios. Se excluyen registros retirados, no archivados o
no descubribles. Tipos, palabras y exclusiones se aplican localmente a la selección;
un registro sin abstract se guarda pero no recibe un resumen automático.

La versión inicial descubre depósitos, no revisiones del mismo UUID. No hay deduplicación
por DOI entre Colibrí y arXiv. Las comunidades/colecciones adicionales se eligen desde
un explorador público; el catálogo se cachea un día y no da herramientas al modelo.

Los seleccionados reciben un único resumen automático de afinidad, abstract, secciones
y apoyos. No se generan análisis técnicos. Los metadatos PDF no garantizan que el
archivo sea público o legible: se comprueba al descargar. **Ver PDF** resuelve y guarda
el enlace al pulsarlo, sin inferencia ni descarga del contenido para hallar ese enlace.
Se consulta ORIGINAL y sus bitstreams. Se usa el único PDF, o el principal
indicado por DSpace si hay varios. Sin selección inequívoca no se descarga uno al azar.
No se siguen enlaces externos, no se inicia sesión ni se eluden permisos/embargos.
Límite configurable de descarga, **100 MB por defecto**; hasta 100 páginas/300 000 caracteres extraídos, sin OCR y con cobertura
parcial explícita. La solicitud PDF 401/403 queda como error, no inicia autenticación.

## Cuotas y fallos independientes

Reparto inicial recomendado: 8 resúmenes de Colibrí y 2 de arXiv. La simplificación
conservó los límites guardados (6 + 2), sin cupos de análisis técnico.
No se transfieren cupos cuando faltan novedades y
varias búsquedas manuales no multiplican esos máximos. Los filtros, cursores, pausas
y estados de descubrimiento se mantienen separados; una búsqueda puede terminar
parcialmente con el boletín de una fuente conservado aunque falle la otra.

Las marcas Me interesa/No me interesa mantienen entradas visibles y marcadas en el boletín, sin borrar
documentos, cancelar tareas ni modificar filtros. No se incluyen en prompts ni rankings
de selección y no rellenan cupos al aplicarse. La biblioteca permite filtrar esas marcas.

## Validación real (2026-10-06)

Prueba aislada: `/tmp/opencode/colibri-check-x1ojehug/`, mediante
`scripts/check-colibri.py --pdf`. Descubrió **13 depósitos recientes**, seleccionó **8**
y guardó un cursor confirmado. El PDF público de ParaKit tenía **16 931 072 bytes** y
**164 páginas**; se extrajeron **100** y se indicó lectura parcial.
La prueba hizo **4 solicitudes**: 1 descubrimiento, 2 metadatos de archivo y 1 descarga.
Todas fueron a Colibrí, ninguna a arXiv. No hubo inferencia ni cambios en producción.

La inspección inicial hizo además **5 solicitudes** a Colibrí (primera consulta InCo,
dos consultas de descubrimiento Fing/InCo, paquetes y archivos de un documento).
Las pruebas de interfaz usaron una base separada y un catálogo simulado. Se verificó
la retirada de 8 a 7 entradas al marcar, persistencia del resumen en biblioteca, paneles
separados y guardado independiente de palabras. No se aplicaron marcas de prueba a
producción. Los tests cubren migración aditiva, cuotas, aislamiento de errores,
PDF ambiguo/restringido/grande, redirecciones, idiomas, Retry-After y pausa persistente.

El catálogo real se validó además con **6 solicitudes**: comunidades principales,
contenido de Fing, diagnóstico y nueva comprobación tras corregir el nombre de la
relación DSpace `subcommunities`. El primer catálogo omitía las subcomunidades; se
conserva ese resultado intermedio, se versionó la caché y se añadió una regresión.
El resultado final de Fing tiene **14 entradas**, incluido InCo; volver a pedir el
mismo catálogo desde caché hizo **0 solicitudes**. Total de inspección y validación
durante esta integración: **15 solicitudes a Colibrí, 0 a arXiv**, aparte de las
consultas posteriores de producción que tienen su propio contador persistente.

Verificación final: **116 pruebas automatizadas** y Ruff pasan. Se esperó al análisis
de arXiv en curso (job 39), que terminó `done`, antes de reiniciar. Se guardó un respaldo
SQLite consistente y se activó Colibrí con los cupos solicitados. La primera búsqueda
de producción hizo **1 solicitud**, produjo un boletín visible de **8 Colibrí + 2 arXiv**
y conservó el cursor arXiv anterior sin otra consulta. El análisis cancelado (job 13)
permanece cancelado. Los nuevos resúmenes empezaron a generarse secuencialmente.

Artefactos resumidos: `data/validation/colibri-20261006/`. La consulta pública y extracción
funcionaron; no certifican interpretación científica de PDFs ni disponibilidad futura.
