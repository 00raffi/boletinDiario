"""Descubrimiento público DSpace por fecha de depósito, sin scraping ni login."""
import json
import re
from datetime import UTC, datetime
from uuid import UUID

import httpx

from .colibri_catalog import effective_scopes
from .sources import Paper, RequestSource

API = "https://www.colibri.udelar.edu.uy/server/api"


def uuid(value):
    return str(UUID(value))


def values(metadata, key):
    return [item["value"].strip() for item in metadata.get(key, []) if isinstance(item.get("value"), str) and item["value"].strip()]


def parse_item(item, scope):
    if item.get("type") != "item" or item.get("withdrawn") or not item.get("inArchive") or not item.get("discoverable"):
        return None
    metadata = item.get("metadata", {})
    dates = values(metadata, "dc.date.accessioned")
    if not dates:
        raise ValueError("Colibrí devolvió un documento sin fecha de depósito; no se avanzó el cursor.")
    deposited = datetime.fromisoformat(dates[0])
    if deposited.tzinfo is None:
        raise ValueError("Fecha de depósito de Colibrí sin zona horaria.")
    deposited = deposited.astimezone(UTC).isoformat().replace("+00:00", "Z")
    identifier = uuid(item["uuid"])
    title = " ".join((values(metadata, "dc.title") or [item.get("name", "")])[0].split())
    if not title:
        raise ValueError("Colibrí devolvió un documento sin título.")
    handle = item.get("handle", "") or ""
    url = (f"https://www.colibri.udelar.edu.uy/handle/{handle}" if re.fullmatch(r"[\d.]+/\d+", handle)
           else f"https://www.colibri.udelar.edu.uy/entities/publication/{identifier}")
    abstracts = values(metadata, "dc.description.abstract")
    # Si hay varios idiomas no juntar traducciones. Elegir el abstract acorde a
    # dc.language.iso, y en ausencia de esa marca usar el primero disponible.
    language = (values(metadata, "dc.language.iso") or [""])[0].lower()
    matching = [v["value"] for v in metadata.get("dc.description.abstract", [])
                if v.get("language") and language.startswith(v["language"].lower()) and v.get("value")]
    return Paper(source="colibri", external_id=identifier, version="1", title=title,
                 authors=values(metadata, "dc.contributor.author"), abstract=(matching or abstracts or [""])[0],
                 published=(values(metadata, "dc.date.issued") or [""])[0], updated=deposited,
                 categories=[scope, *values(metadata, "dc.subject")[:15]], url=url, pdf_url="",
                 document_type=(values(metadata, "dc.type") or [""])[0],
                 has_pdf="application/pdf" in values(metadata, "dc.format.mimetype"))


def suitable_for_analysis(paper):
    """Elegibilidad conservadora, no ranking científico ni garantía de PDF legible."""
    if not paper.get("has_pdf", True) or len(paper.get("abstract", "").strip()) < 50:
        return False
    if paper["source"] == "arxiv":
        return True
    kind = paper.get("document_type", "").casefold()
    return any(term in kind for term in ("tesis", "artículo", "article", "informe", "report", "trabajo", "conference", "preprint", "ponencia"))


