import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from radar.app import create_app
from radar.engine import Engine

HEADERS = {"X-Radar-Request": "1"}


def add_bulletin(db, stamp, day, papers):
    run_id = db.execute("""INSERT INTO runs(started_at,status,reason,selected,bulletin_day)
        VALUES(?,'completed','manual',?,?)""", (stamp, len(papers), day))
    for paper_id in papers:
        db.execute("INSERT INTO bulletin VALUES(?,?)", (run_id, paper_id))
    return run_id


def test_remove_article_from_local_day_removes_all_repeated_memberships_only(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    first, second = db.add_papers([sample, replace(sample, external_id="other")])
    add_bulletin(db, "2026-10-06T01:00:00Z", "", [first])  # 5 October locally
    add_bulletin(db, "2026-10-06T12:00:00Z", "2026-10-06", [first, second])
    add_bulletin(db, "2026-10-06T14:00:00Z", "2026-10-06", [first])
    db.execute("UPDATE papers SET brief=?,overview=?,analysis=?,interest=1,favorite=1,is_read=1 WHERE id=?",
               ('{"summary":"Saved"}', '{"sections":[]}', '{"method":"Saved"}', first))
    db.queue(first, "summary")
    before_paper = db.paper(first)
    before_jobs = db.rows("SELECT * FROM jobs")
    before_runs = db.rows("SELECT * FROM runs")
    with TestClient(app, base_url="http://localhost") as client:
        path = f"/api/bulletins/2026-10-06/papers/{first}"
        assert client.delete(path).status_code == 403
        assert client.delete(path, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
        assert client.get(f"/api/papers/{first}").json()["bulletin_days"] == ["2026-10-06", "2026-10-05"]
        response = client.delete(path, headers=HEADERS)
        assert response.json()["removed_articles"] == 1
        assert [p["id"] for p in client.get("/api/papers?bulletin_day=2026-10-06").json()["papers"]] == [second]
        assert client.get(f"/api/papers/{first}").json()["bulletin_days"] == ["2026-10-05"]
        assert client.delete(path, headers=HEADERS).status_code == 404
        assert client.delete("/api/bulletins/invalid/papers/1", headers=HEADERS).status_code == 422
    assert db.paper(first) == before_paper
    assert db.rows("SELECT * FROM jobs") == before_jobs
    assert db.rows("SELECT * FROM runs") == before_runs
    assert app.state.engine.used_slots("2026-10-06", "arxiv", db.settings()) == 2


def test_delete_bulletin_is_day_wide_keeps_documents_jobs_cursors_and_latest_falls_back(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    first, second = db.add_papers([sample, replace(sample, source="colibri", external_id="other")])
    add_bulletin(db, "2026-10-05T12:00:00Z", "2026-10-05", [first])
    add_bulletin(db, "2026-10-06T12:00:00Z", "2026-10-06", [first])
    add_bulletin(db, "2026-10-06T14:00:00Z", "2026-10-06", [second])
    db.set_meta("source:arxiv", {"last_scan": "saved", "retry_after": "saved"})
    db.queue(second, "summary")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.delete("/api/bulletins/2026-10-06").status_code == 403
        response = client.delete("/api/bulletins/2026-10-06", headers=HEADERS)
        assert response.json()["removed_articles"] == 2
        assert [d["day"] for d in client.get("/api/bulletins").json()["days"]] == ["2026-10-05"]
        assert client.get("/api/bulletin").json()["day"] == "2026-10-05"
        assert client.get("/api/papers").json()["total"] == 2
        assert client.get("/api/papers?bulletin_day=2026-10-06").json()["total"] == 0
        assert client.delete("/api/bulletins/2026-10-06", headers=HEADERS).status_code == 404
        assert client.delete("/api/bulletins/not-a-date", headers=HEADERS).status_code == 422
        assert client.delete("/api/bulletins/2026-10-05", headers=HEADERS).status_code == 200
        assert client.get("/api/bulletin").json()["run"] is None
    assert db.get_meta("source:arxiv") == {"last_scan": "saved", "retry_after": "saved"}
    assert db.rows("SELECT paper_id,status FROM jobs") == [{"paper_id": second, "status": "queued"}]
    app.state.engine.plan_summaries()
    assert len(db.rows("SELECT * FROM jobs")) == 1


def test_removed_article_consumes_its_slot_and_is_not_selected_again(db, sample, tmp_path):
    engine = Engine(db, tmp_path)
    settings = db.settings().model_dump()
    settings.update(bulletin_limit=2)
    db.set_meta("settings", settings)
    today = datetime.now(UTC).astimezone(ZoneInfo(settings["timezone"])).date().isoformat()
    first = db.add_papers([sample])[0]
    add_bulletin(db, datetime.now(UTC).isoformat(), today, [first])
    engine.remove_bulletin(today, first)
    engine.sources["arxiv"].discover = AsyncMock(return_value=[sample, replace(sample, external_id="new")])
    asyncio.run(engine.scan("manual", ["arxiv"]))
    assert db.rows("SELECT paper_id FROM bulletin") == [{"paper_id": first + 1}]
    assert engine.used_slots(today, "arxiv", db.settings()) == 2
    engine.sources["arxiv"].discover = AsyncMock(return_value=[replace(sample, external_id="third")])
    asyncio.run(engine.scan("manual", ["arxiv"]))
    assert len(db.rows("SELECT * FROM bulletin")) == 1


def test_delete_day_during_discovery_cannot_recreate_it(db, sample, tmp_path):
    engine = Engine(db, tmp_path)
    today = datetime.now(UTC).astimezone(ZoneInfo(db.settings().timezone)).date().isoformat()
    first = db.add_papers([sample])[0]
    add_bulletin(db, datetime.now(UTC).isoformat(), today, [first])

    async def discover(*args, **kwargs):
        engine.remove_bulletin(today)
        return [sample, replace(sample, external_id="new")]

    engine.sources["arxiv"].discover = discover
    asyncio.run(engine.scan("manual", ["arxiv"]))
    engine.plan_summaries()
    assert db.rows("SELECT * FROM bulletin") == []
    assert db.rows("SELECT * FROM jobs") == []
    assert db.rows("SELECT count(*) AS n FROM papers")[0]["n"] == 2


def test_clear_archive_and_regenerate_today_is_local_atomic_preserves_results_and_cancellations(db, sample, tmp_path):
    engine = Engine(db, tmp_path)
    settings = db.settings().model_dump()
    settings.update(colibri_enabled=True, bulletin_limit=3, colibri_bulletin_limit=1)
    db.set_meta("settings", settings)
    recent = replace(sample, updated="2026-10-06T10:00:00Z")
    papers = [recent, replace(recent, external_id="second"), replace(recent, external_id="cancelled"),
              replace(recent, external_id="filtered", categories=["math.AG"]),
              replace(recent, external_id="colibri", source="colibri", categories=[settings["colibri_scopes"][0]]),
              replace(recent, external_id="old", updated="2026-08-01T10:00:00Z")]
    ids = db.add_papers(papers)
    add_bulletin(db, "2026-10-05T12:00:00Z", "2026-10-05", ids)
    add_bulletin(db, "2026-10-06T12:00:00Z", "2026-10-06", ids)
    db.execute("UPDATE papers SET brief=?,overview=?,analysis=?,interest=-1 WHERE id=?",
               ('{"relevance":4}', '{"sections":[]}', '{"method":"Saved"}', ids[0]))
    db.queue(ids[2], "summary")
    db.execute("UPDATE jobs SET status='cancelled'")
    db.set_meta("source:arxiv", {"last_scan": "saved", "retry_after": "saved"})
    db.set_meta("network:arxiv", {"until": "saved"})
    before_papers = db.rows("SELECT * FROM papers")
    before_meta = db.rows("SELECT * FROM meta")
    result = engine.regenerate_today(clear_archive=True, now=datetime(2026, 10, 6, 15, tzinfo=UTC))
    assert set(result["paper_ids"]) == {ids[0], ids[1], ids[4]}
    assert result["sources"]["arxiv"]["selected"] == 2
    assert result["sources"]["colibri"]["selected"] == 1
    assert db.rows("SELECT * FROM papers") == before_papers
    assert db.rows("SELECT * FROM meta") == before_meta
    assert db.rows("SELECT * FROM source_requests") == []
    assert db.rows("SELECT count(DISTINCT run_id) AS n FROM bulletin")[0]["n"] == 1
    assert engine.used_slots("2026-10-06", "arxiv", db.settings()) == 2
    assert db.rows("SELECT day FROM deleted_bulletins") == [{"day": "2026-10-05"}]
    assert db.rows("SELECT status FROM jobs WHERE paper_id=?", (ids[2],))[0]["status"] == "cancelled"
    assert db.rows("SELECT * FROM jobs WHERE paper_id=?", (ids[0],)) == []


def test_regeneration_replaces_memberships_not_stored_summary(db, sample, tmp_path):
    first = db.add_papers([sample])[0]
    db.execute("UPDATE papers SET brief=?,overview=? WHERE id=?",
               (json.dumps({"summary": "Saved"}), json.dumps({"sections": []}), first))
    add_bulletin(db, "2026-10-05T12:00:00Z", "2026-10-05", [first])
    engine = Engine(db, tmp_path)
    engine.regenerate_today(clear_archive=True, now=datetime(2026, 10, 6, 15, tzinfo=UTC))
    assert db.paper(first)["brief"]["summary"] == "Saved"
    assert db.rows("SELECT * FROM jobs") == []
