import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from radar.app import create_app
from radar.catalog import CATEGORIES
from radar.config import daily_slot
from radar.engine import Engine
from radar.sources import ArxivSource


def feed(offset, count, total, *, updated=None, category="cs.AI", index=None):
    updated = updated or (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    entries = "".join(f"""<entry><id>http://arxiv.org/abs/2610.{i:05d}v1</id>
        <title>Algorithm design and machine learning {i}</title><summary>We investigate algorithms and machine learning.</summary>
        <published>{updated}</published><updated>{updated}</updated><category term="{escape(category)}"/></entry>"""
        for i in range(offset, offset + count))
    return f"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
        <o:totalResults>{total}</o:totalResults><o:startIndex>{offset if index is None else index}</o:startIndex>{entries}</feed>""".encode()


def source_for(db, monkeypatch, handler, *, budget=2, size=2):
    original = httpx.AsyncClient
    monkeypatch.setattr("radar.sources.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    source = ArxivSource(db=db)
    source.pace = AsyncMock()
    source.request_budget, source.page_size = budget, size
    return source


def interval():
    end = datetime.now(UTC) + timedelta(seconds=1)
    return end - timedelta(days=7), end


def test_budget_commits_pages_and_new_source_resumes_instead_of_starting_over(db, monkeypatch):
    calls = []

    def handler(request):
        offset = int(request.url.params["start"])
        calls.append(offset)
        return httpx.Response(200, content=feed(offset, min(2, 7 - offset), 7))

    start, end = interval()
    source = source_for(db, monkeypatch, handler)
    first = asyncio.run(source.discover(start, end, ["cs.AI"]))
    assert not first.complete and len(first) == 4
    assert len(db.rows("SELECT * FROM papers")) == 4
    assert db.get_meta(source.checkpoint_key)["units"][0]["offset"] == 4
    # Nueva instancia y fechas de llamada distintas: se retoma el intervalo fijado.
    second_source = ArxivSource(db=db)
    second_source.pace = AsyncMock()
    second_source.request_budget, second_source.page_size = 2, 2
    second = asyncio.run(second_source.discover(start + timedelta(days=1), end + timedelta(days=1), ["cs.AI"]))
    assert second.complete and second.start == start and second.end == end
    assert calls == [0, 2, 4, 6]
    assert len(db.rows("SELECT * FROM papers")) == 7
    assert second.progress["saved"] == 7


def test_more_than_5000_metadata_is_partial_success_then_continues(db, monkeypatch):
    calls = []

    def handler(request):
        offset = int(request.url.params["start"])
        calls.append(offset)
        return httpx.Response(200, content=feed(offset, min(100, 5100 - offset), 5100))

    source = source_for(db, monkeypatch, handler, budget=50, size=100)
    start, end = interval()
    first = asyncio.run(source.discover(start, end, ["cs.AI"]))
    assert not first.complete and len(first.inserted_ids) == 5000
    assert len(calls) == 50
    second = asyncio.run(source.discover(start, end, ["cs.AI"]))
    assert second.complete and calls[-1] == 5000
    assert len(db.rows("SELECT * FROM papers")) == 5100


def test_all_categories_are_grouped_and_round_robin_covers_breadth(db, monkeypatch):
    calls = []
    codes = sorted(list(CATEGORIES)[:19])

    def handler(request):
        calls.append((request.url.params["search_query"], int(request.url.params["start"])))
        return httpx.Response(200, content=feed(int(request.url.params["start"]), 2, 8))

    source = source_for(db, monkeypatch, handler, budget=4)
    result = asyncio.run(source.discover(*interval(), codes))
    assert not result.complete
    assert [offset for _, offset in calls] == [0, 0, 0, 2]
    checkpoint = db.get_meta(source.checkpoint_key)
    assert len(checkpoint["units"]) == 3
    assert all(any(f"cat:{code}" in unit["query"] for unit in checkpoint["units"]) for code in codes)
    assert all(unit["query"].count("cat:") <= 8 for unit in checkpoint["units"])
    assert len(db.rows("SELECT * FROM papers")) == 4  # cross-listings deduplicated


def test_http_failure_preserves_page_and_failed_offset_and_respects_cooldown(db, monkeypatch):
    calls = []

    def handler(request):
        offset = int(request.url.params["start"])
        calls.append(offset)
        return httpx.Response(200, content=feed(0, 2, 8)) if offset == 0 else httpx.Response(429, headers={"Retry-After": "7200"})

    source = source_for(db, monkeypatch, handler)
    first = asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert not first.complete and first.error
    assert len(db.rows("SELECT * FROM papers")) == 2
    assert db.get_meta(source.checkpoint_key)["units"][0]["offset"] == 2
    second = asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert not second.complete and second.error
    assert calls == [0, 2]  # no external request during the network cooldown


def test_cancellation_keeps_successful_page_and_resume_point(db, monkeypatch):
    source = source_for(db, monkeypatch, lambda request: httpx.Response(200, content=feed(0, 2, 8)))
    original_get = source.get

    async def get(client, url, **kwargs):
        if kwargs["params"]["start"]:
            raise asyncio.CancelledError()
        return await original_get(client, url, **kwargs)

    source.get = get
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert len(db.rows("SELECT * FROM papers")) == 2
    assert db.get_meta(source.checkpoint_key)["units"][0]["offset"] == 2


@pytest.mark.parametrize("bad_index", [True, False])
def test_wrong_index_or_repeated_page_does_not_advance_checkpoint(db, monkeypatch, bad_index):
    def handler(request):
        offset = int(request.url.params["start"])
        return httpx.Response(200, content=feed(0, 2, 8, index=0 if bad_index else offset))

    source = source_for(db, monkeypatch, handler)
    result = asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert result.error and not result.complete
    assert result.progress["pages"] == 1
    assert db.get_meta(source.checkpoint_key)["units"][0]["offset"] == 2


def test_papers_and_checkpoint_roll_back_together(db, monkeypatch):
    source = source_for(db, monkeypatch, lambda request: httpx.Response(200, content=feed(0, 2, 2)))
    add = db.add_papers

    def broken_add(papers, *, connection=None):
        add(papers, connection=connection)
        raise ValueError("simulated transaction failure")

    monkeypatch.setattr(db, "add_papers", broken_add)
    with pytest.raises(ValueError, match="transaction failure"):
        asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert db.rows("SELECT * FROM papers") == []
    assert db.get_meta(source.checkpoint_key) is None


def test_failed_second_transaction_reports_only_committed_progress(db, monkeypatch):
    source = source_for(db, monkeypatch, lambda request: httpx.Response(200, content=feed(int(request.url.params["start"]), 2, 4)))
    add = db.add_papers

    def broken_add(papers, *, connection=None):
        ids = add(papers, connection=connection)
        if papers[0].external_id.endswith("00002"):
            raise ValueError("simulated second-page failure")
        return ids

    monkeypatch.setattr(db, "add_papers", broken_add)
    result = asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert result.error and not result.complete
    assert result.progress["pages"] == 1 and result.progress["saved"] == 2
    assert db.get_meta(source.checkpoint_key)["units"][0]["offset"] == 2
    assert len(db.rows("SELECT * FROM papers")) == 2


def test_recent_revisions_of_old_submissions_are_not_lost_to_a_submission_date_filter(db, monkeypatch):
    body = feed(0, 1, 1)
    # Un envío original antiguo con una actualización dentro de la ventana.
    before = body.split(b"<published>")[1].split(b"</published>")[0]
    body = body.replace(b"<published>" + before + b"</published>", b"<published>2021-01-01T00:00:00Z</published>")
    source = source_for(db, monkeypatch, lambda request: httpx.Response(200, content=body))
    result = asyncio.run(source.discover(*interval(), ["cs.AI"]))
    assert result.complete and len(result) == 1
    assert db.rows("SELECT published FROM papers")[0]["published"] == "2021-01-01T00:00:00Z"


def test_changed_categories_invalidate_checkpoint_but_do_not_delete_papers(db, monkeypatch):
    calls = []

    def handler(request):
        calls.append((request.url.params["search_query"], request.url.params["start"]))
        return httpx.Response(200, content=feed(int(request.url.params["start"]), 2, 8))

    source = source_for(db, monkeypatch, handler, budget=1)
    asyncio.run(source.discover(*interval(), ["cs.AI"]))
    asyncio.run(source.discover(*interval(), ["cs.LG"]))
    assert [offset for _, offset in calls] == ["0", "0"]
    assert "cat:cs.LG" in calls[-1][0]
    assert len(db.rows("SELECT * FROM papers")) == 2


def test_partial_scan_selects_bulletin_preserves_quota_and_advances_cursor_only_at_end(db, monkeypatch, tmp_path):
    def handler(request):
        offset = int(request.url.params["start"])
        return httpx.Response(200, content=feed(offset, min(2, 5 - offset), 5))

    source = source_for(db, monkeypatch, handler, budget=1)
    engine = Engine(db, tmp_path)
    engine.sources["arxiv"] = source

    async def run():
        await engine.scan("manual")
        assert engine.source_state("arxiv").get("last_scan") is None
        assert engine.source_state("arxiv").get("last_slot") is None
        assert db.rows("SELECT found,selected,status FROM runs")[0] == {"found": 2, "selected": 2, "status": "partial"}
        end = db.get_meta(source.checkpoint_key)["end"]
        db.execute("UPDATE jobs SET status='cancelled'")
        for _ in range(2):
            state = engine.source_state("arxiv")
            db.set_meta("source:arxiv", {**state, "retry_after": None})
            await engine.scan("manual")
        assert engine.source_state("arxiv")["last_scan"] == end
        assert engine.source_state("arxiv")["last_slot"] == daily_slot(datetime.fromisoformat(end), db.settings()).isoformat()
        assert len(db.rows("SELECT * FROM papers")) == 5
        assert len(db.rows("SELECT * FROM bulletin")) == 5
        assert len(db.rows("SELECT * FROM jobs WHERE status='cancelled'")) == 2
        assert engine.status()["sources"]["arxiv"]["discovery"]["complete"]

    asyncio.run(run())


def test_partial_scans_do_not_multiply_daily_quota_or_restore_deleted_day(db, monkeypatch, tmp_path):
    source = source_for(db, monkeypatch, lambda request: httpx.Response(200, content=feed(int(request.url.params["start"]), 2, 6)), budget=1)
    settings = db.settings().model_dump()
    settings["bulletin_limit"] = 2
    db.set_meta("settings", settings)
    engine = Engine(db, tmp_path)
    engine.sources["arxiv"] = source

    async def run():
        await engine.scan("manual")
        day = datetime.now(UTC).astimezone(ZoneInfo(db.settings().timezone)).date().isoformat()
        engine.remove_bulletin(day)
        state = engine.source_state("arxiv")
        db.set_meta("source:arxiv", {**state, "retry_after": None})
        await engine.scan("manual")
        assert db.rows("SELECT * FROM bulletin") == []
        assert len(db.rows("SELECT * FROM jobs")) == 2
        assert len(db.rows("SELECT * FROM papers")) == 4

    asyncio.run(run())


def test_saving_new_arxiv_filters_clears_only_discovery_checkpoint(tmp_path):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    db.set_meta("discovery:arxiv", {"complete": False, "start": "2026-10-01", "end": "2026-10-07",
                                  "pages": 1, "saved": 2, "next": 0, "units": [{"done": False, "offset": 2}]})
    db.set_meta("unrelated", {"keep": True})
    with TestClient(app, base_url="http://localhost") as client:
        settings = client.get("/api/settings").json()
        settings["categories"] = ["cs.DS"]
        assert client.put("/api/settings", json=settings, headers={"X-Radar-Request": "1"}).status_code == 200
    assert db.get_meta("discovery:arxiv") is None
    assert db.get_meta("unrelated") == {"keep": True}