class ColibriSource(RequestSource):
    name = "colibri"

    async def json(self, client, path, *, params=None, purpose="metadata"):
        return json.loads(await self.get(client, API + path, params=params, purpose=purpose))

    async def browse(self, parent=None):
        parent = uuid(parent) if parent else None
        key = f"colibri-catalog:v2:{parent or 'top'}"
        cached = self.db.get_meta(key) if self.db else None
        if cached and (datetime.now(UTC) - datetime.fromisoformat(cached["at"])).total_seconds() < 86400:
            return cached["entries"]
        paths = [(f"/core/communities/{parent}/subcommunities", "communities"),
                 (f"/core/communities/{parent}/collections", "collections")] if parent else [
                     ("/core/communities/search/top", "communities")]
        entries = []
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            for path, kind in paths:
                for page in range(3):
                    data = await self.json(client, path, params={"size": 100, "page": page}, purpose="catalog")
                    embedded_key = "subcommunities" if path.endswith("/subcommunities") else kind
                    entries += [{"uuid": uuid(item["uuid"]), "name": item["name"], "kind": kind}
                                for item in data.get("_embedded", {}).get(embedded_key, [])]
                    if page + 1 >= data.get("page", {}).get("totalPages", 1):
                        break
                else:
                    raise ValueError("Demasiadas comunidades/colecciones en este nivel; no se mostró una lista incompleta.")
        if self.db:
            self.db.set_meta(key, {"at": datetime.now(UTC).isoformat(), "entries": entries})
        return entries

    async def discover(self, start, end, categories, *, keywords=()):
        papers, seen = [], set()
        requests = 0
        async with httpx.AsyncClient(timeout=60, trust_env=False, headers={"User-Agent": "PersonalResearchReader/0.2"}) as client:
            for scope in effective_scopes(categories):
                scope = uuid(scope)
                previous_date = None
                for page in range(50):
                    if requests >= 50:
                        raise ValueError("Colibrí: límite de 50 consultas alcanzado. Reduce periodo o comunidades; cursor sin avanzar.")
                    requests += 1
                    data = await self.json(client, "/discover/search/objects", params={
                        # Algunas comunidades (p. ej. Convenios) usan una configuración
                        # propia que rechaza este orden. La pública default sí lo ofrece;
                        # se conserva el scope y se verifica el orden de la respuesta.
                        "scope": scope, "configuration": "default",
                        "sort": "dc.date.accessioned,DESC", "page": page, "size": 100,
                    })
                    if data.get("sort") != {"by": "dc.date.accessioned", "order": "DESC"}:
                        raise ValueError("Colibrí no confirmó el orden por depósito; cursor sin avanzar.")
                    result = data["_embedded"]["searchResult"]
                    objects = result.get("_embedded", {}).get("objects", [])
                    reached_start = False
                    for obj in objects:
                        item = parse_item(obj["_embedded"]["indexableObject"], scope)
                        if item is None:
                            continue
                        deposited = datetime.fromisoformat(item.updated)
                        if previous_date and deposited > previous_date:
                            raise ValueError("Colibrí devolvió depósitos fuera de orden; cursor sin avanzar.")
                        previous_date = deposited
                        if deposited < start:
                            reached_start = True
                        elif deposited <= end and item.external_id not in seen:
                            papers.append(item)
                            seen.add(item.external_id)
                        elif item.external_id in seen:
                            existing = next(p for p in papers if p.external_id == item.external_id)
                            if scope not in existing.categories:
                                existing.categories.append(scope)
                    if reached_start or not objects or page + 1 >= result["page"]["totalPages"]:
                        break
                else:
                    raise ValueError("Colibrí: demasiados metadatos; cursor sin avanzar.")
        return sorted(papers, key=lambda paper: paper.updated, reverse=True)

    async def resolve_pdf(self, paper):
        """Resolver enlace, sin descargar el contenido ni usar el modelo."""
        cached = paper.get("pdf_url", "")
        if re.fullmatch(re.escape(API) + r"/core/bitstreams/[a-f0-9-]{36}/content", cached):
            return cached, None
        identifier = uuid(paper["external_id"])
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            bundles = await self.json(client, f"/core/items/{identifier}/bundles", params={"size": 20}, purpose="pdf-metadata")
            if bundles.get("page", {}).get("totalPages", 1) > 1:
                raise ValueError("Colibrí: demasiados paquetes de archivos; requiere selección manual.")
            candidates, primary_ids = [], []
            for bundle in bundles.get("_embedded", {}).get("bundles", []):
                if bundle["name"] != "ORIGINAL":
                    continue
                bundle_id = uuid(bundle["uuid"])
                files = await self.json(client, f"/core/bundles/{bundle_id}/bitstreams", params={"size": 50}, purpose="pdf-metadata")
                if files.get("page", {}).get("totalPages", 1) > 1:
                    raise ValueError("Colibrí: demasiados archivos; requiere selección manual.")
                candidates += [b for b in files.get("_embedded", {}).get("bitstreams", [])
                               if b.get("name", "").lower().endswith(".pdf") and b.get("bundleName") == "ORIGINAL"]
                if len(candidates) > 1:
                    try:
                        primary = await self.json(client, f"/core/bundles/{bundle_id}/primaryBitstream", purpose="pdf-metadata")
                        primary_ids.append(uuid(primary["uuid"]))
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
            unique = {uuid(b["uuid"]): b for b in candidates}
            chosen = [identifier for identifier in primary_ids if identifier in unique]
            if len(unique) == 1:
                chosen = list(unique)
            if len(chosen) != 1:
                raise ValueError("Colibrí: no hay un único PDF principal público identificable. Consulta la ficha original.")
            bitstream = unique[chosen[0]]
            url = f"{API}/core/bitstreams/{chosen[0]}/content"
            paper["pdf_url"] = url
            paper["has_pdf"] = True
            if self.db and paper.get("id"):
                self.db.execute("UPDATE papers SET pdf_url=?,has_pdf=1 WHERE id=?", (url, paper["id"]))
            return url, bitstream.get("sizeBytes", 0)

    async def document(self, paper):
        url, size = await self.resolve_pdf(paper)
        limit = self.pdf_limit
        if size and size > limit:
            raise ValueError(f"PDF de Colibrí de {size / 1_000_000:.2f} MB; supera el límite de {limit / 1_000_000:g} MB. No se descargó.")
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            body = await self.get(client, url, limit=limit, purpose="pdf")
            if not body.startswith(b"%PDF-"):
                raise ValueError("Colibrí no devolvió un PDF público. No se intentará iniciar sesión.")
            paper["pdf_url"] = url
            return body
