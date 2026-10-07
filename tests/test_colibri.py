import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from radar.app import create_app
from radar.colibri import ColibriSource, parse_item
from radar.colibri_catalog import FING, INCO
from radar.config import Settings
from radar.db import Database, utcnow
from radar.engine import Engine, select_candidates
from radar.interests import TermProposal
from radar.llm import Ollama
from radar.sources import ArxivSource

ITEM = "101566c7-df87-448d-b63f-4f7e17371815"
BUNDLE = "cddb47ae-d041-48e4-9f7b-3b3bda361ec0"
PDF = "c9d00707-b629-47a4-9893-20bbf246110f"


def item(identifier=ITEM, deposited=None):
    return {"uuid": identifier, "type": "item", "inArchive": True, "discoverable": True,
            "handle": "20.500.12008/56792", "metadata": {
                "dc.title": [{"value": "Aprendizaje de robots"}],
                "dc.description.abstract": [{"value": "En este artículo se presenta un método de aprendizaje para robots y se evalúan sus resultados."}],
                "dc.date.accessioned": [{"value": deposited or utcnow()}],
                "dc.date.issued": [{"value": "2021"}], "dc.type": [{"value": "Tesis de grado"}],
                "dc.subject": [{"value": "Robótica"}], "dc.format.mimetype": [{"value": "application/pdf"}]}}


def install_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr("radar.sources.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def enable(db):
    data = db.settings().model_dump()
    data["colibri_enabled"] = True
    db.set_meta("settings", data)


def papers(sample, source, count):
    return [replace(sample, source=source, external_id=f"{source}-{i}", categories=[FING] if source == "colibri" else ["cs.AI"],
                    abstract=sample.abstract + " The results are preliminary.",
                    document_type="Tesis de grado" if source == "colibri" else "", updated=utcnow()) for i in range(count)]


def test_metadata_uses_deposit_date_not_publication_year_and_preserves_absence():
    original = item(deposited="2026-10-02T18:04:44Z")
    parsed = parse_item(original, FING)
    assert parsed.published == "2021"
    assert parsed.updated == "2026-10-02T18:04:44Z"
    assert parsed.external_id == ITEM and parsed.document_type == "Tesis de grado"
    assert parsed.pdf_url == "" and parsed.has_pdf
    original["metadata"].pop("dc.description.abstract")
    assert parse_item(original, FING).abstract == ""
    original["withdrawn"] = True
    assert parse_item(original, FING) is None


def test_bilingual_metadata_chooses_language_without_combining_abstracts():
    data = item()
    data["metadata"]["dc.language.iso"] = [{"value": "es"}]
    data["metadata"]["dc.description.abstract"] = [{"value": "English abstract", "language": "en"},
                                                      {"value": "Resumen español", "language": "es"}]
    assert parse_item(data, FING).abstract == "Resumen español"


def test_fing_includes_inco_and_discovery_stops_at_old_deposits(monkeypatch):
    calls = []
    now = datetime.now(UTC)

    def handler(request):
        calls.append(request)
        entries = [item(deposited=(now - timedelta(days=1)).isoformat()),
                   item("1930ee3b-c69b-41df-bbb7-e4a91f5d67ae", (now - timedelta(days=20)).isoformat())]
        return httpx.Response(200, json={"sort": {"by": "dc.date.accessioned", "order": "DESC"}, "_embedded": {
            "searchResult": {"_embedded": {"objects": [{"_embedded": {"indexableObject": i}} for i in entries]},
                             "page": {"totalPages": 30}}}})

    install_transport(monkeypatch, handler)
    source = ColibriSource()
    source.pace = AsyncMock()
    found = asyncio.run(source.discover(now - timedelta(days=7), now, [FING, INCO]))
    assert len(calls) == 1 and len(found) == 1
    assert calls[0].url.params["scope"] == FING
    assert found[0].published == "2021"


def test_colibri_refuses_unconfirmed_incremental_order(monkeypatch):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json={"sort": {"by": "score", "order": "DESC"}}))
    source = ColibriSource()
    source.pace = AsyncMock()
    with pytest.raises(ValueError, match="orden"):
        asyncio.run(source.discover(datetime.now(UTC)-timedelta(days=7), datetime.now(UTC), [FING]))


