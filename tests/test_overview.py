import asyncio
from unittest.mock import AsyncMock

import pytest

from radar.engine import Engine
from radar.overview import (
    SectionDraft,
    SupportDraft,
    article_overview,
    detect_sections,
    grounded_draft,
    grounded_support,
    heading_span,
    sample_section,
    section_sources,
    validate_section,
    validate_support,
)


def extracted():
    return {"total_pages": 4, "extraction_partial": False, "pages": [
        {"page": 1, "text": "Introduction\nWe describe a method for measuring signals in a controlled experiment."},
        {"page": 2, "text": "Method\nWe apply the procedure to a synthetic dataset with fixed conditions."},
        {"page": 3, "text": "Conclusion\nThe authors report preliminary findings and identify limitations of the method."},
        {"page": 4, "text": "Funding\nThis study was funded by Research Council under grant A123."}],
        "headings": [{"title": title, "level": 0, "page": page} for page, title in enumerate(
            ["Introduction", "Method", "Conclusion", "Funding"], 1)]}


def test_outline_uses_main_sections_in_order_and_keeps_conclusion():
    data = extracted()
    data["headings"].insert(3, {"title": "Conclusions in detail", "page": 3, "level": 1})
    sections, mode = detect_sections(data)
    assert mode == "pdf_outline"
    assert [s["title"] for s in sections] == ["Introduction", "Method", "Conclusion"]
    assert [s["excerpts"][0]["page"] for s in sections] == [1, 2, 3]
    assert "funded" not in sections[-1]["excerpts"][-1]["text"]


def test_same_page_sections_do_not_use_neighboring_results():
    data = {"total_pages": 1, "pages": [{"page": 1, "text": "Method\nWe measured carefully.\nConclusion\nWe report limited findings."}],
            "headings": [{"title": "Method", "page": 1, "level": 0}, {"title": "Conclusion", "page": 1, "level": 0}]}
    sections, _ = detect_sections(data)
    assert "limited findings" not in sections[0]["excerpts"][0]["text"]
    assert "measured" not in sections[1]["excerpts"][0]["text"]


def test_spaced_pdf_heading_is_found_without_matching_body_mentions_or_bibliography():
    text = "We discuss the conclusion elsewhere.\n7 C ONCLUSION\nThe authors report limited findings.\n"
    assert heading_span(text, "Conclusion") == (text.index("7 C ONCLUSION"), text.index("The authors"))
    data = {"total_pages": 3, "headings": [{"title": "Related work", "page": 1, "level": 0},
            {"title": "Conclusion", "page": 1, "level": 0}], "pages": [
        {"page": 1, "text": "6 R ELATED W ORK\nA prior study reports impressive results.\n7 C ONCLUSION\nOur method retains limitations."},
        {"page": 2, "text": "References\nA bibliography, not a conclusion."},
        {"page": 3, "text": "Appendix\nSupplementary discussion."}]}
    sections, _ = detect_sections(data)
    conclusion = sections[-1]
    assert conclusion["excerpts"] == [{"page": 1, "text": "Our method retains limitations."}]


def test_text_heading_fallback_rejects_toc_equations_and_numbered_sentences():
    data = {"total_pages": 3, "pages": [
        {"page": 1, "text": "Índice general\n1 Introduction ............ 2\n2 Conclusion ......... 3"},
        {"page": 2, "text": "1 Introduction\nWe introduce the method with assumptions.\n1. This is a numbered claim.\n2 rr = xx"},
        {"page": 3, "text": "2 Conclusion\nThe result remains preliminary.\nReferences\nPrior work."}]}
    sections, mode = detect_sections(data)
    assert mode == "text_headings"
    assert [s["title"] for s in sections] == ["1 Introduction", "2 Conclusion"]
    assert "Prior work" not in sections[-1]["excerpts"][-1]["text"]


def test_quotes_require_actual_section_and_support_is_not_affiliation():
    excerpt = [{"page": 1, "text": "The authors are affiliated with Example University."}]
    with pytest.raises(ValueError):
        validate_section({"summary": "An unsupported claim", "evidence": []}, excerpt, None)
    with pytest.raises(ValueError):
        validate_section({"summary": "A claim", "evidence": [{"page": 2, "quote": excerpt[0]["text"]}]}, excerpt, None)
    with pytest.raises(ValueError, match="afiliación"):
        validate_support({"organizations": [{"name": "Example University", "role": "support", "quote": excerpt[0]["text"], "page": 1}]}, excerpt)
    quote = "This study was funded by Research Council under grant A123."
    validate_support({"organizations": [{"name": "Research Council", "role": "funding", "quote": quote, "page": 4}]}, [{"page": 4, "text": quote}])


def test_section_sampling_is_bounded_and_cites_actual_pages():
    sample = sample_section({"excerpts": [{"page": 1, "text": "a" * 9000}, {"page": 9, "text": "b" * 9000}]})
    assert sum(len(p["text"]) for p in sample) <= 4000
    assert [p["page"] for p in sample] == [1, 9]


