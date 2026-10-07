import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient

from radar.app import create_app
from radar.colibri import ColibriSource
from radar.engine import Engine

ITEM = "101566c7-df87-448d-b63f-4f7e17371815"
BUNDLE = "cddb47ae-d041-48e4-9f7b-3b3bda361ec0"
FILE = "c9d00707-b629-47a4-9893-20bbf246110f"
URL = f"https://www.colibri.udelar.edu.uy/server/api/core/bitstreams/{FILE}/content"


def test_colibri_pdf_link_resolves_caches_and_does_not_download_large_content(db, sample, monkeypatch):
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/bundles"):
            return httpx.Response(200, json={"_embedded": {"bundles": [{"uuid": BUNDLE, "name": "ORIGINAL"}]}})
        if request.url.path.endswith("/bitstreams"):
            return httpx.Response(200, json={"_embedded": {"bitstreams": [{"uuid": FILE, "name": "tesis.pdf",
                "bundleName": "ORIGINAL", "sizeBytes": 30_000_000}]}})
        raise AssertionError("Abrir enlace no debe descargar contenido.")

    monkeypatch.setattr("radar.colibri.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    paper_id = db.add_papers([replace(sample, source="colibri", external_id=ITEM, pdf_url="", has_pdf=False)])[0]
    source = ColibriSource(db=db)
    source.pace = AsyncMock()
    assert asyncio.run(source.resolve_pdf(db.paper(paper_id))) == (URL, 30_000_000)
    assert db.paper(paper_id)["pdf_url"] == URL and db.paper(paper_id)["has_pdf"]
    assert asyncio.run(source.resolve_pdf(db.paper(paper_id))) == (URL, None)
    assert len(calls) == 2


def test_pdf_endpoint_is_explicit_local_request_without_inference(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    paper_id = app.state.db.add_papers([replace(sample, source="colibri", external_id=ITEM, pdf_url="")])[0]
    app.state.engine.sources["colibri"].resolve_pdf = AsyncMock(return_value=(URL, 1000))
    app.state.engine.llm.models = AsyncMock()
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post(f"/api/papers/{paper_id}/pdf").status_code == 403
        response = client.post(f"/api/papers/{paper_id}/pdf", headers={"X-Radar-Request": "1"})
        assert response.json()["url"] == URL
        app.state.engine.llm.models.assert_not_awaited()
        assert client.post("/api/papers/999/pdf", headers={"X-Radar-Request": "1"}).status_code == 404


def test_summary_pipeline_generates_all_components_once_and_preserves_technical_archive(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.execute("UPDATE papers SET analysis=? WHERE id=?", ('{"method":"Archived"}', paper_id))
        db.queue(paper_id, "summary")
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        engine.llm.brief = AsyncMock(return_value={"summary": "Brief", "relevance": 4, "relevance_reason": "Interest"})
        overview = AsyncMock(return_value={"sections": [{"title": "Conclusion", "summary": "Result"}], "support": []})
        monkeypatch.setattr("radar.engine.article_overview", overview)
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        paper = db.paper(paper_id)
        assert paper["brief"]["summary"] == "Brief"
        assert paper["overview"]["sections"][0]["title"] == "Conclusion"
        assert paper["analysis"] == {"method": "Archived"}
        assert db.rows("SELECT kind,status FROM jobs") == [{"kind": "summary", "status": "done"}]
        engine.llm.brief.assert_awaited_once()
        overview.assert_awaited_once()
    asyncio.run(run())


def test_pdf_failure_keeps_brief_for_display_and_reuses_it_on_retry(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "summary")
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        engine.llm.brief = AsyncMock(return_value={"summary": "Brief", "relevance": 4})
        overview = AsyncMock(side_effect=ValueError("PDF restringido"))
        monkeypatch.setattr("radar.engine.article_overview", overview)
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        assert db.paper(paper_id)["brief"]["summary"] == "Brief"
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "error"
        db.queue(paper_id, "summary", retry=True)
        overview.side_effect = None
        overview.return_value = {"sections": [], "support": []}
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        engine.llm.brief.assert_awaited_once()
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "done"
    asyncio.run(run())


def test_legacy_job_migration_preserves_cancelled_and_results(db, sample, tmp_path):
    first = db.add_papers([sample])[0]
    second = db.add_papers([replace(sample, external_id="cancelled")])[0]
    db.execute("UPDATE papers SET analysis=?", ('{"method":"Archived"}',))
    db.queue(first, "brief")
    db.queue(first, "analysis")
    db.queue(second, "overview")
    db.execute("UPDATE jobs SET status='cancelled' WHERE paper_id=?", (second,))
    engine = Engine(db, tmp_path)
    engine.retire_legacy_jobs()
    engine.retire_legacy_jobs()
    assert db.rows("SELECT paper_id,status FROM jobs WHERE kind='summary'") == [{"paper_id": first, "status": "queued"}]
    assert db.rows("SELECT * FROM jobs WHERE kind='analysis' AND status='queued'") == []
    assert db.paper(first)["analysis"] == {"method": "Archived"}
    assert db.rows("SELECT status FROM jobs WHERE paper_id=?", (second,))[0]["status"] == "cancelled"


def test_summary_with_no_pdf_is_explicit_and_does_not_invent_sections(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([replace(sample, has_pdf=False)])[0]
        db.queue(paper_id, "summary")
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        engine.llm.brief = AsyncMock(return_value={"summary": "Brief", "relevance": 4})
        overview = AsyncMock()
        monkeypatch.setattr("radar.engine.article_overview", overview)
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        assert db.paper(paper_id)["overview"]["scope"] == "pdf_unavailable"
        assert db.paper(paper_id)["overview"]["sections"] == []
        overview.assert_not_awaited()
    asyncio.run(run())


def test_analysis_jobs_cannot_run_even_if_left_in_queue(db, sample, tmp_path):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "analysis")
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock()
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        engine.llm.models.assert_not_awaited()
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "cancelled"
    asyncio.run(run())


def test_pause_summaries_keeps_queued_work_without_starting_inference(db, sample, tmp_path, monkeypatch):
    async def run():
        settings = db.settings().model_dump()
        settings.update(pause_summaries=True, schedule_enabled=False)
        db.set_meta("settings", settings)
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "summary")
        engine = Engine(db, tmp_path)

        async def end_iteration(_):
            engine.stopping = True

        monkeypatch.setattr("radar.engine.asyncio.sleep", end_iteration)
        await engine.loop()
        assert engine.job_task is None
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "queued"
    asyncio.run(run())


def test_summary_cancellation_preserves_saved_brief_and_stays_cancelled_after_recovery(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "summary")
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        engine.llm.brief = AsyncMock(return_value={"summary": "Confirmed brief", "relevance": 4})
        started = asyncio.Event()

        async def wait_for_cancellation(*args):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("radar.engine.article_overview", wait_for_cancellation)
        job = db.rows("SELECT * FROM jobs")[0]
        engine.job_task = asyncio.create_task(engine.process_job(job))
        await started.wait()
        assert await engine.cancel_job(job["id"])
        assert db.paper(paper_id)["brief"]["summary"] == "Confirmed brief"
        assert db.paper(paper_id)["overview"] is None
        db.recover()
        engine.retire_legacy_jobs()
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "cancelled"
    asyncio.run(run())
