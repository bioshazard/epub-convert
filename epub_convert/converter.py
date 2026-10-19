import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

PIPELINE = "iooh-epub-v1"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
STAGE_TIMEOUT_SECONDS = 120
WORKER = Path(__file__).with_name("worker.py")


class ConversionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def pandoc_bin() -> str:
    return os.environ.get("PANDOC_BIN", "pandoc")


def check_dependencies() -> None:
    if not shutil.which(pandoc_bin()):
        raise RuntimeError("Pandoc is missing. Install it with: sudo apt install pandoc")
    for package, expected in {"markdownify": "0.14.1", "beautifulsoup4": "4.13.3"}.items():
        if version(package) != expected:
            raise RuntimeError(f"Expected {package}=={expected}. Run uv sync --locked.")


def run_command(
    cmd: list[str], timeout: float = STAGE_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            504, "conversion_timeout", "Conversion exceeded its time limit."
        ) from exc


def convert_epub(data: bytes) -> str:
    if not data:
        raise ConversionError(400, "empty_file", "Upload a nonempty EPUB.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ConversionError(413, "file_too_large", "EPUB exceeds 64 MiB.")
    with TemporaryDirectory(prefix="epub-convert-") as directory:
        epub, html, md = (Path(directory) / name for name in ("input.epub", "book.html", "book.md"))
        epub.write_bytes(data)
        validation = run_command([sys.executable, str(WORKER), "validate", str(epub)])
        if validation.returncode:
            raise ConversionError(
                422,
                "invalid_epub",
                "File is not a supported, valid EPUB (archive limit: 256 MiB expanded / 10,000 entries).",
            )
        # Default HTML wrapping is intentional: it is part of the original workflow.
        result = run_command(
            [
                pandoc_bin(),
                "--sandbox",
                "--from=epub",
                "--to=html",
                str(epub),
                "--output",
                str(html),
            ]
        )
        if result.returncode:
            raise ConversionError(
                422,
                "unreadable_epub",
                "Pandoc could not read this EPUB. It may be damaged or DRM protected.",
            )
        result = run_command([sys.executable, str(WORKER), "render", str(html), str(md)])
        if result.returncode:
            raise RuntimeError(f"Markdown conversion failed: {result.stderr[:1000]}")
        markdown = md.read_text(encoding="utf-8")
        if not markdown.strip():
            raise ConversionError(422, "empty_book", "No readable content was found in this EPUB.")
        return markdown
