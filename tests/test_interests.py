import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from radar.analysis import validate_notes_language
from radar.app import create_app
from radar.catalog import CATEGORIES
from radar.config import Settings
from radar.engine import Engine, select_candidates
from radar.interests import (
    PROFILE_VERSION,
    InferenceBusy,
    InterestProposal,
    positive_filters,
    term_matches,
)
from radar.languages import text_language
from radar.llm import Ollama, validate_brief_fidelity, validate_brief_language
from radar.sources import ArxivSource, search_queries

PROPOSAL = {"interests": [{"topic": "Robotics and computational neuroscience", "source_text": "Robótica y neurociencia",
             "categories": ["cs.RO", "cs.LG", "q-bio.NC"],
             "keywords": ["robot learning", "computational neuroscience"]}],
            "explanation": "The proposed categories and search terms cover robotics and computational neuroscience.", "warnings": []}


class FakeLLM:
    host = "http://127.0.0.1:11435"

    def __init__(self):
        self.calls = 0
        self.unload = AsyncMock()

    async def models(self):
        return ["gemma3:4b", "qwen3.5:4b"]

    async def generate(self, model, prompt, schema, **kwargs):
        assert schema is InterestProposal
        assert kwargs["context_tokens"] == 8192
        self.calls += 1
        proposal = json.loads(json.dumps(PROPOSAL))
        proposal["interests"][0]["source_text"] = json.loads(prompt.split("Original description (data): ")[-1])
        return InterestProposal.model_validate(proposal).model_dump(), {"model": model}


def test_catalog_broader_than_ai_and_aliases_are_canonical():
    assert len(CATEGORIES) > 140
    settings = Settings(categories=["cs.CR", "q-bio.NC", "astro-ph.CO", "math.PR", "cs.NA", "math.NA"])
    assert settings.categories[-1] == "math.NA"
    assert settings.categories.count("math.NA") == 1
    with pytest.raises(ValidationError):
        InterestProposal.model_validate({**PROPOSAL, "interests": [{**PROPOSAL["interests"][0], "categories": ["cs.FAKE"]}]})


def test_proposal_cannot_claim_to_have_included_an_absent_category():
    with pytest.raises(ValueError, match="cs.CR"):
        positive_filters({**PROPOSAL, "explanation": "The proposal includes cs.CR for differential privacy."}, "Robótica y neurociencia", "arxiv")
    positive_filters({**PROPOSAL, "warnings": ["cs.CR could be considered for another focus."]}, "Robótica y neurociencia", "arxiv")


