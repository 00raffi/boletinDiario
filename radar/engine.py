import asyncio
import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .catalog import ALIASES
from .colibri import ColibriSource
from .config import daily_slot, next_slot
from .db import decode_paper, utcnow
from .interests import (
    PROFILE_VERSION,
    InferenceBusy,
    propose_colibri_interests,
    propose_interests,
    term_matches,
)
from .llm import Ollama
from .notifications import DesktopNotifier
from .overview import article_overview
from .sources import SOURCES, ArxivSource, DiscoveryBatch

log = logging.getLogger(__name__)


def select_candidates(papers, settings, source="arxiv", limit=None):
    eligible = []
    categories, keywords, excluded, strict = settings.filters(source)
    for paper in papers:
        if source == "arxiv" and "categories" in paper and not set(categories).intersection(
                ALIASES.get(code, code) for code in paper["categories"]):
            continue
        if source == "colibri":
            if not set(categories).intersection(paper.get("categories", [])):
                continue
            if settings.colibri_types and paper.get("document_type", "").lower() not in settings.colibri_types:
                continue
        text = (paper["title"] + " " + paper["abstract"]).lower()
        if source == "colibri":
            text += " " + " ".join(paper.get("categories", []))
        if any(term_matches(term, text) for term in excluded):
            continue
        priority = sum(term_matches(term, text) for term in keywords)
        if strict and not priority:
            continue
        eligible.append((priority, paper["updated"], paper))
    eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in eligible[:settings.bulletin_limit if limit is None else limit]]


