# Actualización de interfaz en ambos hosts — 2026-10-07

El servidor entregaba exactamente el mismo HTML, JavaScript y CSS en localhost y
127.0.0.1, pero sin instrucciones explícitas de caché. Las pestañas mantienen el código
que ya cargaron al cambiar una ruta hash; el navegador también mantiene cachés por origen.
Esto es compatible con observar una ficha actualizada en un host y antigua en el otro,
aunque no se inspeccionó directamente la caché de la pestaña del usuario.

## Corrección

- `app.index()` responde HTML con URLs de CSS/JS versionadas por SHA-256 del contenido.
  Los hashes se calculan al solicitar la página, no solo al arrancar el servicio.
- HTML: `Cache-Control: no-store`.
- Archivos estáticos: `Cache-Control: no-cache`, con revalidación mediante ETag.
- El cambio afecta a ambos hosts por igual y no modifica datos, filtros o inferencia.
- Una pestaña anterior debe recargarse completamente una vez; no basta navegar entre
  las vistas con enlaces `#...`.

## Verificación

**162 pruebas** y Ruff pasan. Se verifican hosts idénticos, hashes correctos, cache headers,
revalidación 304 y cambio de versión de un asset sin reiniciar la aplicación.

En producción, peticiones HTTP a ambos hosts confirmaron HTML y recursos idénticos,
con nuevas versiones y headers. Tras recargar en navegador la ficha 2847, se observaron
las URLs versionadas, ausencia del texto/selector retirados y resumen de ancho completo.
El navegador de revisión no permitió navegar a localhost a través de su conexión;
la equivalencia del host localhost se comprobó por HTTP desde el servidor y en tests.

Se reinició únicamente la aplicación, sin trabajo activo. Comparación contra
`data/validation/frontend-cache-20261007/before.sqlite3`: artículos, tareas, pertenencias,
ledger de solicitudes y settings intactos. `hosts.json` conserva hashes y headers.