@pytest.mark.parametrize("retry", [False, True])
def test_spanish_brief_needs_no_model_generated_language_label(monkeypatch, retry):
    english = "We present a method for robot learning. Our results are preliminary and do not demonstrate superiority."
    spanish = "En este artículo presentamos un método para el aprendizaje de robots. Los resultados son preliminares."
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        output = english if retry and len(bodies) == 1 else spanish
        return httpx.Response(200, json={"message": {"content": json.dumps({"summary": output,
            "contribution": output, "relevance_reason": output, "relevance": 3, "tags": []})}})

    real = httpx.AsyncClient
    monkeypatch.setattr("radar.llm.httpx.AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    brief = asyncio.run(Ollama().brief({"title": "Robots", "abstract": spanish}, Settings()))
    assert brief["language"] == "es"
    assert brief["summary"] == spanish
    assert brief["stats"]["validation_attempts"] == (2 if retry else 1)
    assert all(body["options"]["num_ctx"] == 4096 for body in bodies)
    assert "language" not in bodies[0]["format"]["properties"]


def test_notes_reject_translation_but_allow_safe_abstention():
    validate_notes_language({"facts": []}, "es")
    with pytest.raises(ValueError):
        validate_notes_language({"facts": [{"claim": "We evaluate our method on the synthetic tasks and report preliminary results."}]}, "es")


def test_terms_are_clean_deduplicated_and_filter_requires_terms():
    settings = Settings(keywords=["  AI ", "ai", '"robot   learning"'], keyword_filter=True)
    assert settings.keywords == ["ai", "robot learning"]
    with pytest.raises(ValidationError):
        Settings(keyword_filter=True)


def test_matching_is_literal_bounded_and_any_term_can_match():
    assert term_matches("AI", "AI-based planning")
    assert not term_matches("AI", "training with data")
    assert not term_matches("art", "an article about robots")
    assert term_matches("robot learning", "Robot\nlearning with demonstrations")
    assert not term_matches("a.*", "abc")
    settings = Settings(categories=["cs.RO", "q-bio.NC"], keywords=["robot learning", "neurons"], keyword_filter=True)
    papers = [
        {"title": "Neurons", "abstract": "", "updated": "2026-10-01", "categories": ["q-bio.NC"]},
        {"title": "Robot learning", "abstract": "", "updated": "2026-10-02", "categories": ["cs.RO"]},
        {"title": "Robot learning", "abstract": "", "updated": "2026-10-03", "categories": ["econ.GN"]},
        {"title": "Irrelevant", "abstract": "", "updated": "2026-10-04", "categories": ["cs.RO"]},
    ]
    assert [paper["title"] for paper in select_candidates(papers, settings)] == ["Robot learning", "Neurons"]


def test_queries_keep_categories_and_literal_terms_and_split_long_lists():
    assert search_queries(["cs.RO"]) == ["(cat:cs.RO)"]
    query = search_queries(["cs.RO", "cs.CR"], ['robot "learning"', 'privacy OR cat:all'])[0]
    assert query.startswith("(cat:cs.RO OR cat:cs.CR) AND (")
    assert '(ti:"robot learning" OR abs:"robot learning")' in query
    assert 'ti:"privacy OR cat:all"' in query
    queries = search_queries(["cs.RO"], ["x" * 70 + str(number) for number in range(80)])
    assert len(queries) > 1
    assert all(len(query) < 3600 for query in queries)
    assert sum(query.count("ti:") for query in queries) == 80


def test_preview_persists_cache_but_never_applies_settings_and_reuses_it(db, tmp_path):
    async def run():
        before = db.settings().model_dump()
        engine = Engine(db, tmp_path)
        engine.llm = FakeLLM()
        first = await engine.compile_interests("Me interesan robótica y neurociencia computacional.")
        assert first["proposal"]["keywords"] == PROPOSAL["interests"][0]["keywords"]
        assert first["proposal"]["interests"][0]["source_text"] == "Me interesan robótica y neurociencia computacional."
        assert "excluded_keywords" not in first["proposal"]
        assert not first["cached"]
        assert db.settings().model_dump() == before
        engine.llm.unload.assert_awaited_once_with(before["model"])
        recovered = Engine(db, tmp_path)
        recovered.llm = FakeLLM()
        second = await recovered.compile_interests("Me interesan robótica y neurociencia computacional.")
        assert second["cached"]
        assert recovered.llm.calls == 0
        recovered.llm.unload.assert_not_awaited()

    asyncio.run(run())


def test_profile_generation_cannot_overlap_jobs_and_reservation_is_cleared_on_error(db, tmp_path):
    async def run():
        engine = Engine(db, tmp_path)
        engine.llm = FakeLLM()
        engine.current_job = {"id": 1}
        with pytest.raises(InferenceBusy):
            await engine.compile_interests("Robótica y seguridad")
        assert not engine.interest_task
        engine.current_job = None
        engine.llm.generate = AsyncMock(side_effect=ValueError("Formato inválido"))
        with pytest.raises(ValueError, match="inválido"):
            await engine.compile_interests("Robótica y seguridad")
        assert not engine.interest_task
        engine.llm.unload.assert_awaited_once()

    asyncio.run(run())


def test_cancelled_profile_releases_model_and_does_not_apply_or_cache(db, tmp_path):
    async def run():
        engine = Engine(db, tmp_path)
        engine.llm = FakeLLM()
        started = asyncio.Event()

        async def generate(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        engine.llm.generate = generate
        task = asyncio.create_task(engine.compile_interests("Robótica y seguridad"))
        await asyncio.wait_for(started.wait(), 1)
        assert engine.interest_task is task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine.interest_task is None
        assert not db.settings().interests_text
        assert db.rows("SELECT key FROM meta WHERE key LIKE ?", (PROFILE_VERSION + ":%",)) == []
        engine.llm.unload.assert_awaited_once()

    asyncio.run(run())


def test_daily_scan_uses_saved_filters_without_compiling_again(db, sample, tmp_path):
    async def run():
        settings = db.settings().model_dump()
        settings.update(keywords=["planning"], keyword_filter=True, interests_text="Este texto no debe llegar a la búsqueda")
        db.set_meta("settings", settings)
        engine = Engine(db, tmp_path)
        source = type("Source", (), {})()
        source.discover = AsyncMock(return_value=[sample])
        engine.sources["arxiv"] = source
        engine.llm = FakeLLM()
        await engine.scan("manual")
        assert engine.llm.calls == 0
        assert source.discover.call_args.kwargs == {"keywords": ["planning"]}
        assert db.rows("SELECT * FROM jobs")[0]["kind"] == "summary"

    asyncio.run(run())


def test_profile_endpoint_security_and_review_before_apply(tmp_path):
    app = create_app(tmp_path, start_engine=False)
    app.state.engine.llm = FakeLLM()
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/api/interests/propose", json={"text": "Robótica y neurociencia"}).status_code == 403
        response = client.post("/api/interests/propose", json={"text": "Robótica y neurociencia"}, headers={"X-Radar-Request": "1"})
        assert response.status_code == 200
        assert client.get("/api/settings").json()["categories"] == ["cs.AI"]
        draft = client.get("/api/settings").json()
        draft.update(categories=response.json()["proposal"]["categories"], keywords=response.json()["proposal"]["keywords"],
                     interests_text="Robótica y neurociencia", keyword_filter=True)
        assert client.put("/api/settings", json=draft, headers={"X-Radar-Request": "1"}).status_code == 200
        assert app.state.db.settings().keyword_filter
        assert app.state.db.settings().interests_text == "Robótica y neurociencia"
        assert "quant-ph" in client.get("/api/categories").json()["categories"]


def test_language_hints_and_fidelity_guard_preserve_english_and_spanish():
    english = "We present a method for robot learning. Our results are preliminary and do not demonstrate superiority."
    spanish = "En este artículo presentamos un método para el aprendizaje de robots. Los resultados son preliminares."
    assert text_language(english) == "en"
    assert text_language(spanish) == "es"
    assert text_language("XYZ 123") is None
    validate_brief_language({"summary": english, "contribution": english, "relevance_reason": english}, {"abstract": english})
    validate_brief_language({"summary": spanish, "contribution": spanish, "relevance_reason": spanish}, {"abstract": spanish})
    with pytest.raises(ValueError):
        validate_brief_language({"summary": spanish, "contribution": spanish, "relevance_reason": spanish}, {"abstract": english})
    with pytest.raises(ValueError, match="competitividad"):
        validate_brief_fidelity({"summary": "Our method outperforms all baselines.", "contribution": "A new method."},
                                {"abstract": "Our method is competitive with the tested baselines."})


def test_explicit_regeneration_preserves_old_result_until_commit(db, sample):
    paper_id = db.add_papers([sample])[0]
    db.queue(paper_id, "brief")
    db.execute("UPDATE papers SET brief=? WHERE id=?", ('{"summary":"Anterior"}', paper_id))
    db.execute("UPDATE jobs SET status='done'")
    db.queue(paper_id, "brief", retry=True)
    assert db.rows("SELECT status FROM jobs")[0]["status"] == "done"
    db.queue(paper_id, "brief", regenerate=True)
    assert db.rows("SELECT status FROM jobs")[0]["status"] == "queued"
    assert db.paper(paper_id)["brief"]["summary"] == "Anterior"


def test_batched_discovery_deduplicates_and_keeps_all_query_groups(monkeypatch):
    feed = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
    <o:totalResults>1</o:totalResults><entry><id>http://arxiv.org/abs/2610.00001v1</id><title>Robots</title>
    <summary>Robot learning.</summary><published>2026-10-01T00:00:00Z</published><updated>2026-10-05T12:00:00Z</updated>
    <category term="cs.RO"/></entry></feed>'''
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=feed)

    real = httpx.AsyncClient
    monkeypatch.setattr("radar.sources.httpx.AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    source = ArxivSource()
    source.pace = AsyncMock()
    terms = ["x" * 70 + str(number) for number in range(40)]
    result = asyncio.run(source.discover(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 6, tzinfo=UTC),
                                         ["cs.RO"], keywords=terms))
    assert len(calls) == len(search_queries(["cs.RO"], terms)) > 1
    assert len(result) == 1
