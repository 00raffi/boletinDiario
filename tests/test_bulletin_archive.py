from dataclasses import replace

from fastapi.testclient import TestClient

from radar.app import create_app


def test_bulletin_days_group_runs_deduplicate_papers_and_preserve_legacy_local_dates(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    first = db.add_papers([sample])[0]
    second = db.add_papers([replace(sample, external_id="another", source="colibri")])[0]
    for stamp, day, paper_ids in [
        ("2026-10-06T01:00:00+00:00", "", [first]),
        ("2026-10-05T22:00:00+00:00", "2026-10-05", [first, second]),
        ("2026-10-06T10:00:00+00:00", "2026-10-06", [second]),
        ("2026-10-07T10:00:00+00:00", "2026-10-07", []),
    ]:
        run_id = db.execute("INSERT INTO runs(started_at,status,reason,bulletin_day,selected) VALUES(?,'completed','manual',?,?)", (stamp, day, len(paper_ids)))
        for paper_id in paper_ids:
            db.execute("INSERT INTO bulletin VALUES(?,?)", (run_id, paper_id))
    with TestClient(app, base_url="http://localhost") as client:
        days = client.get("/api/bulletins").json()["days"]
        assert [entry["day"] for entry in days] == ["2026-10-06", "2026-10-05"]
        assert days[1]["total"] == 2 and days[1]["runs"] == 2
        assert days[1]["sources"] == {"colibri": 1, "arxiv": 1}
        archive = client.get("/api/papers?bulletin_day=2026-10-05").json()
        assert archive["total"] == 2
        assert client.get("/api/papers?bulletin_day=2026-10-05&source=arxiv").json()["total"] == 1
        assert client.get("/api/papers?bulletin_day=2026-10-04").json()["total"] == 0
        assert client.get("/api/papers?bulletin_day=invalid").status_code == 422


def test_archived_bulletin_is_not_clipped_by_current_quotas_or_interest_marks(tmp_path, sample):
    app = create_app(tmp_path, start_engine=False)
    db = app.state.db
    run_id = db.execute("INSERT INTO runs(started_at,status,reason,selected,bulletin_day) VALUES('2026-10-01T12:00:00Z','completed','manual',12,'2026-10-01')")
    for number in range(12):
        paper_id = db.add_papers([replace(sample, external_id=f"sample-{number}")])[0]
        db.execute("INSERT INTO bulletin VALUES(?,?)", (run_id, paper_id))
    db.execute("UPDATE papers SET interest=1")
    db.set_meta("settings", {"bulletin_limit": 1})
    with TestClient(app, base_url="http://localhost") as client:
        archived = client.get("/api/papers?bulletin_day=2026-10-01&state=interested").json()
        assert archived["total"] == 12 and len(archived["papers"]) == 12
        assert client.get("/api/bulletins").json()["days"][0]["total"] == 12
        assert client.post("/api/papers/1/jobs/overview", headers={"X-Radar-Request": "1"}).status_code == 200
        assert db.rows("SELECT kind,status FROM jobs") == [{"kind": "summary", "status": "queued"}]
