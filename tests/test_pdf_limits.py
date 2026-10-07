import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from radar.colibri import ColibriSource
from radar.config import Settings
from radar.sources import ArxivSource, bounded_get


def test_pdf_limit_defaults_to_100_mb_and_uses_current_saved_preference(db):
    assert Settings().max_pdf_mb == 100
    source = ArxivSource(db=db)
    assert source.pdf_limit == 100_000_000
    settings = db.settings().model_dump()
    settings["max_pdf_mb"] = 50
    db.set_meta("settings", settings)
    assert source.pdf_limit == 50_000_000
    assert ColibriSource(db=db).pdf_limit == 50_000_000
    for invalid in (0, 251):
        with pytest.raises(ValidationError):
            Settings(max_pdf_mb=invalid)


def test_head_reads_only_headers_and_records_redirects_without_reading_body(db):
    class UnreadableBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("HEAD must not read a response body")
            yield b""  # pragma: no cover

    async def run():
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.host == "arxiv.org":
                return httpx.Response(302, headers={"Location": "https://www.arxiv.org/pdf/test"})
            return httpx.Response(200, headers={"Content-Length": "44748090", "Content-Type": "application/pdf"},
                                  stream=UnreadableBody())

        source = ArxivSource(db=db)
        source.pace = AsyncMock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            headers = await source.head(client, "https://arxiv.org/pdf/test")
        assert headers["content-length"] == "44748090"
        assert [request.method for request in requests] == ["HEAD", "HEAD"]
        assert db.rows("SELECT purpose,status FROM source_requests") == [
            {"purpose": "pdf-size", "status": 302}, {"purpose": "pdf-size", "status": 200}]
    asyncio.run(run())


def test_head_respects_cooldown_after_429_without_retrying(db):
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "3600"})

        source = ArxivSource(db=db)
        source.pace = AsyncMock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await source.head(client, "https://arxiv.org/pdf/test")
            with pytest.raises(ValueError, match="pausa"):
                await source.head(client, "https://arxiv.org/pdf/test")
        assert len(calls) == 1
        assert db.rows("SELECT purpose,status FROM source_requests") == [{"purpose": "pdf-size", "status": 429}]
    asyncio.run(run())


def test_arxiv_document_uses_pdf_budget_not_metadata_budget(db, sample):
    async def run():
        source = ArxivSource(db=db)
        source.get = AsyncMock(return_value=b"%PDF-test")
        assert await source.document(vars(sample)) == b"%PDF-test"
        assert source.get.await_args.kwargs["limit"] == 100_000_000
        assert source.get.await_args.kwargs["purpose"] == "pdf"
    asyncio.run(run())


def test_colibri_rejects_metadata_over_configured_limit_before_downloading(db):
    async def run():
        settings = db.settings().model_dump()
        settings["max_pdf_mb"] = 50
        db.set_meta("settings", settings)
        source = ColibriSource(db=db)
        source.resolve_pdf = AsyncMock(return_value=("https://www.colibri.udelar.edu.uy/pdf", 60_000_000))
        source.get = AsyncMock()
        with pytest.raises(ValueError, match="60.00 MB.*50 MB"):
            await source.document({})
        source.get.assert_not_awaited()
    asyncio.run(run())


def test_size_errors_include_declared_size_and_limit_without_reading_body():
    async def run():
        def handler(request):
            return httpx.Response(200, headers={"Content-Length": "44748090"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="44.75 MB.*20 MB"):
                await bounded_get(client, "https://arxiv.org/pdf/test", limit=20_000_000)
    asyncio.run(run())
