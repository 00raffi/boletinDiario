"""Prueba real opt-in: idiomas y propuesta puntual de intereses, sin aplicar preferencias."""
import asyncio
import json
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from radar.analysis import fragment_prompt, validate_notes_language, verify_evidence
from radar.app import create_app
from radar.config import Settings
from radar.languages import text_language
from radar.llm import ChunkNotes, Ollama
from radar.sources import bounded_get, parse_feed, search_queries

TEXT = ("Me interesan el aprendizaje por refuerzo para robótica, la neurociencia computacional, "
        "la privacidad diferencial y la cosmología. No me interesan el trading ni el marketing.")
PAPERS = [
    {"title": "Controlled robot planning", "abstract": "We present a method for robot planning. "
     "We evaluate it on 40 synthetic tasks and report 72% accuracy compared with 68% for the baseline. "
     "Our results are preliminary and do not demonstrate performance on real-world robots."},
    {"title": "Planificación de robots en un entorno controlado", "abstract": "En este artículo presentamos un método "
     "para la planificación de robots. Lo evaluamos en 40 tareas sintéticas y reportamos una exactitud del 72%, "
     "frente al 68% de la línea base. Los resultados son preliminares y no demuestran rendimiento en robots reales."},
]


def record_requests(work):
    """Conservar también intentos rechazados, no solo resultados aceptados."""
    original = httpx.AsyncClient.post
    count = 0

    async def post(client, url, **kwargs):
        nonlocal count
        response = await original(client, url, **kwargs)
        if str(url).endswith("/api/chat"):
            count += 1
            (work / f"request-{count:02d}.json").write_text(json.dumps(kwargs.get("json"), ensure_ascii=False, indent=2))
            (work / f"response-{count:02d}.json").write_text(response.text)
        return response

    httpx.AsyncClient.post = post


async def languages(work):
    llm = Ollama()
    settings = Settings(categories=["cs.RO"], keywords=["robot planning", "planificación de robots"])
    outputs = []
    try:
        for paper in PAPERS:
            language = text_language(paper["abstract"])
            brief = await llm.brief(paper, settings)
            assert brief["language"] == language
            assert text_language(brief["summary"]) == language
            chunk = {"page": 1, "text": paper["abstract"]}
            notes, stats = await llm.generate(settings.model, fragment_prompt({**paper, "language": language}, chunk),
                                               ChunkNotes, output_tokens=1500,
                                               validator=lambda result, lang=language: validate_notes_language(result, lang))
            facts = verify_evidence(notes["facts"], chunk)
            assert facts
            assert all(text_language(fact["claim"]) in {language, None} for fact in facts)
            outputs.append({"paper": paper, "brief": brief, "notes": notes, "verified": facts, "stats": stats})
            print(language, json.dumps(outputs[-1], ensure_ascii=False), flush=True)
            await llm.unload(settings.model)
    finally:
        await llm.unload(settings.model)
        (work / "languages.json").write_text(json.dumps(outputs, ensure_ascii=False, indent=2))


def main():
    work = Path(tempfile.mkdtemp(prefix="reading-design-", dir="/tmp/opencode"))
    print("Artefactos:", work, flush=True)
    record_requests(work)
    with httpx.Client(trust_env=False, timeout=10) as client:
        response = client.get("http://127.0.0.1:8765/api/status")
        response.raise_for_status()
        assert not response.json()["current_job"] and not response.json().get("compiling_interests")
    app = create_app(work / "preview", start_engine=False)
    with TestClient(app, base_url="http://localhost") as client:
        before = client.get("/api/settings").json()
        headers = {"X-Radar-Request": "1"}
        response = client.post("/api/interests/propose", json={"text": TEXT}, headers=headers)
        assert response.status_code == 200, response.text
        proposal = response.json()
        assert client.get("/api/settings").json() == before
        cached = client.post("/api/interests/propose", json={"text": TEXT}, headers=headers)
        assert cached.json()["cached"]
        (work / "interests.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2))
        print("Propuesta NO aplicada:", json.dumps(proposal, ensure_ascii=False), flush=True)
    asyncio.run(languages(work))

    async def check_query():
        queries = search_queries(proposal["proposal"]["categories"], proposal["proposal"]["keywords"])
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
                body = await bounded_get(client, "https://export.arxiv.org/api/query", params={
                    "search_query": queries[0], "sortBy": "lastUpdatedDate", "sortOrder": "descending", "max_results": 1})
        except httpx.HTTPError as exc:
            (work / "arxiv-error.json").write_text(json.dumps({"query": queries[0], "error": str(exc),
                "status": exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None}, indent=2))
            raise
        papers, total = parse_feed(body)
        result = {"query": queries[0], "total": total, "first_title": papers[0].title if papers else None}
        (work / "arxiv-query.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print("Consulta arXiv verificada:", json.dumps(result, ensure_ascii=False), flush=True)

    asyncio.run(check_query())
    print("Prueba completada:", work, flush=True)


if __name__ == "__main__":
    main()
