"""Avisos nativos de Linux, sin shell ni herramientas accesibles al modelo."""
import asyncio
import logging
import shutil
from html import escape

log = logging.getLogger(__name__)


class DesktopNotifier:
    async def _send(self, summary, body):
        executable = shutil.which("notify-send")
        if not executable:
            return {"status": "unavailable", "error": "No se encontró notify-send. Instala libnotify-bin para usar avisos de escritorio."}
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                executable, "--app-name=Lecturas de investigación", "--icon=emblem-documents",
                "--urgency=normal", "--expire-time=10000", "--", summary, body,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode:
                return {"status": "error", "error": stderr.decode(errors="replace").strip()[:500]
                        or "El escritorio rechazó la notificación."}
            return {"status": "sent"}
        except (OSError, TimeoutError) as exc:
            return {"status": "error", "error": str(exc)[:500] or "El envío de la notificación agotó el tiempo de espera."}
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    async def completion(self, paper, kind, *, partial=False):
        label = {"brief": "Resumen listo", "summary": "Resumen listo", "overview": "Resumen por secciones listo", "analysis": "Análisis técnico listo"}[kind]
        if kind == "analysis" and partial:
            label += " · lectura parcial"
        # libnotify admite markup en el cuerpo: escapar el texto externo y quitar controles.
        title = " ".join(paper["title"].split())
        title = "".join(char for char in title if char.isprintable())[:280]
        return await self._send(label, escape(title, quote=True))

    async def test(self):
        return await self._send("Notificación de prueba",
                                "Recibirás un aviso cuando termine un resumen o un análisis técnico.")