def test_identified_evidence_is_copied_not_rewritten_by_the_model():
    text = "The power distribution with exponent α≥1 uses Zα(x), and preserves the conditions stated in the paper."
    excerpts = [{"page": 5, "text": text}]
    sources = section_sources(excerpts)
    grounded = grounded_draft({"summary": "The authors describe a conditioned distribution.", "evidence_ids": ["S1"]}, sources, "en")
    assert grounded["evidence"] == [{"quote": text, "page": 5}]
    validate_section(grounded, excerpts, "en")
    with pytest.raises(ValueError, match="identificadores"):
        grounded_draft({"summary": "Invented evidence", "evidence_ids": ["S999"]}, sources, "en")
    with pytest.raises(ValueError, match="identificadores"):
        grounded_draft({"summary": "No evidence", "evidence_ids": []}, sources, "en")


def test_support_names_and_signals_are_checked_after_python_copies_evidence():
    excerpts = [{"page": 2, "text": "This work was funded by Research Council under grant B2026."}]
    sources = section_sources(excerpts)
    result = grounded_support({"organizations": [{"name": "Research Council", "role": "funding", "evidence_id": "S1"}]}, sources, excerpts)
    assert result["organizations"][0]["quote"] == excerpts[0]["text"]
    with pytest.raises(ValueError, match="nombre"):
        grounded_support({"organizations": [{"name": "Imaginary Foundation", "role": "funding", "evidence_id": "S1"}]}, sources, excerpts)


def test_spanish_section_summary_is_not_translated():
    sources = [{"id": "S1", "page": 2, "quote": "Los autores describen el método y las condiciones de sus resultados."}]
    result = {"summary": "Los autores describen el método y las condiciones de sus resultados.", "evidence_ids": ["S1"]}
    assert grounded_draft(result, sources, "es")["summary"] == result["summary"]
    with pytest.raises(ValueError):
        grounded_draft({**result, "summary": "The authors describe the method and the conditions of their results."}, sources, "es")


def test_overview_persists_caches_and_uses_pdf_not_abstract(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        paper = db.paper(paper_id)
        (tmp_path / "documents").mkdir()
        (tmp_path / f"documents/{paper_id}.pdf").write_bytes(b"existing PDF")
        extractor = AsyncMock(return_value=extracted())
        monkeypatch.setattr("radar.overview.extract_pdf", extractor)
        calls = []

        class LLM:
            async def generate(self, model, prompt, schema, **kwargs):
                calls.append(schema)
                assert sample.abstract not in prompt
                if schema is SupportDraft:
                    result = {"organizations": [{"name": "Research Council", "role": "funding", "evidence_id": "S1"}]}
                else:
                    assert schema is SectionDraft
                    title = next(title for title in ("Introduction", "Method", "Conclusion") if f'Sección: "{title}"' in prompt)
                    page = {"Introduction": 1, "Method": 2, "Conclusion": 3}[title]
                    text = extracted()["pages"][page - 1]["text"].split("\n")[1]
                    result = {"summary": text, "evidence_ids": ["S1"]}
                kwargs["validator"](result)
                return result, {}

        source = type("Source", (), {"document": AsyncMock()})()
        progress = []
        result = await article_overview(paper, db.settings(), source, LLM(), db, tmp_path, progress.append)
        assert len(result["sections"]) == 3 and result["coverage"]["conclusion_detected"]
        assert result["support"][0]["name"] == "Research Council"
        assert len(calls) == 4
        repeat = await article_overview(paper, db.settings(), source, LLM(), db, tmp_path, progress.append)
        assert repeat["sections"] == result["sections"] and len(calls) == 4
        source.document.assert_not_awaited()
        assert "Secciones confirmadas 3/3" in progress
    asyncio.run(run())


def test_overview_without_real_headings_fails_without_inference(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        source = type("Source", (), {"document": AsyncMock(return_value=b"PDF")})()
        monkeypatch.setattr("radar.overview.extract_pdf", AsyncMock(return_value={"pages": [{"page": 1, "text": "No headings in this text."}], "total_pages": 1}))
        llm = type("LLM", (), {"generate": AsyncMock()})()
        with pytest.raises(ValueError, match="estructura"):
            await article_overview(db.paper(paper_id), db.settings(), source, llm, db, tmp_path, lambda message: None)
        llm.generate.assert_not_awaited()
    asyncio.run(run())


def test_overview_job_does_not_replace_abstract_brief_or_technical_report(db, sample, tmp_path, monkeypatch):
    async def run():
        paper_id = db.add_papers([sample])[0]
        db.execute("UPDATE papers SET brief=?,analysis=? WHERE id=?", ('{"summary":"Existing"}', '{"method":"Existing"}', paper_id))
        db.queue(paper_id, "overview")
        monkeypatch.setattr("radar.engine.article_overview", AsyncMock(return_value={"sections": [], "support": []}))
        engine = Engine(db, tmp_path)
        engine.llm.models = AsyncMock(return_value=[db.settings().model])
        await engine.process_job(db.rows("SELECT * FROM jobs")[0])
        assert db.paper(paper_id)["overview"] == {"sections": [], "support": []}
        assert db.paper(paper_id)["brief"]["summary"] == "Existing"
        assert db.paper(paper_id)["analysis"]["method"] == "Existing"
    asyncio.run(run())
