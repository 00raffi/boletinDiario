import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from radar.analysis import make_chunks, verify_evidence
from radar.app import create_app
from radar.config import Settings, daily_slot, next_slot
from radar.db import utcnow
from radar.engine import Engine, select_candidates
from radar.sources import bounded_get, parse_feed, validate_public_url


def test_daily_slot_has_calendar_anchor():
    settings = Settings()
    now = datetime(2026, 10, 5, 12, 30, tzinfo=UTC)
    assert daily_slot(now, settings).isoformat() == "2026-10-05T07:00:00-03:00"
    assert next_slot(now, settings).isoformat() == "2026-10-06T07:00:00-03:00"


def test_before_seven_recovers_previous_day():
    now = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    assert daily_slot(now, Settings()).isoformat() == "2026-10-04T07:00:00-03:00"


@pytest.mark.parametrize("changes", [{"daily_time":"25:00"},{"daily_time":"7:00"},
    {"timezone":"Not/AZone"},{"model":"gemma-cloud"},{"categories":["cat:bad OR all:*"]},
    {"bulletin_limit":0},{"max_chunks":41}])
def test_invalid_settings(changes):
    with pytest.raises(ValidationError):
        Settings(**changes)


def test_deduplication_and_versions(db, sample):
    ids = db.add_papers([sample])
    assert len(ids) == 1
    assert db.add_papers([sample]) == []
    new = db.add_papers([replace(sample, version="2", updated="2026-10-04T12:00:00Z")])
    assert db.paper(new[0])["is_revision"] == 1
    assert db.paper(ids[0])["is_revision"] == 0


def test_jobs_recover_and_manual_retry(db, sample):
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "analysis")
    db.execute("UPDATE jobs SET status='running'")
    db.recover()
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "queued"
    db.execute("UPDATE jobs SET status='error'")
    db.queue(paper_id, "analysis", retry=True)
    db.queue(paper_id, "analysis", retry=True)
    assert len(db.rows("SELECT * FROM jobs")) == 1
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "queued"


def test_candidate_selection_preferences_and_exclusions():
    settings=Settings(bulletin_limit=2,keywords=["planning"],excluded_keywords=["exclude"])
    papers=[{"title":"Recent", "abstract":"", "updated":"2026-10-04"},
            {"title":"Planning", "abstract":"", "updated":"2026-10-02"},
            {"title":"Exclude planning", "abstract":"", "updated":"2026-10-05"}]
    assert [p["title"] for p in select_candidates(papers,settings)] == ["Planning","Recent"]


@pytest.mark.parametrize("url", ["http://arxiv.org/pdf/a", "https://127.0.0.1/a", "https://arxiv.org.evil.test/",
    "https://arxiv.org:444/a", "https://user@arxiv.org/a", "file:///etc/passwd"])
def test_url_allowlist(url):
    with pytest.raises(ValueError): validate_public_url(url)


