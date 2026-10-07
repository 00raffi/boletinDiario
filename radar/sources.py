"""Contrato independiente de fuentes: Colibrí podrá implementar este mismo protocolo."""
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree

from .catalog import valid_categories
from .db import utcnow

ATOM = "{http://www.w3.org/2005/Atom}"
OPEN = "{http://a9.com/-/spec/opensearch/1.1/}"
ID_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})v(\d+)$")
PUBLIC_HOSTS = {"export.arxiv.org", "arxiv.org", "www.arxiv.org", "www.colibri.udelar.edu.uy"}


@dataclass
class Paper:
    source: str
    external_id: str
    version: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    url: str
    pdf_url: str
    document_type: str = ""
    has_pdf: bool = True


class Source(Protocol):
    name: str

    async def discover(self, start: datetime, end: datetime, categories: list[str], *, keywords=()) -> list[Paper]: ...

    async def document(self, paper: dict) -> bytes: ...


def validate_public_url(url: str, hosts=PUBLIC_HOSTS):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts or
            parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Destino de descarga no autorizado.")


async def bounded_get(client, url, *, params=None, limit=4_000_000, before=None, record=None, hosts=PUBLIC_HOSTS,
                      headers_only=False):
    """Solo destinos definidos en código; no sigue redirecciones a hosts desconocidos."""
    for _ in range(4):
        validate_public_url(url, hosts)
        if before:
            await before()
        async with client.stream("HEAD" if headers_only else "GET", url, params=params) as response:
            if record:
                record(response)
            if response.is_redirect:
                url = str(response.url.join(response.headers["location"]))
                params = None
                continue
            response.raise_for_status()
            if headers_only:
                return dict(response.headers)
            length = int(response.headers.get("content-length", "0"))
            if length > limit:
                raise ValueError(f"Documento de {length / 1_000_000:.2f} MB; supera el límite de {limit / 1_000_000:g} MB.")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise ValueError(f"La descarga superó el límite de {limit / 1_000_000:g} MB y se detuvo.")
            return bytes(body)
    raise ValueError("Demasiadas redirecciones.")


def parse_feed(data: bytes):
    root = ElementTree.fromstring(data)
    total = int(root.findtext(f"{OPEN}totalResults", "0"))
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = entry.findtext(f"{ATOM}id", "").split("/abs/")[-1]
        match = ID_RE.fullmatch(raw_id)
        if not match:
            raise ValueError("arXiv devolvió una entrada de error o un identificador inesperado.")
        external_id, version = match.groups()
        papers.append(Paper(
            source="arxiv", external_id=external_id, version=version,
            title=" ".join(entry.findtext(f"{ATOM}title", "").split()),
            authors=[author.findtext(f"{ATOM}name", "") for author in entry.findall(f"{ATOM}author")],
            abstract=" ".join(entry.findtext(f"{ATOM}summary", "").split()),
            published=entry.findtext(f"{ATOM}published", ""),
            updated=entry.findtext(f"{ATOM}updated", ""),
            categories=[cat.attrib["term"] for cat in entry.findall(f"{ATOM}category")],
            url=f"https://arxiv.org/abs/{external_id}v{version}",
            pdf_url=f"https://arxiv.org/pdf/{external_id}v{version}",
        ))
    return papers, total


def search_queries(categories, keywords=()):
    categories = valid_categories(categories)
    if not categories:
        raise ValueError("Selecciona al menos una categoría.")
    base = "(" + " OR ".join(f"cat:{cat}" for cat in categories) + ")"
    if not keywords:
        return [base]
    # Solo frases entre comillas: los términos del modelo nunca son consultas libres.
    clauses = []
    for term in keywords:
        phrase = " ".join(term.replace('"', " ").replace("\\", " ").split())
        if not phrase:
            raise ValueError("Un término de búsqueda está vacío.")
        clauses.append(f'(ti:"{phrase}" OR abs:"{phrase}")')
    queries, batch = [], []
    for clause in clauses:
        if len(base) + len(" OR ".join([*batch, clause])) > 3500 and batch:
            queries.append(base + " AND (" + " OR ".join(batch) + ")")
            batch = []
        batch.append(clause)
    queries.append(base + " AND (" + " OR ".join(batch) + ")")
    return queries


