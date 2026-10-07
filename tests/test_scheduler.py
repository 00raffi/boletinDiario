import asyncio
from datetime import UTC, datetime, timedelta

from radar.config import Settings, daily_slot
from radar.engine import Engine


def test_startup_coalesces_overdue_days_into_one_scan(db, tmp_path):
    async def run():
        engine = Engine(db, tmp_path)
        called = asyncio.Event()
        calls = []

        class FakeSource:
            async def discover(self, start, end, categories):
                calls.append((start, end))
                called.set()
                return []

        now = datetime.now(UTC)
        db.set_meta("last_scan", (now - timedelta(days=4)).isoformat())
        db.set_meta("last_slot", daily_slot(now - timedelta(days=4), Settings()).isoformat())
        engine.sources["arxiv"] = FakeSource()
        await engine.start()
        await asyncio.wait_for(called.wait(), timeout=1)
        await engine.scan_task
        assert len(calls) == 1
        assert calls[0][0] < now - timedelta(days=4)
        assert db.get_meta("last_slot") == daily_slot(now, Settings()).isoformat()
        await engine.stop()

    asyncio.run(run())


def test_job_cancellation_and_shutdown_have_different_recovery(db, sample, tmp_path):
    async def run():
        started = asyncio.Event()

        class WaitingLLM:
            async def models(self):
                started.set()
                await asyncio.Event().wait()

        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "brief")
        engine = Engine(db, tmp_path)
        engine.llm = WaitingLLM()
        job = db.rows("SELECT * FROM jobs")[0]
        engine.job_task = asyncio.create_task(engine.process_job(job))
        await asyncio.wait_for(started.wait(), timeout=1)
        assert engine.cancel()
        await engine.job_task
        assert db.rows("SELECT * FROM jobs")[0]["status"] == "cancelled"
        db.queue(paper_id, "brief", retry=True)
        started.clear()
        engine.job_task = asyncio.create_task(engine.process_job(job))
        await asyncio.wait_for(started.wait(), timeout=1)
        await engine.stop()
        assert db.rows("SELECT * FROM jobs")[0]["status"] == "queued"

    asyncio.run(run())
