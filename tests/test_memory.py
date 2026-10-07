import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from radar.analysis import NOTES_VERSION, detailed_analysis, fragment_prompt
from radar.config import Settings
from radar.engine import Engine
from radar.llm import ChunkNotes, Ollama, validate_brief_fidelity


def test_memory_defaults_and_validation():
    settings = Settings()
    assert settings.model == "qwen3.5:4b"
    assert settings.unload_after_paper
    assert settings.recycle_every_chunks == 4
    with pytest.raises(ValueError):
        Settings(recycle_every_chunks=-1)


@pytest.mark.parametrize("host", ["http://example.com:11434", "http://0.0.0.0:11434",
                                 "http://user:pass@localhost:11434", "http://127.0.0.1/api",
                                 "http://localhost:11434?proxy=1"])
def test_ollama_rejects_nonlocal_or_ambiguous_endpoints(monkeypatch, host):
    monkeypatch.setattr("radar.llm.HOST", host)
    with pytest.raises(ValueError):
        Ollama()


def test_ollama_accepts_dedicated_local_endpoint(monkeypatch):
    monkeypatch.setattr("radar.llm.HOST", "http://127.0.0.1:11435/")
    assert Ollama().host == "http://127.0.0.1:11435"


def test_brief_prompt_requires_conditions_and_author_attribution():
    llm = Ollama()
    llm.generate = AsyncMock(return_value=({"summary": "Resumen de prueba"}, {}))
    paper = {"title": "Garantía condicionada", "abstract": "A bound holds only under independent detector outcomes."}
    asyncio.run(llm.brief(paper, Settings()))
    prompt = llm.generate.call_args.args[1]
    assert "nunca presentes como universal una garantía condicionada" in prompt
    assert "Atribuye hallazgos a los autores" in prompt
    assert "resultado es preliminar" in prompt
    assert paper["abstract"] in prompt


def test_brief_rejects_unsupported_superiority_but_allows_explicit_source_claims():
    paper = {"abstract": "Our model is competitive with self-supervised representations across five tasks."}
    result = {"summary": "El modelo supera a otras representaciones en cinco tareas.", "contribution": "Un método nuevo."}
    with pytest.raises(ValueError, match="competitividad"):
        validate_brief_fidelity(result, paper)
    validate_brief_fidelity({**result, "summary": "El modelo es competitivo en cinco tareas."}, paper)
    validate_brief_fidelity(result, {"abstract": "Our model is competitive and outperforms baseline B."})