def test_scopes_with_custom_search_configuration_use_public_default_without_changing_scope(monkeypatch):
    convenios = "f1de19bf-63a3-4af8-b929-9ecb4e030054"
    calls = []
    now = datetime.now(UTC)

    def handler(request):
        calls.append(request)
        if request.url.params.get("configuration") != "default":
            return httpx.Response(422, json={"message": "Invalid search request"})
        return httpx.Response(200, json={"sort": {"by": "dc.date.accessioned", "order": "DESC"}, "_embedded": {
            "searchResult": {"_embedded": {"objects": [{"_embedded": {"indexableObject": item(deposited=(now-timedelta(hours=1)).isoformat())}}]},
                             "page": {"totalPages": 1}}}})

    install_transport(monkeypatch, handler)
    source = ColibriSource()
    source.pace = AsyncMock()
    result = asyncio.run(source.discover(now-timedelta(days=7), now, [convenios]))
    assert len(calls) == 1 and len(result) == 1
    assert calls[0].url.params["scope"] == convenios
    assert result[0].categories[0] == convenios


@pytest.mark.parametrize("failure", [None, "restricted", "ambiguous", "oversized", "redirect"])
def test_pdf_resolution_uses_only_original_bundles_and_public_official_content(monkeypatch, failure):
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/bundles"):
            return httpx.Response(200, json={"_embedded": {"bundles": [{"uuid": BUNDLE, "name": "ORIGINAL"},
                                                                       {"uuid": PDF, "name": "THUMBNAIL"}]}})
        if path.endswith("/bitstreams"):
            files = [{"uuid": PDF, "name": "tesis.pdf", "bundleName": "ORIGINAL", "sizeBytes": 120_000_000 if failure == "oversized" else 100}]
            if failure == "ambiguous":
                files.append({"uuid": ITEM, "name": "anexo.pdf", "bundleName": "ORIGINAL"})
            return httpx.Response(200, json={"_embedded": {"bitstreams": files}})
        if path.endswith("/primaryBitstream"):
            return httpx.Response(404)
        if failure == "restricted":
            return httpx.Response(401)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.com/private.pdf"})
        return httpx.Response(200, content=b"%PDF-1.7 sample")

    install_transport(monkeypatch, handler)
    source = ColibriSource()
    source.pace = AsyncMock()
    paper = {"external_id": ITEM, "pdf_url": "https://example.com/malicious"}
    if failure:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            asyncio.run(source.document(paper))
    else:
        assert asyncio.run(source.document(paper)).startswith(b"%PDF-")
        assert paper["pdf_url"].endswith(f"/{PDF}/content")
    assert all(request.url.host == "www.colibri.udelar.edu.uy" for request in requests)


def test_source_filters_are_independent_and_marks_are_not_selection_feedback(sample):
    settings = Settings(colibri_enabled=True, keywords=["agents"], colibri_keywords=["robots"], colibri_keyword_filter=True)
    p = {"source": "colibri", "categories": [FING], "title": "Robots", "abstract": "Método técnico", "updated": utcnow(), "document_type": "Tesis de grado"}
    assert select_candidates([{**p, "interest": -1}], settings, "colibri")
    assert not select_candidates([{**p, "title": "Agents"}], settings, "colibri")
    assert not select_candidates([p], Settings(colibri_enabled=True, colibri_types=["Artículo"]), "colibri")


def test_daily_source_quotas_survive_repeated_scans_and_no_abstract_is_library_only(db, sample, tmp_path):
    async def run():
        enable(db)
        engine = Engine(db, tmp_path)
        arxiv = papers(sample, "arxiv", 6)
        colibri = papers(sample, "colibri", 12)
        colibri.append(replace(colibri[0], external_id="no-abstract", abstract=""))
        engine.sources["arxiv"] = type("Source", (), {"discover": AsyncMock(return_value=arxiv)})()
        engine.sources["colibri"] = type("Source", (), {"discover": AsyncMock(return_value=colibri)})()
        await engine.scan("manual")
        assert db.rows("SELECT source,count(*) AS n FROM papers JOIN bulletin ON papers.id=bulletin.paper_id GROUP BY source") == [
            {"source": "arxiv", "n": 2}, {"source": "colibri", "n": 8}]
        assert len(db.rows("SELECT * FROM papers")) == 19
        assert len(db.rows("SELECT * FROM jobs")) == 10
        await engine.scan("manual")
        assert len(db.rows("SELECT * FROM jobs")) == 10
        assert db.rows("SELECT selected FROM runs ORDER BY id") == [{"selected": 10}, {"selected": 0}]
    asyncio.run(run())


def test_failure_of_arxiv_keeps_colibri_bulletin_and_independent_cursors(db, sample, tmp_path):
    async def run():
        enable(db)
        engine = Engine(db, tmp_path)
        engine.sources["arxiv"] = type("Source", (), {"discover": AsyncMock(side_effect=ValueError("arXiv 429"))})()
        engine.sources["colibri"] = type("Source", (), {"discover": AsyncMock(return_value=papers(sample, "colibri", 8))})()
        await engine.scan("manual")
        assert db.rows("SELECT status,selected FROM runs")[0] == {"status": "partial", "selected": 8}
        assert engine.source_state("colibri")["last_scan"]
        assert not engine.source_state("arxiv").get("last_scan")
        assert engine.source_state("arxiv")["retry_after"]
    asyncio.run(run())


