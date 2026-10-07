import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from radar.app import create_app
from radar.config import Settings
from radar.engine import Engine
from radar.notifications import DesktopNotifier


class FakeLLM:
    async def unload(self, model):
        return {"done_reason": "unload"}

    async def models(self):
        return ["gemma3:4b", "qwen3.5:4b"]

    async def brief(self, paper, settings):
        return {"summary": "Resumen de prueba", "scope": "abstract"}


def test_notification_default_is_enabled():
    assert Settings().desktop_notifications is True


def test_completion_names_and_escapes_external_title(monkeypatch):
    notifier = DesktopNotifier()
    send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr(notifier, "_send", send)
    paper = {"title": '<b>AI</b> & "agents"\x00'}
    asyncio.run(notifier.completion(paper, "brief"))
    summary, body = send.call_args.args
    assert summary == "Resumen listo"
    assert body == "&lt;b&gt;AI&lt;/b&gt; &amp; &quot;agents&quot;"
    asyncio.run(notifier.completion(paper, "analysis", partial=True))
    assert "Análisis técnico listo · lectura parcial" in send.call_args.args[0]


def test_missing_notify_send_is_nonfatal(monkeypatch):
    monkeypatch.setattr("radar.notifications.shutil.which", lambda executable: None)
    result = asyncio.run(DesktopNotifier().test())
    assert result["status"] == "unavailable"
    assert "notify-send" in result["error"]


def test_native_notification_uses_argv_not_shell(monkeypatch):
    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    spawn = AsyncMock(return_value=Process())
    monkeypatch.setattr("radar.notifications.shutil.which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr("radar.notifications.asyncio.create_subprocess_exec", spawn)
    assert asyncio.run(DesktopNotifier().test())["status"] == "sent"
    args, kwargs = spawn.call_args
    assert args[0] == "/usr/bin/notify-send"
    assert "--" in args
    assert "shell" not in kwargs


def test_timed_out_notification_kills_child(monkeypatch):
    class Process:
        returncode = None
        killed = False

        async def communicate(self):
            raise TimeoutError()

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    child = Process()
    monkeypatch.setattr("radar.notifications.shutil.which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr("radar.notifications.asyncio.create_subprocess_exec", AsyncMock(return_value=child))
    assert asyncio.run(DesktopNotifier().test())["status"] == "error"
    assert child.killed


@pytest.mark.parametrize("status", ["sent", "error", "unavailable"])
def test_notice_is_after_commit_and_does_not_change_job_result(db, sample, tmp_path, status):
    db.set_meta("settings", {"desktop_notifications": True})
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "brief")
    engine = Engine(db, tmp_path)
    engine.llm = FakeLLM()

    class Notifier:
        async def completion(self, paper, kind, **kwargs):
            assert db.paper(paper_id)["brief"] is not None
            assert db.rows("SELECT * FROM jobs")[0]["status"] == "done"
            assert kind == "brief"
            return {"status": status, "error": "simulated"} if status != "sent" else {"status": status}

    engine.notifier = Notifier()
    asyncio.run(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "done"
    assert db.get_meta("last_notification")["status"] == status
    db.recover()
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "done"


def test_disabled_notifications_emit_nothing(db, sample, tmp_path):
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "brief")
    engine = Engine(db, tmp_path)
    engine.llm = FakeLLM()
    engine.notifier.completion = AsyncMock()
    asyncio.run(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
    engine.notifier.completion.assert_not_awaited()


def test_failed_processing_emits_no_success_notice(db, sample, tmp_path):
    db.set_meta("settings", {"desktop_notifications": True})
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "brief")
    engine = Engine(db, tmp_path)
    engine.llm = FakeLLM()
    engine.llm.brief = AsyncMock(side_effect=ValueError("falló inferencia"))
    engine.notifier.completion = AsyncMock()
    asyncio.run(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "error"
    engine.notifier.completion.assert_not_awaited()


def test_cancellation_during_notice_keeps_completed_job(db, sample, tmp_path):
    async def run():
        db.set_meta("settings", {"desktop_notifications": True})
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "brief")
        engine = Engine(db, tmp_path)
        engine.llm = FakeLLM()
        notifying = asyncio.Event()

        async def completion(*args, **kwargs):
            notifying.set()
            await asyncio.Event().wait()

        engine.notifier.completion = completion
        engine.job_task = asyncio.create_task(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
        await asyncio.wait_for(notifying.wait(), timeout=1)
        await engine.stop()
        assert db.rows("SELECT * FROM jobs")[0]["status"] == "done"
        assert db.paper(paper_id)["brief"] is not None

    asyncio.run(run())


def test_notification_test_endpoint_security(tmp_path):
    app = create_app(tmp_path, start_engine=False)
    app.state.engine.notifier.test = AsyncMock(return_value={"status": "sent"})
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/api/notifications/test").status_code == 403
        headers = {"X-Radar-Request": "1"}
        assert client.post("/api/notifications/test", headers=headers).json()["status"] == "sent"
        app.state.engine.notifier.test = AsyncMock(return_value={"status": "unavailable", "error": "No hay escritorio"})
        response = client.post("/api/notifications/test", headers=headers)
        assert response.status_code == 503
        assert app.state.db.get_meta("last_notification")["status"] == "unavailable"
