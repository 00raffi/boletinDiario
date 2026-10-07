import asyncio
import hashlib
import io
import json

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from radar.analysis import (
    NOTES_VERSION,
    build_report,
    detailed_analysis,
    extract_pdf,
    verify_evidence,
)
from radar.config import Settings
from radar.llm import Brief, ChunkNotes


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    content = DecodedStreamObject()
    sentence = "We evaluate a planning method using a controlled benchmark. "
    content.set_data(("BT /F1 12 Tf 30 700 Td (" + sentence * 80 + ") Tj ET").encode())
    page[NameObject("/Contents")] = content
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extraction_runs_in_child_process(tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(sample_pdf())
    result = asyncio.run(extract_pdf(path))
    assert result["total_pages"] == 1
    assert "controlled benchmark" in result["pages"][0]["text"]


def test_bad_pdf_fails_safely(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        asyncio.run(extract_pdf(path))


def test_partial_analysis_grounding_and_cache(db, sample, tmp_path):
    class FakeSource:
        async def document(self, paper):
            return sample_pdf()

    class FakeLLM:
        calls = 0

        async def generate(self, model, prompt, schema, **kwargs):
            if schema is ChunkNotes:
                self.calls += 1
                return {"facts": [
                    {"section": "evaluation", "claim": "Se evalúa en un benchmark controlado.",
                     "quote": "We evaluate a planning method using a controlled benchmark.", "page": 1},
                    {"section": "results", "claim": "Resultado inventado que debe descartarse.",
                     "quote": "The accuracy was 100 percent on all tasks.", "page": 1},
                ]}, {"model": model}
            raise AssertionError("No se debe generar una síntesis libre después de las notas.")

    paper_id = db.add_papers([sample])[0]
    paper = db.paper(paper_id)
    llm = FakeLLM()
    settings = Settings(max_chunks=1)
    progress = []
    result = asyncio.run(detailed_analysis(paper, settings, FakeSource(), llm, db, tmp_path, progress.append))
    assert result["scope"] == "partial_text"
    assert result["grounded_facts"] == 1
    assert result["coverage"]["chunks_extracted"] == 2
    assert len(result["evidence"]) == 1
    assert "benchmark controlado" in result["evaluation"]
    assert "100 percent" not in json.dumps(result)
    key = db.rows("SELECT key FROM meta WHERE key LIKE ?", (NOTES_VERSION + ":%",))[0]["key"]
    notes = db.get_meta(key)
    notes[0]["facts"].append(dict(notes[0]["facts"][0]))
    db.set_meta(key, notes)
    asyncio.run(detailed_analysis(paper, settings, FakeSource(), llm, db, tmp_path, progress.append))
    assert llm.calls == 1
    assert len(db.get_meta(key)[0]["facts"]) == 1


def test_literal_evidence_deduplicates_without_merging_different_claims():
    quote = "We evaluate a planning method using a controlled benchmark."
    first = {"section": "evaluation", "claim": "Se usa un benchmark controlado.", "quote": quote, "page": 1}
    second = {**first, "claim": "Se evalúa un método de planificación."}
    assert verify_evidence([first, dict(first), second], {"page": 1, "text": quote}) == [first, second]


@pytest.mark.parametrize("quote", ["†Work done during a summer internship.",
                                  "*Equal contribution, listed in random order.",
                                  "‡Equal co-advising.", "Prior work by Smith reports 95% accuracy."])
def test_obvious_editorial_and_exclusively_prior_work_notes_are_rejected(quote):
    fact = {"section": "author_limitations", "claim": "Nota que no corresponde al trabajo actual.",
            "quote": quote, "page": 1}
    assert verify_evidence([fact], {"page": 1, "text": quote}) == []


def test_prior_work_comparison_with_explicit_own_result_is_not_blindly_rejected():
    quote = "Prior work achieves 80%, whereas our method achieves 85%."
    fact = {"section": "results", "claim": "El método de los autores alcanza 85% frente a 80%.",
            "quote": quote, "page": 1}
    assert verify_evidence([fact], {"page": 1, "text": quote}) == [fact]


def test_new_prompt_does_not_reuse_legacy_notes(db, sample, tmp_path):
    body = sample_pdf()
    paper_id = db.add_papers([sample])[0]
    settings = Settings(max_chunks=1)
    digest = hashlib.sha256(body).hexdigest()[:16]
    suffix = f":{paper_id}:{settings.model}:1:{digest}"
    db.set_meta("grounded-notes-v2" + suffix, [{"facts": []}])

    class Source:
        async def document(self, paper):
            return body

    class LLM:
        calls = 0

        async def generate(self, *args, **kwargs):
            self.calls += 1
            return {"facts": []}, {}

    llm = LLM()
    asyncio.run(detailed_analysis(db.paper(paper_id), settings, Source(), llm, db, tmp_path, lambda message: None))
    assert llm.calls == 1
    assert db.get_meta(NOTES_VERSION + suffix) == [{"facts": []}]
    assert db.get_meta("grounded-notes-v2" + suffix) == [{"facts": []}]


def test_no_grounded_facts_means_no_factual_synthesis(db, sample, tmp_path):
    class FakeSource:
        async def document(self, paper):
            return sample_pdf()

    class FakeLLM:
        async def generate(self, model, prompt, schema, **kwargs):
            assert schema is ChunkNotes
            return {"facts": []}, {"model": model}

    paper_id = db.add_papers([sample])[0]
    result = asyncio.run(detailed_analysis(db.paper(paper_id), Settings(max_chunks=1), FakeSource(),
                                           FakeLLM(), db, tmp_path, lambda message: None))
    assert result["grounded_facts"] == 0
    assert result["language"] == "en"
    assert "No facts" in result["results"]


def test_brief_rejects_numeric_reason_and_shortens_overlong_summary():
    data = {"summary": "Un resumen de un estudio técnico de inteligencia artificial.",
            "contribution": "Una contribución de investigación explícita.",
            "relevance_reason": "4", "relevance": 4, "tags": []}
    with pytest.raises(ValidationError):
        Brief.model_validate(data)
    data["relevance_reason"] = "Investiga aprendizaje de representaciones en IA."
    data["summary"] = "palabra " * 151
    result = Brief.model_validate(data)
    assert len(result.summary.split()) <= 150
    assert result._was_shortened


def test_report_never_populates_sections_without_evidence():
    report = build_report([{"section": "results", "claim": "El método logra el resultado reportado."}])
    assert "resultado reportado" in report["results"]
    assert "No se recuperaron" in report["method"]
    assert "No se recuperaron" in report["contribution"]


def test_settings_can_pause_when_ollama_is_offline(tmp_path):
    from fastapi.testclient import TestClient

    from radar.app import create_app

    app = create_app(tmp_path, start_engine=False)
    with TestClient(app, base_url="http://localhost") as client:
        config = client.get("/api/settings").json()
        config["pause_summaries"] = True
        response = client.put("/api/settings", content=json.dumps(config),
                              headers={"X-Radar-Request": "1", "Content-Type": "application/json"})
        assert response.status_code == 200
        assert response.json()["pause_summaries"] is True
