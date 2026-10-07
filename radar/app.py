import fcntl
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .catalog import CATEGORIES
from .colibri_catalog import COMMUNITIES
from .config import DATA_DIR, Settings
from .db import Database, decode_paper, utcnow
from .engine import Engine
from .interests import InferenceBusy

STATIC = Path(__file__).parent / "static"


def create_app(data_dir=DATA_DIR, *, start_engine=True):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = Database(data_dir / "radar.sqlite3")
    engine = Engine(db, data_dir)

    @asynccontextmanager
    async def lifespan(app):
        lock = (data_dir / "service.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("Ya hay una instancia de la aplicación usando esta base de datos.")
        if start_engine:
            await engine.start()
        try:
            yield
        finally:
            await engine.stop()
            lock.close()

    app = FastAPI(title="boletinDiario", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.engine = engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("x-radar-request") != "1" or (origin and origin != str(request.base_url).rstrip("/")):
                return PlainTextResponse("Petición local no autorizada", status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    async def index():
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for name in ("app.js", "style.css"):
            version = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
            html = html.replace(f"/static/{name}", f"/static/{name}?v={version}")
        return HTMLResponse(html)

    @app.get("/api/status")
    async def status():
        return engine.status()

    @app.get("/api/settings")
    async def settings():
        return db.settings().model_dump()

    @app.put("/api/settings")
    async def save_settings(settings: Settings):
        previous = db.settings()
        changed = []
        for source in ("arxiv", "colibri"):
            old = previous.filters(source)
            new = settings.filters(source)
            if (old[0] != new[0] or old[3] != new[3] or (new[3] and old[1] != new[1])
                    or getattr(previous, f"{source}_enabled") != getattr(settings, f"{source}_enabled")
                    or previous.initial_days != settings.initial_days
                    or previous.metadata_overlap_days != settings.metadata_overlap_days
                    or (source == "colibri" and previous.colibri_types != settings.colibri_types)):
                changed.append(source)
        # Poder pausar/cambiar horario aunque Ollama esté desconectado.
        if previous.model != settings.model:
            try:
                models = await engine.llm.models()
            except httpx.HTTPError:
                raise HTTPException(503, "Ollama no responde. Inícialo antes de cambiar el modelo.")
            if settings.model not in models:
                raise HTTPException(422, "Selecciona un modelo local instalado en Ollama.")
        if changed and engine.status()["scanning"]:
            raise HTTPException(409, "Espera a que termine la búsqueda antes de cambiar sus filtros.")
        db.set_meta("settings", settings.model_dump())
        for source in changed:
            state = engine.source_state(source)
            db.set_meta(f"source:{source}", {**state, "last_scan": None, "last_slot": None})
            if source == "arxiv":
                db.set_meta("last_scan", None)
                db.set_meta("last_slot", None)
                db.set_meta("discovery:arxiv", None)
        return settings.model_dump()

    @app.get("/api/categories")
    async def categories():
        names = dict(COMMUNITIES)
        for row in db.rows("SELECT value FROM meta WHERE key LIKE 'colibri-catalog:%'"):
            for entry in json.loads(row["value"])["entries"]:
                names[entry["uuid"]] = entry["name"]
        return {"categories": CATEGORIES, "colibri_communities": names}

    class ScopeInput(BaseModel):
        parent: str | None = None

    @app.post("/api/colibri/scopes")
    async def colibri_scopes(request: ScopeInput):
        try:
            return {"entries": await engine.sources["colibri"].browse(request.parent)}
        except httpx.HTTPError as exc:
            raise HTTPException(503, "No se pudo consultar el catálogo público de Colibrí. La fuente puede estar en pausa; inténtalo más tarde.") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    class InterestsInput(BaseModel):
        text: str = Field(min_length=3, max_length=4000)
        source: Literal["arxiv", "colibri"] = "arxiv"

        @field_validator("text", mode="before")
        @classmethod
        def strip_text(cls, value):
            return value.strip() if isinstance(value, str) else value

    @app.post("/api/interests/propose")
    async def interests(request: InterestsInput):
        try:
            return await engine.compile_interests(request.text, request.source)
        except InferenceBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Ollama no pudo generar los filtros. Revisa el servicio local.") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:1500]) from exc

    @app.get("/api/models")
    async def models():
        try:
            return {"models": await engine.llm.models(), "available": True}
        except httpx.HTTPError:
            return {"models": [], "available": False}

    @app.post("/api/scan")
    async def scan(source: Literal["arxiv", "colibri"] | None = None):
        # Evitar repetir idéntica consulta a arXiv accidentalmente.
        recent = db.rows("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1")
        if recent and (datetime.now(UTC) - datetime.fromisoformat(recent[0]["started_at"])).total_seconds() < 180:
            raise HTTPException(429, "Espera al menos tres minutos entre búsquedas; los artículos guardados siguen disponibles.")
        if source and not getattr(db.settings(), f"{source}_enabled"):
            raise HTTPException(422, "La fuente está desactivada en Configuración.")
        if not engine.trigger(sources=[source] if source else None):
            raise HTTPException(409, "Ya hay una búsqueda en curso.")
        return {"started": True}

    @app.post("/api/cancel")
    async def cancel():
        return {"cancelled": engine.cancel()}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: int):
        try:
            cancelled = await engine.cancel_job(job_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not cancelled:
            raise HTTPException(409, "La tarea ya no está en cola ni en curso, o está finalizando.")
        return {"cancelled": True}

    @app.post("/api/notifications/test")
    async def test_notification():
        result = await engine.notifier.test()
        db.set_meta("last_notification", {**result, "at": utcnow(), "kind": "test"})
        if result["status"] != "sent":
            raise HTTPException(503, result.get("error", "No se pudo enviar la notificación."))
        return result

    @app.get("/api/papers")
    async def papers(q: str = "", state: str = "", page: int = 1, source: Literal["arxiv", "colibri"] | None = None,
                     bulletin_day: date | None = None):
        page = max(1, page)
        clauses, params = ["1=1"], []
        if q:
            clauses.append("(title LIKE ? OR abstract LIKE ?)")
            params += [f"%{q[:200]}%"] * 2
        filters = {"favorites": "favorite=1", "unread": "is_read=0", "analyzed": "analysis IS NOT NULL", "summary": "overview IS NOT NULL",
                   "revisions": "is_revision=1", "brief": "brief IS NOT NULL", "interested": "interest=1",
                   "not_interested": "interest=-1", "unrated": "interest=0"}
        if state in filters:
            clauses.append(filters[state])
        if source:
            clauses.append("source=?")
            params.append(source)
        if bulletin_day:
            ids = [run["id"] for run in engine.day_runs(bulletin_day.isoformat(), db.settings())]
            if not ids:
                return {"papers": [], "total": 0, "page": page}
            clauses.append(f"EXISTS(SELECT 1 FROM bulletin b WHERE b.paper_id=papers.id AND b.run_id IN ({','.join('?' for _ in ids)}))")
            params.extend(ids)
        where = " AND ".join(clauses)
        total = db.rows(f"SELECT count(*) AS total FROM papers WHERE {where}", params)[0]["total"]
        rows = db.rows(f"SELECT * FROM papers WHERE {where} ORDER BY updated DESC,id DESC LIMIT 30 OFFSET ?",
                       (*params, (page - 1) * 30))
        return {"papers": [decode_paper(row) for row in rows], "total": total, "page": page}

    @app.get("/api/bulletins")
    async def bulletins():
        settings = db.settings()
        days = {}
        for row in db.rows("""SELECT r.id,r.started_at,r.bulletin_day,b.paper_id,p.source FROM runs r
                              JOIN bulletin b ON b.run_id=r.id JOIN papers p ON p.id=b.paper_id"""):
            day = row["bulletin_day"] or datetime.fromisoformat(row["started_at"]).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
            entry = days.setdefault(day, {"day": day, "papers": {}, "runs": set()})
            entry["papers"][row["paper_id"]] = row["source"]
            entry["runs"].add(row["id"])
        return {"days": [{"day": day, "total": len(info["papers"]), "runs": len(info["runs"]),
                          "sources": {source: sum(s == source for s in info["papers"].values()) for source in ("colibri", "arxiv")}}
                         for day, info in sorted(days.items(), reverse=True)]}

    @app.get("/api/bulletin")
    async def bulletin():
        runs = db.rows("SELECT * FROM runs r WHERE EXISTS(SELECT 1 FROM bulletin b WHERE b.run_id=r.id) ORDER BY id DESC LIMIT 1")
        if not runs:
            return {"run": None, "papers": [], "hidden_count": 0}
        settings = db.settings()
        day = runs[0]["bulletin_day"] or datetime.fromisoformat(runs[0]["started_at"]).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
        ids = [run["id"] for run in engine.day_runs(day, settings)]
        rows = db.rows(f"SELECT DISTINCT p.* FROM papers p JOIN bulletin b ON p.id=b.paper_id WHERE b.run_id IN ({','.join('?' for _ in ids)}) ORDER BY p.updated DESC", ids)
        papers = [decode_paper(row) for row in rows]
        papers.sort(key=lambda p: (p["brief"]["relevance"] if p["brief"] else 0, p["updated"]), reverse=True)
        visible = []
        for source in ("colibri", "arxiv"):
            source_papers = [p for p in papers if p["source"] == source]
            visible.extend(source_papers)
        return {"run": runs[0], "papers": visible, "hidden_count": 0,
                "marked_count": sum(p["interest"] != 0 for p in visible),
                 "day": day, "quotas": settings.quotas()}

    @app.delete("/api/bulletins/{day}")
    async def delete_bulletin(day: date):
        try:
            return engine.remove_bulletin(day.isoformat())
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.delete("/api/bulletins/{day}/papers/{paper_id}")
    async def remove_article(day: date, paper_id: int):
        try:
            return engine.remove_bulletin(day.isoformat(), paper_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/papers/{paper_id}")
    async def paper(paper_id: int):
        result = db.paper(paper_id)
        if not result:
            raise HTTPException(404, "Artículo no encontrado.")
        result["jobs"] = db.rows("SELECT * FROM jobs WHERE paper_id=?", (paper_id,))
        result["bulletin_days"] = engine.paper_bulletin_days(paper_id)
        return result

    @app.post("/api/papers/{paper_id}/pdf")
    async def pdf_link(paper_id: int):
        paper = db.paper(paper_id)
        if not paper:
            raise HTTPException(404, "Artículo no encontrado.")
        if paper["source"] != "colibri":
            return {"url": paper["pdf_url"]}
        try:
            url, _ = await engine.sources["colibri"].resolve_pdf(paper)
            return {"url": url}
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Colibrí no permitió resolver el PDF. Consulta la ficha original o inténtalo más tarde si la fuente está en pausa.") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    class PaperFlags(BaseModel):
        favorite: bool | None = None
        is_read: bool | None = None
        interest: Literal[-1, 0, 1] | None = None

    @app.patch("/api/papers/{paper_id}")
    async def flags(paper_id: int, flags: PaperFlags):
        paper = db.paper(paper_id)
        if not paper:
            raise HTTPException(404, "Artículo no encontrado.")
        for field, value in flags.model_dump(exclude_none=True).items():
            db.execute(f"UPDATE papers SET {field}=? WHERE id=?", (int(value), paper_id))
        return {"saved": True}

    @app.post("/api/papers/{paper_id}/jobs/{kind}")
    async def queue(paper_id: int, kind: str, regenerate: bool = False):
        if kind == "analysis":
            raise HTTPException(410, "El análisis técnico fue retirado. Puedes consultar el PDF original.")
        if kind not in {"brief", "summary", "overview"}:
            raise HTTPException(404, "Tipo de tarea desconocido.")
        paper = db.paper(paper_id)
        if not paper:
            raise HTTPException(404, "Artículo no encontrado.")
        if kind == "brief" and not paper["abstract"].strip():
            raise HTTPException(422, "No hay abstract disponible. Consulta el documento original; no se inventará un resumen.")
        db.queue(paper_id, "summary", retry=True, regenerate=regenerate)
        return {"queued": True}

    @app.get("/api/activity")
    async def activity():
        job_limit = db.settings().bulletin_limit
        return {"runs": db.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 30"),
                  "jobs": db.rows("""SELECT j.*,p.title FROM jobs j JOIN papers p ON p.id=j.paper_id
                      WHERE j.kind='summary'
                     ORDER BY CASE j.status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                     CASE WHEN j.status='queued' THEN j.created_at END ASC,j.updated_at DESC,j.id DESC LIMIT ?""", (job_limit,)),
                  "jobs_total": db.rows("SELECT count(*) AS n FROM jobs WHERE kind='summary'")[0]["n"], "job_limit": job_limit}

    @app.get("/api/papers/{paper_id}/export")
    async def export(paper_id: int):
        paper = db.paper(paper_id)
        if not paper:
            raise HTTPException(404, "Artículo no encontrado.")
        parts = [f"# {paper['title']}", f"Fuente ({paper['source']}): {paper['url']}",
                 "Preprint de arXiv. La revisión por pares no fue verificada." if paper['source'] == 'arxiv'
                 else f"Documento de Colibrí: {paper['document_type'] or 'tipo no indicado'}. La revisión por pares no fue verificada.",
                 f"Interés personal: { {1:'Me interesa',-1:'No me interesa',0:'Sin marcar'}[paper['interest']]} (no utilizado como feedback del modelo)."]
        if paper["brief"]:
            parts += ["## Boletín (solo abstract)", paper["brief"]["summary"], paper["brief"]["contribution"]]
        if paper["overview"]:
            overview = paper["overview"]
            parts += ["## Resumen por secciones", overview["warning"]]
            for section in overview["sections"]:
                parts += [f"### {section['title']}", section["summary"], f"Páginas consultadas: {section['pages']}"]
            parts += ["## Organizaciones que apoyan el estudio"]
            for support in overview["support"]:
                parts += [f"{support['name']} ({support['role']}) · página {support['page']}", "> " + support["quote"]]
        if paper["analysis"]:
            analysis = paper["analysis"]
            parts += [f"Alcance: {analysis['scope']}", analysis["warning"]]
            for key in ("problem", "contribution", "method", "evaluation", "results", "author_limitations", "observations"):
                parts += [f"## {key}", analysis[key]]
            parts += ["## Revisión humana", *analysis["human_review"], "## Evidencia literal"]
            for item in analysis["evidence"]:
                parts += [f"Página {item['page']}: {item['claim']}", "> " + item["quote"].replace("\n", "\n> ")]
        return PlainTextResponse("\n\n".join(parts), headers={"Content-Disposition": f'attachment; filename="paper-{paper_id}.md"'})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