class DiscoveryBatch(list):
    """Páginas útiles incluso cuando el presupuesto obliga a continuar después."""

    def __init__(self, papers, *, complete, start, end, inserted_ids, progress, error=None):
        super().__init__(papers)
        self.complete, self.start, self.end = complete, start, end
        self.inserted_ids, self.progress, self.error = inserted_ids, progress, error


class RequestSource:
    def __init__(self, db=None):
        self.last_request = 0.0
        self.db = db
        self.request_lock = asyncio.Lock()

    @property
    def pdf_limit(self):
        return (self.db.settings().max_pdf_mb if self.db else 100) * 1_000_000

    async def head(self, client, url):
        """Consultar cabeceras sin descargar contenido, con las mismas pausas y registro."""
        return await self.get(client, url, purpose="pdf-size", headers_only=True)

    async def pace(self):
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0, 3.1 - (loop.time() - self.last_request)))
        self.last_request = loop.time()

    async def get(self, client, url, *, params=None, limit=4_000_000, purpose="metadata", headers_only=False):
        async with self.request_lock:
            request_id = None

            async def before():
                nonlocal request_id
                cooldown = self.db.get_meta(f"network:{self.name}", {}) if self.db else {}
                if cooldown.get("until") and datetime.now(UTC) < datetime.fromisoformat(cooldown["until"]):
                    raise ValueError(f"{self.name}: pausa por límite de solicitudes hasta {cooldown['until']}.")
                await self.pace()
                if self.db:
                    request_id = self.db.execute("INSERT INTO source_requests(source,started_at,purpose) VALUES(?,?,?)",
                                                 (self.name, utcnow(), purpose))

            def record(response):
                if not self.db:
                    return
                retry = response.headers.get("retry-after")
                self.db.execute("UPDATE source_requests SET status=?,retry_after=? WHERE id=?",
                                (response.status_code, retry, request_id))
                if response.status_code in {429, 503}:
                    previous = self.db.get_meta(f"network:{self.name}", {})
                    failures = min(previous.get("failures", 0) + 1, 8)
                    until = datetime.now(UTC) + timedelta(minutes=min(1440, 30 * 2 ** (failures - 1)))
                    if retry:
                        try:
                            advised = (datetime.now(UTC) + timedelta(seconds=max(0, int(retry)))
                                       if retry.isdigit() else parsedate_to_datetime(retry).astimezone(UTC))
                            until = max(until, advised)
                        except (ValueError, TypeError, OverflowError):
                            pass
                    self.db.set_meta(f"network:{self.name}", {"until": until.isoformat(), "failures": failures})
                elif response.is_success:
                    self.db.set_meta(f"network:{self.name}", {})

            hosts = {"www.colibri.udelar.edu.uy"} if self.name == "colibri" else {"arxiv.org", "export.arxiv.org", "www.arxiv.org"}
            return await bounded_get(client, url, params=params, limit=limit, before=before, record=record, hosts=hosts,
                                     headers_only=headers_only)