class Engine:
    def __init__(self, db, data_dir):
        self.db, self.data_dir = db, data_dir
        self.sources = {name: factory(db=db) for name, factory in SOURCES.items()}
        self.sources["colibri"] = ColibriSource(db=db)
        self.llm = Ollama()
        self.notifier = DesktopNotifier()
        self.scan_task = None
        self.job_task = None
        self.interest_task = None
        self.current_job = None
        self.loop_task = None
        self.stopping = False
        self.cancel_requested = set()

    async def start(self):
        self.db.recover()
        self.retire_legacy_jobs()
        self.loop_task = asyncio.create_task(self.loop())

    def retire_legacy_jobs(self):
        pending = self.db.rows("SELECT * FROM jobs WHERE status='queued' AND kind IN ('brief','overview')")
        for job in pending:
            self.db.queue(job["paper_id"], "summary")
        self.db.execute("""UPDATE jobs SET status='cancelled',progress='Sustituido por el resumen único',updated_at=?
            WHERE status='queued' AND kind IN ('brief','overview','analysis')""", (utcnow(),))

    async def stop(self):
        self.stopping = True
        tasks = [task for task in (self.loop_task, self.scan_task, self.job_task, self.interest_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def trigger(self, reason="manual", sources=None):
        if self.scan_task and not self.scan_task.done():
            return False
        self.scan_task = asyncio.create_task(self.scan(reason, sources))
        return True

    def cancel(self, job_id=None):
        # Cancelación de la tarea actual, nunca de otra tarea.
        current = self.current_job
        if (current and (job_id is None or current["id"] == job_id) and self.job_task and not self.job_task.done()
                and current["id"] not in self.cancel_requested
                and self.db.rows("SELECT status FROM jobs WHERE id=?", (current["id"],))[0]["status"] == "running"):
            self.cancel_requested.add(current["id"])
            current["cancel_requested"] = True
            self.job_task.cancel()
            return True
        return False

    async def cancel_job(self, job_id):
        rows = self.db.rows("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not rows:
            raise LookupError("Tarea no encontrada.")
        if rows[0]["status"] == "queued":
            with self.db.connect() as conn:
                changed = conn.execute("""UPDATE jobs SET status='cancelled',progress='Cancelado por el usuario',
                    updated_at=? WHERE id=? AND status='queued'""", (utcnow(), job_id)).rowcount
            return bool(changed)
        if rows[0]["status"] == "running" and self.cancel(job_id):
            task = self.job_task
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    raise
            return True
        return False

    def status(self):
        settings = self.db.settings()
        now = datetime.now(UTC)
        checkpoint = self.db.get_meta("discovery:arxiv")
        discovery = ArxivSource.discovery_progress(checkpoint) if checkpoint else None
        return {
            "scanning": bool(self.scan_task and not self.scan_task.done()),
            "current_job": self.current_job,
            "compiling_interests": self.interest_task is not None,
            "last_scan": max((self.source_state(name).get("last_scan") or "" for name in self.sources), default="") or None,
            "last_slot": self.db.get_meta("last_slot"),
            "next_run": next_slot(now, settings).isoformat() if settings.schedule_enabled else None,
            "pending_daily": any(getattr(settings, f"{name}_enabled") and self.source_state(name).get("last_slot") != daily_slot(now, settings).isoformat()
                                 for name in self.sources),
            "sources": {name: {**self.source_state(name), "network": self.db.get_meta(f"network:{name}", {}),
                                **({"discovery": discovery} if name == "arxiv" else {}),
                               "requests_today": self.db.rows("SELECT count(*) AS n FROM source_requests WHERE source=? AND started_at>=?",
                                                               (name, now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()))[0]["n"]}
                        for name in self.sources},
            "queue": self.db.rows("SELECT kind,status,count(*) AS count FROM jobs WHERE kind='summary' GROUP BY kind,status"),
            "last_notification": self.db.get_meta("last_notification"),
            "last_model_release": self.db.get_meta("last_model_release"),
            "inference": {"model": settings.model, "endpoint": self.llm.host,
                          "context_tokens": 4096, "thinking": False, "presence_penalty": 0,
                           "mode": "summary_only"},
        }

    def source_state(self, source):
        legacy = ({"last_scan": self.db.get_meta("last_scan"), "last_slot": self.db.get_meta("last_slot"),
                   "retry_after": self.db.get_meta("scan_retry_after")} if source == "arxiv" else {})
        return self.db.get_meta(f"source:{source}", legacy)

    def due_sources(self, now, settings):
        due = []
        for name in self.sources:
            state = self.source_state(name)
            retry = max(filter(None, [state.get("retry_after"), self.db.get_meta(f"network:{name}", {}).get("until")]), default=None)
            if (getattr(settings, f"{name}_enabled") and state.get("last_slot") != daily_slot(now, settings).isoformat()
                    and (not retry or now >= datetime.fromisoformat(retry))):
                due.append(name)
        return due

    def day_runs(self, day, settings):
        return [run for run in self.db.rows("SELECT * FROM runs")
                if (run["bulletin_day"] or datetime.fromisoformat(run["started_at"]).astimezone(ZoneInfo(settings.timezone)).date().isoformat()) == day]

    def used_slots(self, day, source, settings, kind="brief"):
        ids = [run["id"] for run in self.day_runs(day, settings)]
        placeholders = ",".join("?" for _ in ids) or "NULL"
        if kind == "brief":
            return self.db.rows(f"""SELECT count(*) AS n FROM papers p WHERE p.source=? AND p.id IN (
                SELECT b.paper_id FROM bulletin b WHERE b.run_id IN ({placeholders})
                UNION SELECT paper_id FROM bulletin_exclusions WHERE day=?)""", (source, *ids, day))[0]["n"]
        return self.db.rows(f"SELECT count(DISTINCT j.id) AS n FROM jobs j JOIN bulletin b ON b.paper_id=j.paper_id JOIN papers p ON p.id=j.paper_id WHERE b.run_id IN ({placeholders}) AND p.source=? AND j.kind='analysis'", (*ids, source))[0]["n"]

    def paper_bulletin_days(self, paper_id):
        settings = self.db.settings()
        rows = self.db.rows("""SELECT r.started_at,r.bulletin_day FROM runs r JOIN bulletin b ON b.run_id=r.id
            WHERE b.paper_id=?""", (paper_id,))
        return sorted({row["bulletin_day"] or datetime.fromisoformat(row["started_at"]).astimezone(
            ZoneInfo(settings.timezone)).date().isoformat() for row in rows}, reverse=True)

    def remove_bulletin(self, day, paper_id=None):
        """Eliminar pertenencias, no documentos, inferencias ni historial de consultas."""
        ids = [run["id"] for run in self.day_runs(day, self.db.settings())]
        placeholders = ",".join("?" for _ in ids) or "NULL"
        where = f"run_id IN ({placeholders})"
        params = ids
        if paper_id is not None:
            where += " AND paper_id=?"
            params = [*ids, paper_id]
        with self.db.connect() as conn:
            papers = [row["paper_id"] for row in conn.execute(f"SELECT DISTINCT paper_id FROM bulletin WHERE {where}", params)]
            if not papers:
                raise LookupError("El artículo no pertenece a ese boletín." if paper_id is not None else "Boletín no encontrado.")
            stamp = utcnow()
            conn.executemany("INSERT OR IGNORE INTO bulletin_exclusions VALUES(?,?,?)", [(day, item, stamp) for item in papers])
            if paper_id is None:
                conn.execute("INSERT OR IGNORE INTO deleted_bulletins VALUES(?,?)", (day, stamp))
            conn.execute(f"DELETE FROM bulletin WHERE {where}", params)
        return {"deleted": True, "day": day, "removed_articles": len(papers)}

    def regenerate_today(self, *, clear_archive=False, now=None):
        """Reconstrucción explícita desde metadatos locales; sin borrar resultados ni consultar fuentes."""
        settings = self.db.settings()
        now = now or datetime.now(UTC)
        day = now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
        start = (now - timedelta(days=max(settings.initial_days, settings.metadata_overlap_days))).isoformat().replace("+00:00", "Z")
        candidates = [decode_paper(row) for row in self.db.rows("""SELECT p.* FROM papers p
            WHERE trim(p.abstract)!='' AND p.updated>=? AND p.updated<=? AND NOT EXISTS (SELECT 1 FROM jobs j
                WHERE j.paper_id=p.id AND j.kind IN ('brief','overview','summary') AND j.status='cancelled')""",
            (start, now.isoformat().replace("+00:00", "Z")))]
        selected = []
        for source, limit in settings.quotas().items():
            selected.extend(select_candidates([p for p in candidates if p["source"] == source], settings, source, limit))
        old_days = {paper_id: self.paper_bulletin_days(paper_id) for paper_id in
                    [row["paper_id"] for row in self.db.rows("SELECT DISTINCT paper_id FROM bulletin")]}
        stamp = utcnow()
        stats = {source: {"status": "local", "selected": sum(p["source"] == source for p in selected)} for source in self.sources}
        with self.db.connect() as conn:
            for paper_id, days in old_days.items():
                for old_day in days:
                    if clear_archive or old_day == day:
                        conn.execute("INSERT OR IGNORE INTO bulletin_exclusions VALUES(?,?,?)", (old_day, paper_id, stamp))
                        conn.execute("INSERT OR IGNORE INTO deleted_bulletins VALUES(?,?)", (old_day, stamp))
            if clear_archive:
                conn.execute("DELETE FROM bulletin")
            else:
                ids = [run["id"] for run in self.day_runs(day, settings)]
                conn.execute(f"DELETE FROM bulletin WHERE run_id IN ({','.join('?' for _ in ids) or 'NULL'})", ids)
            # Esta reconstrucción explícita autoriza sustituir el boletín de hoy.
            conn.execute("DELETE FROM bulletin_exclusions WHERE day=?", (day,))
            conn.execute("DELETE FROM deleted_bulletins WHERE day=?", (day,))
            run_id = conn.execute("""INSERT INTO runs(started_at,finished_at,status,reason,selected,detailed_limit,detail_quotas,bulletin_day,source_stats)
                VALUES(?,?,'completed','regenerated',?,0,'{}',?,?)""", (stamp, stamp, len(selected), day, json.dumps(stats))).lastrowid
            for paper in selected:
                conn.execute("INSERT INTO bulletin VALUES(?,?)", (run_id, paper["id"]))
                if paper["brief"] is None or paper["overview"] is None:
                    conn.execute("INSERT OR IGNORE INTO jobs(paper_id,kind,created_at,updated_at) VALUES(?,'summary',?,?)",
                                 (paper["id"], stamp, stamp))
        return {"day": day, "run_id": run_id, "paper_ids": [p["id"] for p in selected], "sources": stats}

    async def scan(self, reason, sources=None):
        settings = self.db.settings()
        now = datetime.now(UTC)
        day = now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
        run_id = self.db.execute("INSERT INTO runs(started_at,status,reason,detailed_limit,detail_quotas,bulletin_day) VALUES(?,'running',?,?,?,?)",
                                 (utcnow(), reason, 0, "{}", day))
        stats, selected_count, found_count = {}, 0, 0
        enabled = [name for name in ("colibri", "arxiv") if getattr(settings, f"{name}_enabled")]
        try:
            for source in enabled:
                if sources is not None and source not in sources:
                    continue
                state = self.source_state(source)
                retry = max(filter(None, [state.get("retry_after"), self.db.get_meta(f"network:{source}", {}).get("until")]), default=None)
                if retry and now < datetime.fromisoformat(retry):
                    stats[source] = {"status": "paused", "retry_after": retry, "error": "Pausa de solicitudes activa."}
                    continue
                last = state.get("last_scan")
                start = datetime.fromisoformat(last) - timedelta(days=settings.metadata_overlap_days) if last else now - timedelta(days=settings.initial_days)
                try:
                    categories, keywords, _, strict = settings.filters(source)
                    kwargs = {"keywords": keywords} if source == "arxiv" and strict else {}
                    papers = await self.sources[source].discover(start, now, categories, **kwargs)
                    inserted = self.db.add_papers(papers)
                    batch = papers if isinstance(papers, DiscoveryBatch) else None
                    if batch is not None:
                        inserted = list(dict.fromkeys([*batch.inserted_ids, *inserted]))
                        start = batch.start
                    candidates = [decode_paper(row) for row in self.db.rows("""SELECT p.* FROM papers p
                        WHERE p.source=? AND p.brief IS NULL AND trim(p.abstract)!='' AND NOT EXISTS
                        (SELECT 1 FROM jobs j WHERE j.paper_id=p.id AND j.kind IN ('brief','summary'))
                        AND NOT EXISTS (SELECT 1 FROM bulletin_exclusions e WHERE e.paper_id=p.id AND e.day=?)
                        AND p.updated >= ? ORDER BY p.updated DESC""", (source, day, start.isoformat().replace("+00:00", "Z")))]
                    remaining = max(0, settings.quotas()[source] - self.used_slots(day, source, settings))
                    if self.db.rows("SELECT day FROM deleted_bulletins WHERE day=?", (day,)):
                        remaining = 0
                    selected = select_candidates(candidates, settings, source, remaining)
                    complete = batch is None or batch.complete
                    cursor = batch.end if batch is not None else now
                    if complete:
                        new_state = {"last_scan": cursor.isoformat(), "last_slot": daily_slot(cursor, settings).isoformat(), "retry_after": None}
                    else:
                        new_state = {**state, "last_slot": None,
                                     "retry_after": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()}
                        new_state.pop("error", None)
                        if batch.error:
                            new_state["error"] = batch.error[:1500]
                    with self.db.connect() as conn:
                        for paper in selected:
                            conn.execute("INSERT OR IGNORE INTO bulletin VALUES(?,?)", (run_id, paper["id"]))
                            conn.execute("INSERT OR IGNORE INTO jobs(paper_id,kind,created_at,updated_at) VALUES(?,'summary',?,?)",
                                         (paper["id"], utcnow(), utcnow()))
                        updates = [(f"source:{source}", new_state)]
                        if source == "arxiv" and complete:
                            updates += [("last_scan", cursor.isoformat()), ("last_slot", daily_slot(cursor, settings).isoformat())]
                        for key, value in updates:
                            conn.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
                        conn.execute("UPDATE runs SET found=?,selected=? WHERE id=?",
                                     (found_count + len(inserted), selected_count + len(selected), run_id))
                    selected_count += len(selected)
                    found_count += len(inserted)
                    stats[source] = {"status": "completed" if complete else "partial", "found": len(inserted), "selected": len(selected)}
                    if batch is not None:
                        stats[source]["discovery"] = batch.progress
                    if not complete:
                        stats[source]["retry_after"] = new_state["retry_after"]
                        stats[source]["message"] = "Avance guardado; la búsqueda continuará desde la siguiente página."
                        if batch.error:
                            stats[source]["error"] = batch.error[:1500]
                except Exception as exc:
                    log.exception("Falló búsqueda en %s", source)
                    retry = self.db.get_meta(f"network:{source}", {}).get("until") or (now + timedelta(minutes=30)).isoformat()
                    self.db.set_meta(f"source:{source}", {**state, "last_slot": None, "retry_after": retry, "error": str(exc)[:1500]})
                    stats[source] = {"status": "error", "error": str(exc)[:1500], "retry_after": retry}
            completed = sum(info["status"] == "completed" for info in stats.values())
            useful = any(info["status"] in {"completed", "partial"} for info in stats.values())
            status = "completed" if completed == len(stats) else "partial" if useful else "error"
            errors = " · ".join(f"{name}: {info['error']}" for name, info in stats.items() if info.get("error"))
            self.db.execute("UPDATE runs SET status=?,finished_at=?,found=?,selected=?,source_stats=?,error=? WHERE id=?",
                            (status, utcnow(), found_count, selected_count, json.dumps(stats), errors or None, run_id))
        except asyncio.CancelledError:
            self.db.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE id=?", (utcnow(), run_id))
            raise
        except Exception as exc:
            log.exception("Falló búsqueda")
            self.db.execute("UPDATE runs SET status='error',finished_at=?,error=? WHERE id=?",
                             (utcnow(), str(exc)[:1500], run_id))

    def plan_summaries(self):
        """Completar el boletín vigente, no todo el archivo ni tareas canceladas."""
        settings = self.db.settings()
        # No retroceder a un boletín histórico para generar trabajo al borrar el vigente.
        runs = self.db.rows("SELECT * FROM runs WHERE selected>0 AND status IN ('completed','partial') ORDER BY id DESC LIMIT 1")
        if not runs:
            return
        day = runs[0]["bulletin_day"] or datetime.fromisoformat(runs[0]["started_at"]).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
        ids = [run["id"] for run in self.day_runs(day, settings)]
        papers = [decode_paper(row) for row in self.db.rows(f"""SELECT DISTINCT p.* FROM papers p JOIN bulletin b ON p.id=b.paper_id
            WHERE b.run_id IN ({','.join('?' for _ in ids)})""", ids)]
        papers.sort(key=lambda p: (p["brief"]["relevance"] if p["brief"] else 0, p["updated"]), reverse=True)
        for source, limit in settings.quotas().items():
            for paper in [p for p in papers if p["source"] == source][:limit]:
                if paper["brief"] and paper["overview"]:
                    continue
                if self.db.rows("SELECT id FROM jobs WHERE paper_id=? AND kind IN ('brief','overview') AND status='cancelled'", (paper["id"],)):
                    continue
                self.db.queue(paper["id"], "summary")

    async def generate_summary(self, paper, settings, progress):
        brief = paper["brief"]
        if brief is None and paper["abstract"].strip():
            progress("Evaluando afinidad y preparando el resumen del boletín")
            brief = await self.llm.brief(paper, settings)
            self.db.execute("UPDATE papers SET brief=? WHERE id=? AND brief IS NULL",
                            (json.dumps(brief, ensure_ascii=False), paper["id"]))
        overview = paper["overview"]
        if overview is None or (overview.get("scope") == "pdf_unavailable" and paper.get("pdf_url")):
            if paper.get("has_pdf", True) or (self.data_dir / "documents" / f"{paper['id']}.pdf").exists():
                overview = await article_overview(paper, settings, self.sources[paper["source"]],
                                                  self.llm, self.db, self.data_dir, progress)
            else:
                overview = {"sections": [], "support": [], "scope": "pdf_unavailable", "language": "other",
                            "coverage": {"sections_detected": 0, "sections_summarized": 0, "conclusion_detected": False},
                            "stats": {"model": settings.model}, "created_at": utcnow(),
                            "warning": "La fuente no indica un PDF disponible. No se inventaron secciones ni apoyos."}
        return brief, overview

    async def compile_interests(self, text, source="arxiv"):
        settings = self.db.settings()
        if source not in self.sources:
            raise ValueError("Fuente desconocida.")
        scope_key = json.dumps(settings.colibri_scopes) if source == "colibri" else ""
        digest = hashlib.sha256((settings.model + "\n" + source + scope_key + "\n" + text).encode()).hexdigest()
        key = f"{PROFILE_VERSION}:{digest}"
        cached = self.db.get_meta(key)
        if cached:
            return {**cached, "cached": True}
        if self.interest_task or self.current_job or (self.job_task and not self.job_task.done()):
            raise InferenceBusy("Espera a que termine la inferencia actual antes de proponer filtros.")
        # Reserva sin await: el coordinador no puede iniciar otra inferencia mientras
        # este request usa el mismo runner. No cambia los filtros activos.
        self.interest_task = asyncio.current_task()
        model_used = False
        try:
            if settings.model not in await self.llm.models():
                raise ValueError("El modelo seleccionado no está instalado en Ollama.")
            model_used = True
            if source == "colibri":
                proposal, stats = await propose_colibri_interests(self.llm, settings.model, text, settings.colibri_scopes)
            else:
                proposal, stats = await propose_interests(self.llm, settings.model, text)
            result = {"proposal": proposal, "source": source, "stats": stats, "created_at": utcnow(), "cached": False}
            self.db.set_meta(key, result)
            return result
        finally:
            try:
                if model_used:
                    try:
                        await self.llm.unload(settings.model)
                    except Exception:
                        log.exception("No se pudo liberar el modelo después de proponer filtros")
            finally:
                self.interest_task = None

    async def process_job(self, job):
        if job["kind"] == "analysis":
            self.db.execute("UPDATE jobs SET status='cancelled',progress='Análisis técnico retirado',updated_at=? WHERE id=? AND status='queued'", (utcnow(), job["id"]))
            return
        settings = self.db.settings()
        paper = self.db.paper(job["paper_id"])
        # La selección y el arranque pueden separarse por un turno del loop.
        # No iniciar un trabajo que se canceló mientras todavía estaba en cola.
        with self.db.connect() as conn:
            claimed = conn.execute("UPDATE jobs SET status='running',error=NULL,updated_at=? WHERE id=? AND status='queued'",
                                   (utcnow(), job["id"])).rowcount
        if not claimed:
            return
        self.current_job = {**job, "status": "running", "title": paper["title"]}
        model_used = False

        def progress(message):
            self.current_job["progress"] = message
            reading = re.search(r"Leyendo fragmento (\d+)/(\d+)", message)
            confirmed = re.search(r"Fragmentos confirmados (\d+)/(\d+)", message)
            if job["kind"] in {"overview", "summary"}:
                reading = re.search(r"Resumiendo sección (\d+)/(\d+)", message)
                confirmed = re.search(r"Secciones confirmadas (\d+)/(\d+)", message)
                self.current_job["progress_unit"] = "secciones"
            if reading or confirmed:
                matched = reading or confirmed
                self.current_job["progress_completed"] = max(0, int(matched[1]) - int(bool(reading)))
                self.current_job["progress_total"] = int(matched[2])
            self.db.execute("UPDATE jobs SET progress=?,updated_at=? WHERE id=?", (message, utcnow(), job["id"]))

        try:
            if settings.model not in await self.llm.models():
                raise ValueError(f"El modelo local {settings.model} no está instalado. Cámbialo en Configuración.")
            model_used = True
            if job["kind"] == "brief":
                progress("Resumiendo abstract con Ollama")
                result = await self.llm.brief(paper, settings)
                field = "brief"
            elif job["kind"] == "overview":
                result = await article_overview(paper, settings, self.sources[paper["source"]],
                                                self.llm, self.db, self.data_dir, progress)
                field = "overview"
            elif job["kind"] == "summary":
                brief, result = await self.generate_summary(paper, settings, progress)
                field = "overview"
            else:
                raise ValueError("Tipo de tarea retirado.")
            with self.db.connect() as conn:
                if job["kind"] == "summary" and brief is not None:
                    conn.execute("UPDATE papers SET brief=? WHERE id=?", (json.dumps(brief, ensure_ascii=False), paper["id"]))
                conn.execute(f"UPDATE papers SET {field}=? WHERE id=?", (json.dumps(result, ensure_ascii=False), paper["id"]))
                conn.execute("UPDATE jobs SET status='done',progress='Completado',updated_at=? WHERE id=?", (utcnow(), job["id"]))
        except asyncio.CancelledError:
            status = "queued" if self.stopping and job["id"] not in self.cancel_requested else "cancelled"
            self.db.execute("UPDATE jobs SET status=?,progress=?,updated_at=? WHERE id=?",
                            (status, "Interrumpido" if status == "queued" else "Cancelado por el usuario", utcnow(), job["id"]))
            if self.stopping:
                raise
        except Exception as exc:
            log.exception("Falló resumen de paper %s", paper["id"])
            self.db.execute("UPDATE jobs SET status='error',error=?,updated_at=? WHERE id=?", (str(exc)[:1500], utcnow(), job["id"]))
        else:
            # Ya se guardó el resultado y se confirmó 'done'. Un problema de escritorio
            # nunca debe convertir un resumen completado en un error o reencolarlo.
            # Leer la preferencia actual: puede haber cambiado durante una inferencia larga.
            if self.db.settings().desktop_notifications:
                try:
                    notification = await self.notifier.completion(
                        paper, job["kind"], partial=result.get("scope") == "partial_text")
                    self.db.set_meta("last_notification", {**notification, "at": utcnow(),
                                                          "paper_id": paper["id"], "kind": job["kind"]})
                    if notification["status"] != "sent":
                        log.warning("No se pudo enviar aviso: %s", notification.get("error"))
                except asyncio.CancelledError:
                    # El resultado sigue completado aunque se cierre el servicio al avisar.
                    if self.stopping:
                        raise
                except Exception:
                    log.exception("Error al notificar; el resultado del paper sigue guardado")
        finally:
            try:
                if model_used and self.db.settings().unload_after_paper:
                    progress("Liberando memoria de Ollama al finalizar la tarea")
                    try:
                        await self.llm.unload(settings.model)
                        self.db.set_meta("last_model_release", {"status": "released", "model": settings.model,
                                                               "at": utcnow(), "paper_id": paper["id"]})
                    except Exception as exc:
                        # El resultado ya guardado conserva su estado aunque la limpieza falle.
                        self.db.set_meta("last_model_release", {"status": "error", "model": settings.model,
                                                               "at": utcnow(), "error": str(exc)[:500]})
                        log.exception("No se pudo descargar el modelo de memoria; el resultado no cambia")
            finally:
                self.db.execute("UPDATE jobs SET progress='Completado' WHERE id=? AND status='done'", (job["id"],))
                self.db.execute("UPDATE jobs SET progress='Cancelado por el usuario' WHERE id=? AND status='cancelled'", (job["id"],))
                self.current_job = None
                self.cancel_requested.discard(job["id"])

    async def loop(self):
        while not self.stopping:
            try:
                settings = self.db.settings()
                now = datetime.now(UTC)
                due_sources = self.due_sources(now, settings)
                if settings.schedule_enabled and due_sources:
                    self.trigger("scheduled", due_sources)
                self.plan_summaries()
                if not settings.pause_summaries and not self.interest_task and (not self.job_task or self.job_task.done()):
                    jobs = self.db.rows("""SELECT * FROM jobs WHERE status='queued'
                        AND kind='summary' ORDER BY id LIMIT 1""")
                    if jobs:
                        self.job_task = asyncio.create_task(self.process_job(jobs[0]))
                # El reloj y la consulta a arXiv siguen activos durante inferencias largas.
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Error del coordinador")
                await asyncio.sleep(10)
