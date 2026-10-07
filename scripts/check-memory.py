"""Prueba opt-in: tres runners aislados, mismo PDF, sin modificar la biblioteca.

Ejecutar con .venv/bin/python scripts/check-memory.py (varios minutos de CPU).
"""
import argparse
import asyncio
import json
import os
import re
import runpy
import signal
import socket
import sqlite3
import tempfile
import time
from pathlib import Path

import httpx

from radar import llm as llm_module
from radar.analysis import (
    NOTES_VERSION,
    extract_pdf,
    fragment_prompt,
    make_chunks,
    verify_evidence,
)
from radar.config import DATA_DIR, Settings
from radar.llm import ChunkNotes, Ollama

MODES = {
    "baseline": {},
    "no_prompt_cache": {"LLAMA_ARG_CACHE_RAM": "0"},
    "no_cache_no_checkpoints": {"LLAMA_ARG_CACHE_RAM": "0", "LLAMA_ARG_CTX_CHECKPOINTS": "0"},
}


def memory(pid):
    try:
        lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return {key: int(line.split()[1]) for line in lines
            for key in ("VmRSS", "RssAnon", "RssFile") if line.startswith(key + ":")}


def runner_pid(parent):
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            lines = (path / "status").read_text().splitlines()
            if (any(line == "Name:\tllama-server" for line in lines)
                    and any(line == f"PPid:\t{parent}" for line in lines)):
                return int(path.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return None


async def monitor(server, samples):
    while True:
        pid = runner_pid(server.pid)
        samples.append({"t": time.monotonic(), "runner_pid": pid,
                        "runner": memory(pid) if pid else None, "server": memory(server.pid)})
        await asyncio.sleep(0.5)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def run_mode(mode, overrides, chunks, paper, work, model, briefs=False):
    directory = work / mode
    directory.mkdir()
    host = f"http://127.0.0.1:{free_port()}"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("LLAMA_ARG_", "OLLAMA_"))}
    env.update({"HOME": str(directory), "OLLAMA_HOST": host.removeprefix("http://"),
                "OLLAMA_MODELS": "/usr/share/ollama/.ollama/models", "OLLAMA_NO_CLOUD": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1", **overrides})
    samples, results, exchanges, responses = [], [], [], []
    log_path = directory / "ollama.log"
    llm_module.HOST = host  # Solo este proceso de prueba; no modifica el servicio de la aplicación.
    llm = Ollama()
    server = None
    sampler = None
    real_client = httpx.AsyncClient

    async def capture(request):
        if request.url.path == "/api/chat":
            exchanges.append(json.loads(request.content))
            (directory / "requests.json").write_text(json.dumps(exchanges, ensure_ascii=False, indent=2))

    async def capture_response(response):
        if response.request.url.path == "/api/chat":
            await response.aread()
            responses.append(response.json())
            (directory / "responses.json").write_text(json.dumps(responses, ensure_ascii=False, indent=2))

    def client(**kwargs):
        return real_client(event_hooks={"request": [capture], "response": [capture_response]}, **kwargs)

    with log_path.open("w") as log, sqlite3.connect(directory / "results.sqlite3") as conn:
        conn.execute("CREATE TABLE fragments (id INTEGER PRIMARY KEY, status TEXT, result TEXT, metrics TEXT)")
        conn.execute("CREATE TABLE summaries (id INTEGER PRIMARY KEY, result TEXT)")
        try:
            server = await asyncio.create_subprocess_exec(
                "/usr/local/bin/ollama", "serve", env=env, cwd=directory,
                stdout=log, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            async with real_client(trust_env=False, timeout=2) as probe:
                for _ in range(60):
                    if server.returncode is not None:
                        raise RuntimeError(f"Ollama terminó: ver {log_path}")
                    try:
                        response = await probe.get(host + "/api/tags")
                        response.raise_for_status()
                        if not any(item["name"] == model for item in response.json().get("models", [])):
                            raise RuntimeError(f"{model} no está disponible; no se descargarán modelos.")
                        break
                    except httpx.HTTPError:
                        await asyncio.sleep(0.5)
                else:
                    raise TimeoutError("Ollama temporal no responde")
            httpx.AsyncClient = client
            sampler = asyncio.create_task(monitor(server, samples))
            if briefs:
                brief = await llm.brief(paper, Settings(model=model))
                conn.execute("INSERT INTO summaries VALUES (1,?)", (json.dumps(brief, ensure_ascii=False),))
                conn.commit()
                (directory / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
                print(mode, "brief", json.dumps(brief, ensure_ascii=False), flush=True)
                # Separar la medición de fragmentos del estado dejado por el resumen.
                await llm.unload(model)
            for index, chunk in enumerate(chunks, 1):
                conn.execute("INSERT INTO fragments(id,status) VALUES (?, 'running')", (index,))
                conn.commit()
                start = time.monotonic()
                start_sample = len(samples)
                count = len(exchanges)
                result, stats = await llm.generate(model, fragment_prompt(paper, chunk),
                                                   ChunkNotes, output_tokens=1500)
                raw_facts = len(result["facts"])
                result["facts"] = verify_evidence(result["facts"], chunk)
                pid = runner_pid(server.pid)
                end_memory = memory(pid) if pid else None
                peaks = [sample["runner"].get("VmRSS", 0) for sample in samples[start_sample:]
                         if sample["runner"]]
                metrics = {"fragment": index, "page": chunk["page"], "seconds": time.monotonic() - start,
                           "runner_pid": pid, "rss_end_kib": (end_memory or {}).get("VmRSS"),
                           "rss_peak_kib": max(peaks, default=0), "requests": len(exchanges) - count,
                           "raw_facts": raw_facts, "verified_facts": len(result["facts"]), **stats}
                conn.execute("UPDATE fragments SET status='done',result=?,metrics=? WHERE id=?",
                             (json.dumps(result, ensure_ascii=False), json.dumps(metrics), index))
                conn.commit()
                results.append(metrics)
                print(mode, json.dumps(metrics), flush=True)
            pid = runner_pid(server.pid)
            if pid:
                # El runner nos pertenece: smaps es legible sin elevar permisos.
                for name in ("smaps_rollup", "maps"):
                    try:
                        (directory / name).write_text(Path(f"/proc/{pid}/{name}").read_text())
                    except (FileNotFoundError, PermissionError):
                        pass
        finally:
            try:
                if server and server.returncode is None:
                    await llm.unload(model)
            finally:
                httpx.AsyncClient = real_client
                if sampler:
                    sampler.cancel()
                    await asyncio.gather(sampler, return_exceptions=True)
                if server and server.returncode is None:
                    os.killpg(server.pid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(server.wait(), 10)
                    except TimeoutError:
                        os.killpg(server.pid, signal.SIGKILL)
                        await server.wait()
                (directory / "samples.json").write_text(json.dumps(samples, indent=2))
                (directory / "metrics.json").write_text(json.dumps(results, indent=2))
    text = log_path.read_text()
    relevant = [line for line in text.splitlines() if any(term in line for term in (
        "cache state:", "prompt cache is", "checkpoints", "buffer size", "cache-ram"))]
    (directory / "cache-evidence.txt").write_text("\n".join(relevant))
    states = [float(value) for value in re.findall(r"cache state: \d+ prompts, ([\d.]+) MiB", text)]
    return {"mode": mode, "model": model, "overrides": overrides, "fragments": results,
            "max_prompt_cache_mib": max(states, default=0),
            "cache_configuration": [line for line in relevant if "prompt cache is" in line or
                                    "context checkpoints" in line]}


async def main(args):
    original_host = llm_module.HOST
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        response = await client.get("http://127.0.0.1:8765/api/status")
        response.raise_for_status()
        if response.json()["current_job"] or response.json()["scanning"]:
            raise RuntimeError("Detén las tareas de la aplicación antes de probar.")
        response = await client.get("http://127.0.0.1:11434/api/ps")
        response.raise_for_status()
        if response.json().get("models"):
            raise RuntimeError("Ollama principal tiene un modelo cargado; no se interferirá con él.")
    with sqlite3.connect(f"file:{DATA_DIR / 'radar.sqlite3'}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT title,abstract FROM papers WHERE id=?", (args.paper_id,)).fetchone()
    if not row:
        raise ValueError("Paper inexistente")
    path = DATA_DIR / "documents" / f"{args.paper_id}.pdf"
    extracted = await extract_pdf(path)
    chunks = make_chunks(extracted["pages"])[:args.chunks]
    if len(chunks) < args.chunks:
        raise ValueError("No hay suficientes fragmentos")
    work = Path(tempfile.mkdtemp(prefix="radar-memory-", dir="/tmp/opencode"))
    print("Artefactos:", work, flush=True)
    (work / "input.json").write_text(json.dumps({"paper_id": args.paper_id, "title": row[0], "model": args.model,
                                                "notes_version": NOTES_VERSION,
                                                "chunks": chunks}, ensure_ascii=False, indent=2))
    reports = []
    for mode in args.modes:
        reports.append(await run_mode(mode, MODES[mode], chunks, {"title": row[0], "abstract": row[1]},
                                      work, args.model, args.briefs))
        (work / "comparison.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
    print("Comparación completa:", work / "comparison.json", flush=True)
    if args.validate:
        llm_module.HOST = original_host
        validation = runpy.run_path(str(Path(__file__).with_name("check-model.py")))
        await validation["main"](argparse.Namespace(model=args.model, notes=str(work / args.modes[-1])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-id", type=int, default=2)
    parser.add_argument("--chunks", type=int, choices=range(2, 41), default=6)
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--modes", nargs="+", choices=list(MODES), default=list(MODES))
    parser.add_argument("--briefs", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Después, ejecutar casos y recuperar el informe en el endpoint original")
    asyncio.run(main(parser.parse_args()))
