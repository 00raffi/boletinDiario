"""Prueba opt-in del conector público. No usa Ollama ni modifica producción."""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from radar.analysis import extract_pdf
from radar.config import Settings
from radar.db import Database
from radar.engine import Engine


async def check(work, days, pdf):
    db = Database(work / "validation.sqlite3")
    settings = Settings(colibri_enabled=True, arxiv_enabled=False, initial_days=days,
                        desktop_notifications=False, schedule_enabled=False)
    db.set_meta("settings", settings.model_dump())
    engine = Engine(db, work)
    await engine.scan("validation", ["colibri"])
    run = db.rows("SELECT * FROM runs")[0]
    if run["status"] != "completed":
        raise ValueError(run["error"])
    papers = db.rows("SELECT id,title,document_type,updated,published FROM papers ORDER BY updated DESC")
    print("Descubrimiento:", json.dumps({"run": run, "papers": papers}, ensure_ascii=False), flush=True)
    assert run["selected"] <= 8
    result = {"run": run, "papers": papers}
    if pdf:
        candidates = db.rows("SELECT id FROM papers WHERE has_pdf=1 AND trim(abstract)!='' ORDER BY updated DESC LIMIT 1")
        if not candidates:
            raise ValueError("No hay candidato PDF en el periodo de validación.")
        paper = db.paper(candidates[0]["id"])
        body = await engine.sources["colibri"].document(paper)
        path = work / "sample.pdf"
        path.write_bytes(body)
        extracted = await extract_pdf(path)
        (work / "extraction.json").write_text(json.dumps(extracted, ensure_ascii=False, indent=2))
        result["pdf"] = {"title": paper["title"], "url": paper["pdf_url"], "bytes": len(body),
                         "total_pages": extracted["total_pages"], "pages_extracted": len(extracted["pages"]),
                         "extraction_partial": extracted["extraction_partial"]}
        print("PDF público y extracción:", json.dumps(result["pdf"], ensure_ascii=False), flush=True)
    result["requests"] = db.rows("SELECT source,started_at,purpose,status,retry_after FROM source_requests")
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("Solicitudes externas:", len(result["requests"]), "· Artefactos:", work, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, choices=range(1, 31), default=7)
    parser.add_argument("--pdf", action="store_true", help="Descargar y extraer un único PDF público (hasta 100 MB por defecto).")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="colibri-check-", dir="/tmp/opencode"))
    print("Artefactos:", work, flush=True)
    asyncio.run(check(work, args.days, args.pdf))


if __name__ == "__main__":
    main()
