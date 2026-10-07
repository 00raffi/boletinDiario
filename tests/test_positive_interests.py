import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from radar.catalog import CATEGORIES
from radar.config import Settings
from radar.interests import (
    ARXIV_SYSTEM,
    COLIBRI_SYSTEM,
    InterestProposal,
    TermProposal,
    positive_filters,
    propose_colibri_interests,
    propose_interests,
)
from radar.llm import Ollama
from radar.sources import search_queries

TEXT = "Me interesan la astronomía y la lógica."
ARXIV = {"interests": [{"topic": "Astronomy", "source_text": "astronomía", "categories": ["astro-ph.CO"],
                       "keywords": ["astronomy", "astrophysics"]},
                      {"topic": "Logic", "source_text": "lógica", "categories": ["cs.LO", "math.LO"],
                       "keywords": ["logic", "formal logic"]}],
         "explanation": "The categories and terms cover the stated interests in astronomy and logic.", "warnings": []}
COLIBRI = {"interests": [{"topic": "Astronomía", "source_text": "astronomía", "keywords": ["astronomía", "astronomy"]},
                        {"topic": "Lógica", "source_text": "lógica", "keywords": ["lógica", "logic"]}],
           "explanation": "Los términos propuestos cubren los intereses indicados en astronomía y lógica.", "warnings": []}


def test_exclusions_are_not_part_of_either_model_schema_and_are_rejected():
    for schema, draft in ((InterestProposal, ARXIV), (TermProposal, COLIBRI)):
        assert "excluded_keywords" not in schema.model_json_schema()["properties"]
        with pytest.raises(ValidationError):
            schema.model_validate({**draft, "excluded_keywords": ["astronomy"]})
        with pytest.raises(ValidationError):
            schema.model_validate({**draft, "interests": [{**draft["interests"][0], "excluded_keywords": ["logic"]}]})


def test_arxiv_json_schema_enumerates_only_real_categories_for_constrained_generation():
    schema = InterestProposal.model_json_schema()
    allowed = schema["$defs"]["ArxivInterestTerms"]["properties"]["categories"]["items"]["enum"]
    assert set(allowed) == set(CATEGORIES)
    assert "cs.HO" not in allowed
    assert "cs.GL" in allowed and "math.HO" in allowed


def test_grouped_interests_are_grounded_flattened_and_deduplicated():
    draft = json.loads(json.dumps(ARXIV))
    draft["interests"][1]["keywords"].append("Astronomy")
    proposal = positive_filters(draft, TEXT, "arxiv")
    assert proposal["categories"] == ["astro-ph.CO", "cs.LO", "math.LO"]
    assert proposal["keywords"] == ["astronomy", "astrophysics", "logic", "formal logic"]
    assert len(proposal["interests"]) == 2
    assert "excluded_keywords" not in proposal
    draft["interests"][0]["source_text"] = "robotics"
    with pytest.raises(ValueError, match="exact continuous quote"):
        positive_filters(draft, TEXT, "arxiv")


def test_arxiv_and_colibri_explanations_cannot_switch_output_language():
    with pytest.raises(ValueError, match="English"):
        positive_filters({**ARXIV, "explanation": COLIBRI["explanation"]}, TEXT, "arxiv")
    with pytest.raises(ValueError, match="español"):
        positive_filters({**COLIBRI, "explanation": ARXIV["explanation"]}, TEXT, "colibri")


def test_spanish_short_arxiv_topics_are_detected_together():
    labels = ["diseño de algoritmos", "teoría de la computación", "historia de la computación"]
    text = ", ".join(labels)
    draft = {**ARXIV, "interests": [{**ARXIV["interests"][0], "topic": label, "source_text": label} for label in labels]}
    with pytest.raises(ValueError, match="English"):
        positive_filters(draft, text, "arxiv")


@pytest.mark.parametrize("code", ["cs.AI", "cs.HO", "math.GM", "math-ph", "q-bio.NC", "astro-ph.CO", "CS.AI", "cs.ai artificial intelligence"])
def test_arxiv_rejects_category_codes_in_search_words_including_invented_codes(code):
    draft = {**ARXIV, "interests": [{**ARXIV["interests"][0], "keywords": [code]}]}
    with pytest.raises(ValidationError, match="not category codes"):
        positive_filters(draft, TEXT, "arxiv")


def test_more_than_24_categories_and_80_terms_are_valid_and_every_term_reaches_queries():
    codes = list(CATEGORIES)[:35]
    terms = [f"research topic {index}" for index in range(160)]
    draft = {**ARXIV, "interests": [{**ARXIV["interests"][0], "categories": codes, "keywords": terms}]}
    proposal = positive_filters(draft, TEXT, "arxiv")
    settings = Settings(categories=proposal["categories"], keywords=proposal["keywords"],
                        colibri_keywords=terms, keyword_filter=True)
    assert len(settings.categories) > 24
    assert len(settings.keywords) == len(settings.colibri_keywords) == 160
    queries = search_queries(settings.categories, settings.keywords)
    assert sum(query.count("ti:") for query in queries) == 160
    assert all(len(query) < 3600 for query in queries)


@pytest.mark.parametrize("source,draft,system", [("arxiv", ARXIV, ARXIV_SYSTEM), ("colibri", COLIBRI, COLIBRI_SYSTEM)])
def test_real_client_sends_source_specific_system_and_rejects_generated_exclusions(monkeypatch, source, draft, system):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        result = {**draft, "excluded_keywords": ["astronomy"]} if len(bodies) == 1 else draft
        return httpx.Response(200, json={"message": {"content": json.dumps(result, ensure_ascii=False)}})

    real = httpx.AsyncClient
    monkeypatch.setattr("radar.llm.httpx.AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    llm = Ollama()
    if source == "arxiv":
        result, stats = asyncio.run(propose_interests(llm, "qwen3.5:4b", TEXT))
        assert "Decompose" in bodies[0]["messages"][1]["content"]
        assert "The previous attempt was invalid" in bodies[1]["messages"][1]["content"]
    else:
        result, stats = asyncio.run(propose_colibri_interests(llm, "qwen3.5:4b", TEXT, Settings().colibri_scopes))
        assert "Desglosa" in bodies[0]["messages"][1]["content"]
        assert "El intento anterior fue inválido" in bodies[1]["messages"][1]["content"]
    assert "excluded_keywords" not in result
    assert stats["validation_attempts"] == 2
    assert all(body["messages"][0]["content"] == system for body in bodies)
    assert all(body["options"]["num_predict"] == 4096 and body["options"]["num_ctx"] == 8192 for body in bodies)


def test_prompt_does_not_request_dislikes_or_limit_interest_counts():
    async def run():
        llm = type("LLM", (), {})()
        llm.generate = AsyncMock(return_value=(ARXIV, {}))
        await propose_interests(llm, "qwen3.5:4b", TEXT)
        prompt = llm.generate.call_args.args[1]
        assert "no fixed numerical cap" in prompt
        assert "Do not output excluded_keywords" in prompt
        assert "40 exclusiones" not in prompt
    asyncio.run(run())
