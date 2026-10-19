import asyncio
import re
import subprocess
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import gettempdir

import httpx
import pytest
from fastapi.testclient import TestClient

from epub_convert.api import MAX_REQUEST_BYTES, create_app
from epub_convert.converter import PIPELINE


@pytest.fixture(scope="module")
def epub(tmp_path_factory):
    directory = tmp_path_factory.mktemp("epub-fixture")
    md, book = directory / "book.md", directory / "book.epub"
    md.write_text(
        """# A Sample Book

## First Chapter

This paragraph has a deliberately wrapped
line and **bold text**, *emphasis*, and a [readable link](https://example.com).

| Name | Value |
| ---- | ----- |
| Alpha | One |
| Beta | Two |

## Second Chapter

Unicode survives: café — naïve 日本語.
""",
        encoding="utf-8",
    )
    subprocess.run(["pandoc", str(md), "--metadata=title:Sample Book", "-o", str(book)], check=True)
    return book.read_bytes()


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def raw(client, data):
    return client.post("/convert", content=data, headers={"Content-Type": "application/epub+zip"})


def temp_dirs():
    return set(Path(gettempdir()).glob("epub-convert-*"))


def test_conversion_structure_and_cleanup(client, epub):
    response = client.post("/convert", files={"file": ("Sample Book.epub", epub)})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="Sample Book.md"'
    assert response.headers["x-conversion-pipeline"] == PIPELINE
    md = response.text
    assert "# A Sample Book" in md
    assert "## First Chapter" in md
    assert "wrapped line and **bold text**, *emphasis*, and a readable link" in md
    assert "](https://example.com)" not in md
    assert re.search(r"^\|\s*Alpha\s*\|\s*One\s*\|$", md, re.M)
    assert re.search(r"^\|\s*Beta\s*\|\s*Two\s*\|$", md, re.M)
    assert "café — naïve 日本語" in md


def test_raw_and_multipart_identical(client, epub):
    response = raw(client, epub)
    assert response.status_code == 200
    assert response.content == client.post("/convert", files={"file": ("book.epub", epub)}).content


def test_concurrent_books_are_isolated_and_temp_files_removed(client, epub):
    before = temp_dirs()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: raw(client, epub), range(2)))
    assert [response.status_code for response in results] == [200, 200]
    assert results[0].content == results[1].content
    assert temp_dirs() == before


def test_invalid_and_empty_uploads(client):
    before = temp_dirs()
    assert raw(client, b"garbage").status_code == 422
    assert raw(client, b"").status_code == 400
    assert temp_dirs() == before
    # A valid ZIP is not sufficient to be a valid EPUB.
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a book")
    assert raw(client, buffer.getvalue()).status_code == 422


def test_reject_malformed_and_duplicate_uploads(client, epub):
    assert client.post("/convert", files={"other": ("book.epub", epub)}).status_code == 400
    assert (
        client.post(
            "/convert", files=[("file", ("one.epub", epub)), ("file", ("two.epub", epub))]
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/convert", content=b"garbage", headers={"Content-Type": "multipart/form-data"}
        ).status_code
        == 400
    )


def test_request_size_limit(client):
    response = client.post(
        "/convert",
        content=b"small",
        headers={
            "Content-Type": "application/epub+zip",
            "Content-Length": str(MAX_REQUEST_BYTES + 1),
        },
    )
    assert response.status_code == 413


def test_stream_size_limit_without_content_length(monkeypatch):
    import epub_convert.api as api

    monkeypatch.setattr(api, "MAX_REQUEST_BYTES", 10)

    async def send():
        async def chunks():
            yield b"123456"
            yield b"123456"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            return await client.post(
                "/convert", content=chunks(), headers={"Content-Type": "application/epub+zip"}
            )

    assert asyncio.run(send()).status_code == 413


def test_errors_health_and_docs(client):
    assert client.post("/convert", json={}).status_code == 415
    assert client.get("/convert").status_code == 405
    assert client.get("/unknown").status_code == 404
    assert client.get("/health").json() == {"status": "ok", "pipeline": PIPELINE}
    assert client.get("/docs").status_code == 200
    assert (
        "multipart/form-data"
        in client.get("/openapi.json").json()["paths"]["/convert"]["post"]["requestBody"]["content"]
    )


def test_capacity_and_recovery(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def fake_convert(data):
        started.set()
        assert release.wait(5)
        return "# book"

    monkeypatch.setattr("epub_convert.api.convert_epub", fake_convert)
    with TestClient(create_app(max_concurrent=1)) as client, ThreadPoolExecutor() as executor:
        first = executor.submit(raw, client, b"book")
        try:
            assert started.wait(5)
            second = raw(client, b"book")
            assert second.status_code == 503
            assert second.headers["retry-after"] == "5"
        finally:
            release.set()
        assert first.result().status_code == 200
        assert raw(client, b"next").status_code == 200