class ArxivSource(RequestSource):
    name = "arxiv"
    checkpoint_key = "discovery:arxiv"
    category_group_size = 8
    # Pasadas cortas: publicar resultados útiles sin recorrer miles de metadatos
    # en una sola ejecución. El resto continúa con la pausa del coordinador.
    request_budget = 10
    page_size = 100

    @staticmethod
    def discovery_progress(state):
        return {"complete": state["complete"], "start": state["start"], "end": state["end"],
                "pages": state["pages"], "saved": state["saved"], "groups": len(state["units"]),
                "completed_groups": sum(unit["done"] for unit in state["units"]),
                "next_offset": state["units"][state["next"]]["offset"]}

    def save_page(self, papers, state):
        if self.db:
            # Las filas y su punto de continuación se confirman juntas.
            with self.db.connect() as conn:
                inserted = self.db.add_papers(papers, connection=conn)
                state["saved"] += len(inserted)
                conn.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (self.checkpoint_key, json.dumps(state)))
            return inserted
        self._checkpoint = json.loads(json.dumps(state))
        return []

    async def discover(self, start, end, categories, *, keywords=()):
        # Filtrar por última actualización incluye versiones nuevas de papers antiguos.
        categories = sorted(valid_categories(categories))
        queries = [query for offset in range(0, len(categories), self.category_group_size)
                   for query in search_queries(categories[offset:offset + self.category_group_size], keywords)]
        if not queries:
            raise ValueError("Selecciona al menos una categoría.")
        signature = hashlib.sha256(json.dumps(["arxiv-paging-v1", queries, self.page_size]).encode()).hexdigest()
        state = self.db.get_meta(self.checkpoint_key) if self.db else getattr(self, "_checkpoint", None)
        if not state or state["signature"] != signature or state["complete"]:
            state = {"signature": signature, "start": start.isoformat(), "end": end.isoformat(),
                     "complete": False, "next": 0, "pages": 0, "saved": 0,
                     "units": [{"query": query, "offset": 0, "done": False, "last_page": None} for query in queries]}
        # El intervalo pendiente permanece fijo aunque pase tiempo entre continuaciones.
        start, end = datetime.fromisoformat(state["start"]), datetime.fromisoformat(state["end"])
        papers, seen, inserted_ids = [], set(), []
        requests = 0
        error = None
        async with httpx.AsyncClient(timeout=60, trust_env=False,
                                     headers={"User-Agent": "boletinDiario/0.1 (personal local reader)"}) as client:
            while not state["complete"] and requests < self.request_budget:
                unit = state["units"][state["next"]]
                try:
                    requests += 1
                    data = await self.get(client, "https://export.arxiv.org/api/query", params={
                        "search_query": unit["query"], "sortBy": "lastUpdatedDate", "sortOrder": "descending",
                        "start": unit["offset"], "max_results": self.page_size,
                    })
                    page, total = parse_feed(data)
                    root = ElementTree.fromstring(data)
                    index = root.findtext(f"{OPEN}startIndex")
                    if index is not None and int(index) != unit["offset"]:
                        raise ValueError("arXiv devolvió una página distinta de la solicitada; se conserva el punto de continuación.")
                    digest = hashlib.sha256(json.dumps([(p.external_id, p.version) for p in page]).encode()).hexdigest()
                    if page and digest == unit["last_page"]:
                        raise ValueError("arXiv repitió la página anterior; se conserva el punto de continuación.")
                    eligible = []
                    for paper in page:
                        updated = datetime.fromisoformat(paper.updated)
                        identifier = (paper.external_id, paper.version)
                        if start <= updated <= end and identifier not in seen:
                            eligible.append(paper)
                            seen.add(identifier)
                    next_state = json.loads(json.dumps(state))
                    unit = next_state["units"][next_state["next"]]
                    unit["done"] = (not page or any(datetime.fromisoformat(p.updated) < start for p in page)
                                    or unit["offset"] + len(page) >= total)
                    unit["offset"] += len(page)
                    unit["last_page"] = digest
                    next_state["pages"] += 1
                    # Una página por grupo antes de volver al primero: no monopolizar
                    # el presupuesto con las categorías más voluminosas.
                    pending = [(next_state["next"] + step) % len(next_state["units"]) for step in range(1, len(next_state["units"]) + 1)
                               if not next_state["units"][(next_state["next"] + step) % len(next_state["units"])]["done"]]
                    next_state["complete"] = not pending
                    if pending:
                        next_state["next"] = pending[0]
                    inserted_ids.extend(self.save_page(eligible, next_state))
                    state = next_state
                    papers.extend(eligible)
                except (httpx.HTTPError, ValueError) as exc:
                    if not state["pages"]:
                        raise
                    error = str(exc)
                    break
        return DiscoveryBatch(sorted(papers, key=lambda paper: paper.updated, reverse=True),
                              complete=state["complete"], start=start, end=end, inserted_ids=inserted_ids,
                              progress=self.discovery_progress(state), error=error)

    async def document(self, paper):
        # Reconstruir el destino: nunca confiar en enlaces proporcionados por el modelo.
        identifier = f"{paper['external_id']}v{paper['version']}"
        if not ID_RE.fullmatch(identifier):
            raise ValueError("Identificador de arXiv no válido.")
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            body = await self.get(client, f"https://arxiv.org/pdf/{identifier}", limit=self.pdf_limit, purpose="pdf")
        if not body.startswith(b"%PDF-"):
            raise ValueError("La respuesta no es un PDF.")
        return body


SOURCES = {"arxiv": ArxivSource}