def test_feed_parsing_reconstructs_urls():
    feed=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
    <o:totalResults>1</o:totalResults><entry><id>http://arxiv.org/abs/2610.00001v2</id><title>A\n paper</title>
    <summary>Test abstract</summary><published>2026-10-01T00:00:00Z</published><updated>2026-10-02T00:00:00Z</updated>
    <author><name>A</name></author><category term="cs.AI"/><link href="http://localhost/secret"/></entry></feed>'''
    papers,total=parse_feed(feed)
    assert total==1
    assert papers[0].version=="2"
    assert papers[0].pdf_url=="https://arxiv.org/pdf/2610.00001v2"
    assert papers[0].title=="A paper"


def test_unsafe_xml_is_rejected():
    from defusedxml.common import DefusedXmlException
    with pytest.raises(DefusedXmlException):
        parse_feed(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><feed>&x;</feed>')


def test_redirect_to_private_host_is_blocked():
    async def check():
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(302,headers={"location":"http://127.0.0.1/private"})))
        async with client:
            with pytest.raises(ValueError): await bounded_get(client,"https://arxiv.org/pdf/test")
    asyncio.run(check())


def test_download_limit():
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b"123456"))) as client:
            with pytest.raises(ValueError): await bounded_get(client,"https://arxiv.org/test",limit=4)
    asyncio.run(check())


def test_chunking_does_not_drop_tails():
    pages=[{"page":1,"text":"x"*4010},{"page":2,"text":"short"}]
    chunks=make_chunks(pages)
    assert [len(c["text"]) for c in chunks]==[4000,10,5]
    assert chunks[-1]["page"]==2


def test_only_literal_evidence_survives():
    chunk={"page":3,"text":"We report an accuracy of 80 percent."}
    evidence=[{"page":3,"quote":"accuracy of 80 percent", "claim":"A"},
              {"page":3,"quote":"accuracy of 99 percent", "claim":"B"},
              {"page":4,"quote":"accuracy of 80 percent", "claim":"C"}]
    assert verify_evidence(evidence,chunk)==[evidence[0]]


def test_scan_persists_queue_and_cursor(db,sample,tmp_path):
    class FakeSource:
        async def discover(self,*args):return [sample]
    engine=Engine(db,tmp_path)
    engine.sources["arxiv"]=FakeSource()
    asyncio.run(engine.scan("manual"))
    assert db.get_meta("last_scan")
    assert db.get_meta("last_slot")
    assert db.rows("SELECT * FROM runs")[0]["status"]=="completed"
    assert db.rows("SELECT * FROM jobs")[0]["status"]=="queued"
    asyncio.run(engine.scan("manual"))
    assert len(db.rows("SELECT * FROM papers"))==1
    assert len(db.rows("SELECT * FROM jobs"))==1


def test_failed_scan_never_advances_cursor(db,tmp_path):
    class BrokenSource:
        async def discover(self,*args):raise ValueError("network unavailable")
    engine=Engine(db,tmp_path)
    engine.sources["arxiv"]=BrokenSource()
    asyncio.run(engine.scan("manual"))
    assert db.get_meta("last_scan") is None
    assert db.get_meta("last_slot") is None
    assert db.rows("SELECT * FROM runs")[0]["status"]=="error"


def test_brief_job_calls_local_model_and_records_result(db,sample,tmp_path):
    class FakeOllama:
        async def models(self):return ["gemma3:4b"]
        async def brief(self,paper,settings):return {"summary":"Resumen", "relevance":4,"stats":{"model":settings.model}}
    engine=Engine(db,tmp_path)
    engine.llm=FakeOllama()
    paper_id=db.add_papers([sample])[0]
    db.queue(paper_id,"brief")
    asyncio.run(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
    assert db.paper(paper_id)["brief"]["summary"]=="Resumen"
    assert db.rows("SELECT * FROM jobs")[0]["status"]=="done"


def test_automatic_summary_is_single_and_does_not_requeue_cancelled_jobs(db,sample,tmp_path):
    engine=Engine(db,tmp_path)
    run_id=db.execute("INSERT INTO runs(started_at,status,reason,selected) VALUES(?,'completed','manual',1)",(utcnow(),))
    paper_id=db.add_papers([sample])[0]
    db.execute("INSERT INTO bulletin VALUES(?,?)",(run_id,paper_id))
    engine.plan_summaries()
    assert len(db.rows("SELECT * FROM jobs"))==1
    db.execute("UPDATE papers SET brief=? WHERE id=?",(json.dumps({"relevance":4}),paper_id))
    db.execute("UPDATE jobs SET status='done'")
    engine.plan_summaries()
    assert len(db.rows("SELECT * FROM jobs WHERE kind='summary'"))==1
    db.execute("UPDATE jobs SET status='cancelled'")
    engine.plan_summaries()
    assert db.rows("SELECT status FROM jobs")[0]["status"]=="cancelled"
    assert db.rows("SELECT * FROM jobs WHERE kind='analysis'")==[]


def test_local_http_security_and_api(tmp_path,sample):
    app=create_app(tmp_path,start_engine=False)
    paper_id=app.state.db.add_papers([sample])[0]
    with TestClient(app,base_url="http://localhost") as client:
        response=client.get("/")
        assert response.status_code==200
        assert "Content-Security-Policy" in response.headers
        assert client.get("/api/papers").json()["total"]==1
        assert client.get(f"/api/papers/{paper_id}").json()["title"]==sample.title
        assert client.patch(f"/api/papers/{paper_id}",json={"favorite":True}).status_code==403
        assert client.patch(f"/api/papers/{paper_id}",json={"favorite":True},headers={"X-Radar-Request":"1","Origin":"https://evil.test"}).status_code==403
        assert client.patch(f"/api/papers/{paper_id}",json={"favorite":True},headers={"X-Radar-Request":"1","Origin":"http://localhost"}).status_code==200
        assert client.get("/api/papers?state=favorites").json()["total"]==1
        assert client.get("/api/status",headers={"Host":"evil.test"}).status_code==400
        assert client.post(f"/api/papers/{paper_id}/jobs/analysis",headers={"X-Radar-Request":"1"}).status_code==410
        assert client.post(f"/api/papers/{paper_id}/jobs/summary",headers={"X-Radar-Request":"1"}).status_code==200
        assert client.get(f"/api/papers/{paper_id}/export").status_code==200
