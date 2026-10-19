import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from .converter import MAX_UPLOAD_BYTES, PIPELINE, ConversionError, check_dependencies, convert_epub

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


async def bounded_body(request: Request) -> bytes:
    try:
        declared_size = int(request.headers.get("content-length", "0"))
    except ValueError as exc:
        raise ConversionError(400, "invalid_content_length", "Invalid Content-Length.") from exc
    if declared_size > MAX_REQUEST_BYTES:
        raise ConversionError(413, "file_too_large", "Request exceeds upload limit.")
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_REQUEST_BYTES:
            raise ConversionError(413, "file_too_large", "Request exceeds upload limit.")
        chunks.extend(chunk)
    return bytes(chunks)


def download_name(filename: str) -> str:
    stem = filename.replace("\\", "/").split("/")[-1]
    stem = re.sub(r"\.epub$", "", stem, flags=re.IGNORECASE)
    return (re.sub(r"[^a-zA-Z0-9._ -]", "_", stem)[:120] or "book") + ".md"


def create_app(max_concurrent: int = 2) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        check_dependencies()
        yield

    app = FastAPI(title="EPUB to Markdown", version="1.0.0", lifespan=lifespan)
    active = 0

    @app.exception_handler(ConversionError)
    async def conversion_error(request, exc):
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
            media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if media_type not in {
                "multipart/form-data",
                "application/epub+zip",
                "application/octet-stream",
            }:
                raise ConversionError(
                    415,
                    "unsupported_media_type",
                    "Use multipart/form-data with a 'file' field, or application/epub+zip.",
                )
            body = await bounded_body(request)
            filename = "book.epub"
            if media_type == "multipart/form-data":

                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                parsed = Request(request.scope, receive=receive)
                try:
                    async with parsed.form(max_files=1, max_fields=1) as form:
                        files = form.getlist("file")
                        if len(files) != 1 or not isinstance(files[0], UploadFile):
                            raise ConversionError(
                                400, "missing_file", "Send exactly one EPUB in the 'file' field."
                            )
                        filename = files[0].filename or filename
                        if files[0].size and files[0].size > MAX_UPLOAD_BYTES:
                            raise ConversionError(413, "file_too_large", "EPUB exceeds 64 MiB.")
                        data = await files[0].read()
                except (HTTPException, ValueError) as exc:
                    raise ConversionError(
                        400,
                        "invalid_multipart",
                        "Malformed multipart upload; send exactly one 'file'.",
                    ) from exc
            else:
                data = body
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
        except ConversionError:
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
