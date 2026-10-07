"""Comprobación de disponibilidad para ExecStartPost del servicio dedicado."""
import asyncio
import time

import httpx

from radar.llm import Ollama


async def main():
    llm = Ollama()
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            await llm.models()
            return
        except httpx.HTTPError:
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Ollama no está listo en {llm.host}")


if __name__ == "__main__":
    asyncio.run(main())
