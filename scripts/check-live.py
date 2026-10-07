"""Prueba real opt-in: un abstract y un fragmento de PDF, sin tocar la biblioteca principal."""
import asyncio
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import httpx

from radar.analysis import detailed_analysis
from radar.config import Settings
from radar.db import Database
from radar.llm import Ollama
from radar.sources import ArxivSource, bounded_get, parse_feed


async def main():
    llm=Ollama()
    print("Modelos locales:", await llm.models(), flush=True)
    async with httpx.AsyncClient(timeout=60,trust_env=False) as client:
        body=await bounded_get(client,"https://export.arxiv.org/api/query",params={
            "search_query":"cat:cs.AI","sortBy":"lastUpdatedDate","sortOrder":"descending","max_results":1})
    paper=parse_feed(body)[0][0]
    settings=Settings(max_chunks=1,schedule_enabled=False)
    work=Path(tempfile.mkdtemp(prefix="radar-live-",dir="/tmp/opencode"))
    db=Database(work/"radar.sqlite3")
    paper_id=db.add_papers([paper])[0]
    stored=db.paper(paper_id)
    print("Paper real:",paper.title,flush=True)
    brief=await llm.brief(stored,settings)
    print("Resumen:",json.dumps(brief,ensure_ascii=False),flush=True)
    analysis=await detailed_analysis(stored,settings,ArxivSource(),llm,db,work,
                                     lambda message:print(message,flush=True))
    result={"paper":asdict(paper),"brief":brief,"analysis":analysis}
    (work/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print("Resultado real (análisis parcial de prueba):",work/"result.json",flush=True)
    print(json.dumps(analysis,ensure_ascii=False),flush=True)
    await llm.unload(settings.model)


if __name__=="__main__":
    asyncio.run(main())
