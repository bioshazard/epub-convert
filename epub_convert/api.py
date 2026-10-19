import logging
import re
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from .converter import MAX_UPLOAD_BYTES, PIPELINE, ConversionError, check_dependencies, convert_epub

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


class UploadError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


async def read_upload(request: Request) -> tuple[str, bytes]:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in {
        "multipart/form-data",
        "application/epub+zip",
        "application/octet-stream",
    }:
        raise UploadError(
            415, "unsupported_media_type", "Send an EPUB body or one multipart 'file'."
        )
    try:
        declared_size = int(request.headers.get("content-length", "0"))
        if declared_size < 0:
            raise ValueError
    except ValueError as exc:
        raise UploadError(400, "invalid_content_length", "Invalid Content-Length.") from exc
    if declared_size > MAX_REQUEST_BYTES:
        raise UploadError(413, "file_too_large", "Request exceeds upload limit.")
    received = 0

    async def receive():
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > MAX_REQUEST_BYTES:
            raise UploadError(413, "file_too_large", "Request exceeds upload limit.")
        return message

    bounded = Request(request.scope, receive=receive)
    if media_type != "multipart/form-data":
        return "book.epub", await bounded.body()
    try:
        async with bounded.form(max_files=1, max_fields=0) as form:
            files = form.getlist("file")
            if len(files) != 1 or not isinstance(files[0], UploadFile):
                raise UploadError(400, "missing_file", "Send exactly one EPUB in the 'file' field.")
            data = await files[0].read(MAX_UPLOAD_BYTES + 1)
            return files[0].filename or "book.epub", data
    except (HTTPException, ValueError) as exc:
        raise UploadError(
            400, "invalid_multipart", "Send exactly one EPUB in the 'file' field."
        ) from exc


def download_name(filename: str) -> str:
    stem = filename.replace("\\", "/").split("/")[-1]
    stem = re.sub(r"\.epub$", "", stem, flags=re.IGNORECASE)
    return (re.sub(r"[^a-zA-Z0-9._ -]", "_", stem)[:120] or "book") + ".md"


def create_app(max_concurrent: int = 2) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        check_dependencies()
        yield

    app = FastAPI(title="EPUB to Markdown", version=version("epub-convert"), lifespan=lifespan)
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be positive")
    active = 0

    @app.exception_handler(ConversionError)
    async def conversion_error(request, exc):
        status = {
            "empty_file": 400,
            "file_too_large": 413,
            "invalid_epub": 422,
            "unreadable_epub": 422,
            "empty_book": 422,
            "conversion_timeout": 504,
            "engine_unavailable": 503,
        }[exc.code]
        return JSONResponse({"error": exc.code, "message": str(exc)}, status_code=status)

    @app.exception_handler(UploadError)
    async def upload_error(request, exc):
        return JSONResponse({"error": exc.code, "message": str(exc)}, status_code=exc.status)

    @app.get("/health")
    async def health():
        return {"status": "ok", "pipeline": PIPELINE}

    @app.post(
        "/convert",
        response_class=Response,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["file"],
                            "properties": {"file": {"type": "string", "format": "binary"}},
                        }
                    },
                    "application/epub+zip": {"schema": {"type": "string", "format": "binary"}},
                },
            },
            "responses": {
                "200": {
                    "description": "Cleaned Markdown download",
                    "content": {"text/markdown": {"schema": {"type": "string"}}},
                }
            },
        },
    )
    async def convert(request: Request):
        nonlocal active
        # This increment has no await: admission is atomic on the ASGI event loop.
        if active >= max_concurrent:
            return JSONResponse(
                {"error": "busy", "message": "All conversion slots are in use. Retry shortly."},
                status_code=503,
                headers={"Retry-After": "5"},
            )
        active += 1
        try:
            filename, data = await read_upload(request)
            markdown = await run_in_threadpool(convert_epub, data)
            return Response(
                markdown,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{download_name(filename)}"',
                    "Cache-Control": "no-store",
                    "X-Conversion-Pipeline": PIPELINE,
                },
            )
        except (ConversionError, UploadError):
            raise
        except Exception:
            logger.exception("Conversion failed")
            return JSONResponse(
                {"error": "conversion_failed", "message": "Conversion failed. See server logs."},
                status_code=500,
            )
        finally:
            active -= 1

    return app


app = create_app()
