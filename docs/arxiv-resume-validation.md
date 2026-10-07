# Recuperación incremental de arXiv — 2026-10-07

## Fallo comprobado

La configuración guardada tenía 40 categorías, sin exclusiones y con coincidencia
obligatoria de términos desactivada. Tres búsquedas llegaron a 50 páginas y fallaron
al alcanzar 5000 metadatos. Las 150 peticiones de metadatos tuvieron HTTP 200;
el límite local lanzaba una excepción antes de `db.add_papers()`, de modo que las
páginas de esos intentos no se guardaban. Los reintentos empezaban de nuevo.

## Corrección

- `ArxivSource` divide todas las categorías en grupos de hasta ocho y conserva
  todos los grupos de términos cuando se exige coincidencia. Los grupos son una
  división operativa, no un límite a los intereses aceptados.
- Una página por grupo, por turnos; hasta diez peticiones de cien registros por
  pasada. La continuación puede recorrer más de 5000 registros en total.
- Se persisten los documentos y `meta.discovery:arxiv` en la misma transacción.
  El punto guardado conserva consultas, offsets, grupo siguiente, páginas, nuevos
  documentos guardados y los extremos del intervalo. Una transacción fallida no
  avanza el punto ni confirma documentos a medias.
- Al reiniciar se recupera el intervalo fijo y la página siguiente. Los artículos
  recibidos anteriormente ya están en SQLite; no es necesario descargarlos otra vez.
- Se deduplican versiones y resultados compartidos entre grupos. Los documentos
  guardados no se borran por cambiar filtros; se invalida solo la continuación.
- Los filtros o períodos modificados en Configuración reinician el recorrido
  correspondiente. Cambiar modelo, palabras solo de prioridad o cupos no reinicia
  la descarga de metadatos.
- El coordinador selecciona resultados locales tras una pasada parcial y respeta
  los cupos diarios acumulados, exclusiones/tombstones y trabajos cancelados.
- Las pasadas pendientes no avanzan `last_scan` ni confirman la franja diaria.
  Se continúa tras 30 minutos con programación activa. Al completar todos los
  grupos se confirma el extremo final original, no la hora posterior del reintento.
- Una página con offset incorrecto o una repetición exacta de la anterior se
  rechaza sin avanzar. HTTP 429/503 conserva el avance y las pausas de red vigentes.
- Actividad muestra páginas y nuevos documentos confirmados, grupos terminados
  y la diferencia entre recorrido parcial y completo.

Se consultó el manual oficial de la API:
<https://info.arxiv.org/help/api/user-manual.html>.
La API documenta `submittedDate` como filtro de fechas, no un filtro equivalente
de actualización. Filtrar solo por envío original perdería revisiones nuevas de
trabajos antiguos; por eso se mantiene `sortBy=lastUpdatedDate` y el control local
del intervalo. No se inventó un campo de consulta no documentado.

## Pruebas

Los tests en `tests/test_arxiv_resume.py` cubren más de 5000 registros, continuación
desde otra instancia, intervalos fijos, grupos por turnos, deduplicación, fallos
HTTP y cooldowns, cancelación, páginas incorrectas/repetidas, atomicidad, cambios
de filtros, selección parcial, cupos, borrado de boletines y revisiones de envíos
antiguos. El conjunto completo y Ruff se ejecutan con las órdenes habituales.
Resultado final: **193 tests aprobados**, Ruff aprobado. Solo permanece la advertencia
de deprecación ya conocida de Starlette/TestClient.

## Verificación real

Respaldo previo:
`data/validation/arxiv-resume-20261007/before-130219.sqlite3`.
Se reinició únicamente el servicio de la aplicación después de verificar que no había
búsqueda, resumen o propuesta de intereses activos. El servicio Ollama dedicado
no se reinició. La única pausa levantada fue la espera **local** del error de
5000 metadatos ya corregido; no había pausa HTTP de arXiv que saltar.

La primera pasada real, con los filtros guardados de la persona:

- diez páginas/peticiones de metadatos, cinco grupos;
- **829 documentos nuevos confirmados** en SQLite;
- dos páginas recorridas por grupo, offset siguiente **200**;
- estado parcial, sin descartar resultados ni volver a empezar;
- **tres artículos de arXiv en el boletín del 7 de octubre**, respetando el reparto
  guardado de 15 artículos totales y hasta 12 de Colibrí;
- continuación prevista a las **13:32:49 de Montevideo**;
- configuración guardada idéntica a la anterior.

Artefactos: `before-status.json`, `before-settings.json`, `after-first-pass-status.json`,
`first-pass-run.json` y `first-pass-bulletin.json` en el mismo directorio de validación.
El navegador mostró «Recorrido parcial guardado: 10 páginas · 829 registros nuevos
guardados · 0 de 5 grupos completados» sin desbordamiento horizontal.

`preservation-check.json` compara el respaldo con la base después de la recuperación:
se conservan todas las filas preexistentes de runs, jobs, boletín, solicitudes y
exclusiones/tombstones. Los 2860 documentos anteriores y sus resultados no nulos
permanecen intactos; se añaden 829 documentos, tres membresías y tres jobs de resumen.
La generación normal puede completar resultados antes nulos de los artículos
seleccionados. El servicio continuó una inferencia activa al terminar la verificación;
no se reinició ni interrumpió esa tarea.

La primera pasada real no demuestra que se haya completado todo el período.
La recuperación de offsets tras reinicio y al agotar presupuesto sí se verifica
en tests simulados; la continuación automática posterior sigue el horario guardado.
La API no proporciona una instantánea transaccional del índice remoto: el intervalo
local permanece fijo, pero cambios del índice pueden mover resultados entre páginas.
Se conserva el solapamiento temporal para mitigar omisiones, sin garantizar una
cobertura perfecta ni relevancia semántica de todos los registros.