def test_every_selected_paper_has_one_summary_and_no_technical_job(db, sample, tmp_path):
    async def run():
        enable(db)
        engine = Engine(db, tmp_path)
        documents = papers(sample, "colibri", 6)
        documents[0] = replace(documents[0], document_type="Programa de curso")
        documents[1] = replace(documents[1], has_pdf=False)
        engine.sources["arxiv"] = type("Source", (), {"discover": AsyncMock(return_value=papers(sample, "arxiv", 4))})()
        engine.sources["colibri"] = type("Source", (), {"discover": AsyncMock(return_value=documents)})()
        await engine.scan("manual")
        db.execute("UPDATE jobs SET status='done'")
        db.execute("UPDATE papers SET brief=?", (json.dumps({"summary": "Resumen", "relevance": 4}),))
        engine.plan_summaries()
        planned = db.rows("SELECT p.source,p.document_type,p.has_pdf FROM jobs j JOIN papers p ON p.id=j.paper_id WHERE j.kind='summary'")
        assert sum(p["source"] == "arxiv" for p in planned) == 2
        assert sum(p["source"] == "colibri" for p in planned) == 6
        engine.plan_summaries()
        assert len(db.rows("SELECT * FROM jobs WHERE kind='summary'")) == 8
        assert db.rows("SELECT * FROM jobs WHERE kind='analysis'") == []
    asyncio.run(run())


@pytest.mark.parametrize("mark", [-1, 1])
def test_interest_mark_stays_in_bulletin_and_preserves_library_jobs_and_results(tmp_path, sample, mark):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    paper_id = db.add_papers([sample])[0]
    run_id = db.execute("INSERT INTO runs(started_at,status,reason,selected) VALUES(?,'completed','manual',1)", (utcnow(),))
    db.execute("INSERT INTO bulletin VALUES(?,?)", (run_id, paper_id))
    db.execute("UPDATE papers SET brief=? WHERE id=?", (json.dumps({"summary": "Anterior", "relevance": 3}), paper_id))
    db.queue(paper_id, "analysis")
    db.execute("UPDATE jobs SET status='cancelled'")
    with TestClient(app, base_url="http://localhost") as client:
        assert len(client.get("/api/bulletin").json()["papers"]) == 1
        assert client.patch(f"/api/papers/{paper_id}", json={"interest": mark}, headers={"X-Radar-Request": "1"}).status_code == 200
        bulletin = client.get("/api/bulletin").json()
        assert len(bulletin["papers"]) == 1 and bulletin["papers"][0]["interest"] == mark
        assert bulletin["marked_count"] == 1 and bulletin["hidden_count"] == 0
        state = "interested" if mark == 1 else "not_interested"
        library = client.get(f"/api/papers?state={state}&source=arxiv").json()
        assert library["total"] == 1 and library["papers"][0]["brief"]["summary"] == "Anterior"
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "cancelled"
        assert client.patch(f"/api/papers/{paper_id}", json={"interest": 0}, headers={"X-Radar-Request": "1"}).status_code == 200
        assert len(client.get("/api/bulletin").json()["papers"]) == 1
        assert client.patch(f"/api/papers/{paper_id}", json={"interest": 9}, headers={"X-Radar-Request": "1"}).status_code == 422


def test_interest_marks_never_reach_brief_prompt():
    async def run():
        llm = Ollama()
        llm.generate = AsyncMock(return_value=({"summary": "Example"}, {}))
        paper = {"source": "colibri", "title": "Robots", "abstract": "We evaluate the method on synthetic tasks."}
        await llm.brief({**paper, "interest": -1}, Settings(colibri_keywords=["robots"]))
        first = llm.generate.call_args.args[1]
        await llm.brief({**paper, "interest": 1}, Settings(colibri_keywords=["robots"]))
        assert first == llm.generate.call_args.args[1]
        assert "robots" in first and "cs.AI" not in first
    asyncio.run(run())


def test_network_count_retry_after_and_cooldown_prevent_another_request(db, monkeypatch):
    count = []
    install_transport(monkeypatch, lambda request: (count.append(request) or httpx.Response(429, headers={"Retry-After": "7200"})))
    source = ArxivSource(db=db)
    source.pace = AsyncMock()

    async def run():
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await source.get(client, "https://export.arxiv.org/api/query")
            with pytest.raises(ValueError, match="pausa"):
                await source.get(client, "https://export.arxiv.org/api/query")
    asyncio.run(run())
    assert len(count) == 1
    assert db.rows("SELECT source,status,retry_after FROM source_requests") == [{"source": "arxiv", "status": 429, "retry_after": "7200"}]
    assert datetime.fromisoformat(db.get_meta("network:arxiv")["until"]) > datetime.now(UTC) + timedelta(minutes=119)