def test_content_guard_retries_without_accumulating_response_history(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"facts": []}'}})

    def guard(result):
        if len(bodies) == 1:
            raise ValueError("Una afirmación no respeta el alcance de la fuente")

    real_client = httpx.AsyncClient
    monkeypatch.setattr("radar.llm.httpx.AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs))
    _, stats = asyncio.run(Ollama().generate("qwen3.5:4b", "Fragmento actual", ChunkNotes, validator=guard))
    assert stats["validation_attempts"] == 2
    assert len(bodies[1]["messages"]) == 2
    assert "no respeta el alcance" in bodies[1]["messages"][-1]["content"]


def test_fragment_prompt_contains_only_current_document_data():
    chunk = {"page": 9, "text": "Texto del fragmento actual."}
    prompt = fragment_prompt({"title": "Paper de prueba", "brief": "Resumen anterior"}, chunk)
    assert "paper Paper de prueba" in prompt
    assert "page=9" in prompt
    assert json.dumps(chunk, ensure_ascii=False) in prompt
    assert "Resumen anterior" not in prompt
    assert "copiados EXACTAMENTE" in prompt


def test_unload_uses_local_api_without_prompt(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"done": True, "done_reason": "unload"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("radar.llm.httpx.AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(Ollama().unload("gemma3:4b"))
    assert result["done_reason"] == "unload"
    assert str(requests[0].url) == "http://127.0.0.1:11434/api/generate"
    assert json.loads(requests[0].content) == {"model": "gemma3:4b", "stream": False, "keep_alive": 0}


def test_requests_never_accumulate_conversation(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"facts": []}'}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("radar.llm.httpx.AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs))

    async def run():
        llm = Ollama()
        await llm.generate("gemma3:4b", "Fragmento anterior", ChunkNotes)
        await llm.generate("gemma3:4b", "Fragmento actual", ChunkNotes)

    asyncio.run(run())
    assert all(body["options"]["num_ctx"] == 4096 for body in bodies)
    assert all(body["think"] is False for body in bodies)
    assert all(body["options"]["presence_penalty"] == 0 for body in bodies)
    assert len(bodies[1]["messages"]) == 2
    assert bodies[1]["messages"][-1]["content"] == "Fragmento actual"
    assert "Fragmento anterior" not in json.dumps(bodies[1])


@pytest.mark.parametrize("recovers", [False, True])
def test_qwen_format_retry_is_bounded_and_keeps_independent_messages(monkeypatch, recovers):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        content = '{"facts": []}' if recovers and len(bodies) == 2 else '{"incorrect": "datos"}'
        return httpx.Response(200, json={"message": {"content": content}, "done_reason": "stop"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("radar.llm.httpx.AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs))
    call = Ollama().generate("qwen3.5:4b", "Solo el fragmento actual", ChunkNotes, output_tokens=1500)
    if recovers:
        result, stats = asyncio.run(call)
        assert result == {"facts": []}
        assert stats["format_attempts"] == 2
        assert stats["thinking"] is False
        assert stats["presence_penalty"] == 0
    else:
        with pytest.raises(ValueError, match="tras un reintento"):
            asyncio.run(call)
    assert len(bodies) == 2
    assert all(len(body["messages"]) == 2 for body in bodies)
    assert all(body["options"]["num_predict"] == 1500 for body in bodies)
    assert "Corrige estas restricciones" in bodies[1]["messages"][-1]["content"]
    assert "incorrect" not in bodies[1]["messages"][-1]["content"]


@pytest.mark.parametrize("failure", [False, True])
def test_cleanup_is_after_commit_and_failure_keeps_result(db, sample, tmp_path, failure):
    db.set_meta("settings", {"model": "gemma3:4b", "desktop_notifications": False, "unload_after_paper": True})
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "brief")
    engine = Engine(db, tmp_path)

    class FakeLLM:
        async def models(self):
            return ["gemma3:4b"]

        async def brief(self, paper, settings):
            return {"summary": "Resultado guardado"}

        async def unload(self, model):
            assert db.paper(paper_id)["brief"] is not None
            assert db.rows("SELECT * FROM jobs")[0]["status"] == "done"
            if failure:
                raise httpx.ConnectError("Ollama desconectado")

    engine.llm = FakeLLM()
    asyncio.run(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "done"
    assert db.get_meta("last_model_release")["status"] == ("error" if failure else "released")


def test_cancelled_inference_also_unloads(db, sample, tmp_path):
    async def run():
        db.set_meta("settings", {"model": "gemma3:4b", "desktop_notifications": False, "unload_after_paper": True})
        paper_id = db.add_papers([sample])[0]
        db.queue(paper_id, "brief")
        engine = Engine(db, tmp_path)
        started = asyncio.Event()

        class FakeLLM:
            unload = AsyncMock()

            async def models(self):
                return ["gemma3:4b"]

            async def brief(self, paper, settings):
                started.set()
                await asyncio.Event().wait()

        engine.llm = FakeLLM()
        engine.job_task = asyncio.create_task(engine.process_job(db.rows("SELECT * FROM jobs")[0]))
        await asyncio.wait_for(started.wait(), timeout=1)
        await engine.stop()
        engine.llm.unload.assert_awaited_once_with("gemma3:4b")
        assert db.rows("SELECT * FROM jobs")[0]["status"] == "queued"

    asyncio.run(run())


@pytest.mark.parametrize("interval,expected", [(4, 1), (2, 2), (0, 0)])
def test_recycles_between_chunks_only_after_persisting_notes(db, sample, tmp_path, monkeypatch, interval, expected):
    quote = "We evaluate a controlled benchmark for AI agents."

    async def extraction(path):
        return {"pages": [{"page": page, "text": quote} for page in range(1, 6)],
                "total_pages": 5, "extraction_partial": False}

    monkeypatch.setattr("radar.analysis.extract_pdf", extraction)

    class Source:
        async def document(self, paper):
            return b"%PDF-placeholder"

    class FakeLLM:
        generations = 0
        releases = 0

        async def generate(self, model, prompt, schema, **kwargs):
            self.generations += 1
            return {"facts": [{"section": "evaluation", "claim": "Evaluación en un benchmark controlado.",
                               "quote": quote, "page": self.generations}]}, {"model": model}

        async def unload(self, model):
            stored = db.rows("SELECT value FROM meta WHERE key LIKE ?", (NOTES_VERSION + ":%",))[0]
            assert len(json.loads(stored["value"])) == self.generations
            self.releases += 1

    paper_id = db.add_papers([sample])[0]
    llm = FakeLLM()
    settings = Settings(max_chunks=5, recycle_every_chunks=interval)
    result = asyncio.run(detailed_analysis(db.paper(paper_id), settings, Source(), llm, db, tmp_path, lambda text: None))
    assert result["grounded_facts"] == 5
    assert llm.releases == expected
    asyncio.run(detailed_analysis(db.paper(paper_id), settings, Source(), llm, db, tmp_path, lambda text: None))
    assert llm.generations == 5
    assert llm.releases == expected
