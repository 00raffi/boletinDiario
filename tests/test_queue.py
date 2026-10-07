import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from radar.app import create_app
from radar.db import utcnow
from radar.engine import Engine


def test_activity_shows_ten_and_prioritizes_pending_without_deleting_history(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    for number in range(15):
        paper_id = db.add_papers([replace(sample, external_id=f"test-{number}")])[0]
        db.queue(paper_id, "summary")
    db.execute("UPDATE jobs SET status='done',updated_at='2099-01-01T00:00:00+00:00'")
    db.execute("UPDATE jobs SET status='running' WHERE id=1")
    db.execute("UPDATE jobs SET status='queued' WHERE id IN (2,3)")
    with TestClient(app, base_url="http://localhost") as client:
        data = client.get("/api/activity").json()
        assert data["job_limit"] == 10 and data["jobs_total"] == 15
        assert len(data["jobs"]) == 10
        assert data["jobs"][0]["id"] == 1
        assert [j["id"] for j in data["jobs"][1:3]] == [2, 3]
        assert len(db.rows("SELECT * FROM jobs")) == 15


def test_queue_cancel_endpoint_is_local_and_preserves_result_and_other_jobs(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    paper_id = db.add_papers([sample])[0]
    db.execute("UPDATE papers SET brief=? WHERE id=?", (json.dumps({"summary": "Anterior"}), paper_id))
    db.queue(paper_id, "brief")
    db.queue(paper_id, "analysis")
    job = db.rows("SELECT * FROM jobs WHERE kind='brief'")[0]
    with TestClient(app, base_url="http://localhost") as client:
        path = f"/api/jobs/{job['id']}/cancel"
        assert client.post(path).status_code == 403
        response = client.post(path, headers={"X-Radar-Request": "1"})
        assert response.status_code == 200 and response.json()["cancelled"]
        assert db.rows("SELECT status FROM jobs WHERE kind='brief'")[0]["status"] == "cancelled"
        assert db.rows("SELECT status FROM jobs WHERE kind='analysis'")[0]["status"] == "queued"
        assert db.paper(paper_id)["brief"]["summary"] == "Anterior"
        assert client.post(path, headers={"X-Radar-Request": "1"}).status_code == 409
        assert client.post("/api/jobs/999/cancel", headers={"X-Radar-Request": "1"}).status_code == 404
    db.recover()
    assert db.rows("SELECT status FROM jobs WHERE kind='brief'")[0]["status"] == "cancelled"


@pytest.mark.parametrize("status", ["done", "error", "cancelled"])
def test_cancellation_does_not_touch_finished_tasks(db, sample, tmp_path, status):
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "brief")
    db.execute("UPDATE jobs SET status=?", (status,))
    engine = Engine(db, tmp_path)
    assert not asyncio.run(engine.cancel_job(db.rows("SELECT id FROM jobs")[0]["id"]))
    assert db.rows("SELECT status FROM jobs")[0]["status"] == status


def test_cancel_selected_running_job_cleans_memory_without_cancelling_other_jobs(db, sample, tmp_path):
    async def run():
        db.set_meta("settings", {**db.settings().model_dump(), "unload_after_paper": True})
        first = db.add_papers([sample])[0]
        second = db.add_papers([replace(sample, external_id="2610.00002")])[0]
        db.queue(first, "brief")
        db.queue(second, "brief")
        db.set_meta("confirmed-notes", [{"facts": []}])
        engine = Engine(db, tmp_path)
        started = asyncio.Event()
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        engine.llm.unload = AsyncMock()

        async def brief(*args):
            started.set()
            await asyncio.Event().wait()

        engine.llm.brief = brief
        job = db.rows("SELECT * FROM jobs WHERE paper_id=?", (first,))[0]
        engine.job_task = asyncio.create_task(engine.process_job(job))
        await asyncio.wait_for(started.wait(), 1)
        assert await engine.cancel_job(job["id"])
        assert db.rows("SELECT status FROM jobs WHERE paper_id=?", (first,))[0]["status"] == "cancelled"
        assert db.rows("SELECT status FROM jobs WHERE paper_id=?", (second,))[0]["status"] == "queued"
        assert db.get_meta("confirmed-notes") == [{"facts": []}]
        assert engine.current_job is None
        engine.llm.unload.assert_awaited_once()
    asyncio.run(run())


def test_selected_queue_job_cancelled_before_claim_never_starts_inference(db, sample, tmp_path):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "brief")
        job = db.rows("SELECT * FROM jobs")[0]
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock()
        assert await engine.cancel_job(job["id"])
        await engine.process_job(job)
        engine.llm.models.assert_not_awaited()
        assert engine.current_job is None
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "cancelled"
    asyncio.run(run())


def test_fragment_progress_counts_only_confirmed_work(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "overview")
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])

        async def analyze(paper, settings, source, llm, database, data_dir, progress):
            progress("Secciones confirmadas 7/24")
            assert engine.current_job["progress_completed"] == 7
            progress("Resumiendo sección 8/24 · capítulo 6")
            assert engine.current_job["progress_completed"] == 7
            assert engine.current_job["progress_total"] == 24
            progress("Secciones confirmadas 8/24")
            progress("Liberando memoria de Ollama entre fragmentos")
            assert engine.current_job["progress_completed"] == 8
            return {"created_at": utcnow()}

        monkeypatch.setattr("radar.engine.article_overview", analyze)
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        assert db.rows("SELECT status FROM jobs")[0]["status"] == "done"
    asyncio.run(run())


def test_repeated_cancel_does_not_interrupt_cleanup_and_shutdown_keeps_explicit_cancel(db, sample, tmp_path):
    async def run():
        db.set_meta("settings", {**db.settings().model_dump(), "unload_after_paper": True})
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "brief")
        engine = Engine(db, tmp_path)
        started = asyncio.Event()
        cleaned = asyncio.Event()
        engine.llm.models = AsyncMock(return_value=[db.settings().model])

        async def brief(*args):
            started.set()
            await asyncio.Event().wait()

        async def unload(*args):
            await asyncio.sleep(0)
            cleaned.set()

        engine.llm.brief = brief
        engine.llm.unload = unload
        job = db.rows("SELECT * FROM jobs")[0]
        engine.job_task = asyncio.create_task(engine.process_job(job))
        await started.wait()
        assert engine.cancel(job["id"])
        assert not engine.cancel(job["id"])
        engine.stopping = True
        with pytest.raises(asyncio.CancelledError):
            await engine.job_task
        assert cleaned.is_set()
        db.recover()
        assert db.rows("SELECT status,progress FROM jobs")[0] == {
            "status": "cancelled", "progress": "Cancelado por el usuario"}
    asyncio.run(run())