def test_catalog_is_explicit_cached_and_source_proposals_stay_separate(db, monkeypatch, tmp_path):
    calls = []
    install_transport(monkeypatch, lambda request: (calls.append(request) or httpx.Response(200, json={"_embedded": {
        "communities": [{"uuid": FING, "name": "Facultad de Ingeniería"}]}})))
    source = ColibriSource(db=db)
    source.pace = AsyncMock()

    async def run():
        assert (await source.browse())[0]["uuid"] == FING
        assert (await source.browse())[0]["uuid"] == FING
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        engine.llm.generate = AsyncMock(return_value=({"interests": [{"topic": "Robótica", "source_text": "robots", "keywords": ["robots"]}],
            "explanation": "Términos para buscar trabajos de robótica.", "warnings": []}, {}))
        engine.llm.unload = AsyncMock()
        result = await engine.compile_interests("Me interesan los robots", "colibri")
        assert result["source"] == "colibri" and "categories" not in result["proposal"]
        assert engine.llm.generate.call_args.args[2] is TermProposal
        assert db.settings().colibri_keywords == []
    asyncio.run(run())
    assert len(calls) == 1


def test_additive_migration_keeps_old_result_and_cancelled_job(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE papers(id INTEGER PRIMARY KEY, source TEXT, external_id TEXT,version TEXT,
            title TEXT, authors TEXT, abstract TEXT,published TEXT,updated TEXT,categories TEXT,url TEXT,pdf_url TEXT,
            discovered_at TEXT,is_revision INTEGER DEFAULT 0,favorite INTEGER DEFAULT 0,is_read INTEGER DEFAULT 0,
            brief TEXT,analysis TEXT,UNIQUE(source,external_id,version))""")
        conn.execute("INSERT INTO papers(id,source,external_id,version,authors,categories,brief) VALUES(1,'arxiv','test','1','[]','[]',?)",
                     ('{"summary":"Anterior"}',))
    db = Database(path)
    db.queue(1, "analysis")
    db.execute("UPDATE jobs SET status='cancelled'")
    db = Database(path)
    assert db.paper(1)["interest"] == 0 and db.paper(1)["brief"]["summary"] == "Anterior"
    assert db.rows("SELECT status FROM jobs")[0]["status"] == "cancelled"


def test_settings_change_resets_only_that_source_and_does_not_clear_network_pause(tmp_path):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    db.set_meta("source:arxiv", {"last_scan": utcnow(), "last_slot": "today"})
    db.set_meta("source:colibri", {"last_scan": utcnow(), "last_slot": "today"})
    db.set_meta("network:colibri", {"until": "2099-01-01T00:00:00+00:00", "failures": 1})
    arxiv = db.get_meta("source:arxiv")
    with TestClient(app, base_url="http://localhost") as client:
        settings = client.get("/api/settings").json()
        settings["colibri_scopes"] = [INCO]
        assert client.put("/api/settings", json=settings, headers={"X-Radar-Request": "1"}).status_code == 200
        assert db.get_meta("source:arxiv") == arxiv
        assert db.get_meta("source:colibri")["last_scan"] is None
        assert db.get_meta("network:colibri")["failures"] == 1


def test_network_pause_excludes_source_from_scheduler_even_before_first_scan(db, tmp_path):
    enable(db)
    engine = Engine(db, tmp_path)
    db.set_meta("network:colibri", {"until": (datetime.now(UTC)+timedelta(hours=2)).isoformat()})
    assert engine.due_sources(datetime.now(UTC), db.settings()) == ["arxiv"]


def test_catalog_includes_dspace_subcommunities_relation_and_collections(db, monkeypatch):
    def handler(request):
        if request.url.path.endswith("/subcommunities"):
            return httpx.Response(200, json={"_embedded": {"subcommunities": [{"uuid": INCO, "name": "InCo"}]}})
        return httpx.Response(200, json={"_embedded": {"collections": [{"uuid": ITEM, "name": "Tesis"}]}})
    install_transport(monkeypatch, handler)
    source = ColibriSource(db=db)
    source.pace = AsyncMock()
    result = asyncio.run(source.browse(FING))
    assert result == [{"uuid": INCO, "name": "InCo", "kind": "communities"},
                      {"uuid": ITEM, "name": "Tesis", "kind": "collections"}]
