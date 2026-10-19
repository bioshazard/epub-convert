"""One conversion contract: EPUB bytes in, reading Markdown out."""

import os
import re
import shutil
import subprocess
import zipfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

PIPELINE = "reading-markdown-v1"
PANDOC_VERSION = (3, 12, 1)
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
CONVERSION_TIMEOUT_SECONDS = 120
FILTER = Path(__file__).with_name("reading.lua")


class ConversionError(Exception):
    """An expected conversion failure, independent of HTTP or command-line exits."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=4)
def _checked_engine(executable: str) -> str:
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, timeout=5)
        match = re.match(rb"pandoc (\d+)\.(\d+)\.(\d+)", result.stdout)
        if result.returncode or not match or tuple(map(int, match.groups())) != PANDOC_VERSION:
            raise ConversionError(
                "engine_unavailable", "Pandoc 3.12.1 is required for validated output."
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError("engine_unavailable", "Pandoc could not start.") from exc
    return executable


def pandoc_bin() -> str:
    executable = shutil.which(os.environ.get("PANDOC_BIN", "pandoc"))
    if not executable:
        raise ConversionError("engine_unavailable", "Pandoc is missing. Install Pandoc 3.12.1.")
    return _checked_engine(executable)


def check_dependencies() -> None:
    pandoc_bin()


def _validate_epub(data: bytes) -> None:
    if not data:
        raise ConversionError("empty_file", "Upload a nonempty EPUB.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ConversionError("file_too_large", "EPUB exceeds 64 MiB.")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = archive.namelist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 256 * 1024 * 1024:
                raise ValueError("Archive limits exceeded")
            if len(names) != len(set(names)) or any(e.flag_bits & 1 for e in entries):
                raise ValueError("Duplicate or encrypted members")
            if archive.getinfo("mimetype").file_size > 64:
                raise ValueError("Invalid mimetype")
            if archive.read("mimetype").strip() != b"application/epub+zip":
                raise ValueError("Invalid mimetype")
            if archive.getinfo("META-INF/container.xml").file_size > 1024 * 1024:
                raise ValueError("Oversized container metadata")
            metadata = archive.read("META-INF/container.xml")
            if b"<!DOCTYPE" in metadata.upper() or b"<!ENTITY" in metadata.upper():
                raise ValueError("XML declarations are unsupported")
            container = ElementTree.fromstring(metadata)
            roots = container.findall(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            if not roots or roots[0].get("full-path") not in names:
                raise ValueError("Missing package document")
    except (
        zipfile.BadZipFile,
        KeyError,
        ValueError,
        ElementTree.ParseError,
        RuntimeError,
        NotImplementedError,
        OSError,
    ) as exc:
        raise ConversionError("invalid_epub", "File is not a supported, valid EPUB.") from exc


def convert_epub(data: bytes) -> str:
    """Convert in EPUB reading order, without extracting files or fetching resources.

    Pandoc owns parsing and Markdown serialization. The bundled document filter
    owns reading policy; neither transport rewrites the result.
    """
    _validate_epub(data)
    try:
        result = subprocess.run(
            [
                pandoc_bin(),
                "--sandbox",
                "--from=epub",
                "--to=gfm-raw_html-autolink_bare_uris",
                "--wrap=none",
                "--lua-filter=" + str(FILTER),
            ],
            input=data,
            capture_output=True,
            timeout=CONVERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("conversion_timeout", "Conversion exceeded its time limit.") from exc
    except OSError as exc:
        raise ConversionError("engine_unavailable", "Pandoc could not start.") from exc
    if result.returncode:
        raise ConversionError("unreadable_epub", "Pandoc could not read this EPUB.")
    markdown = result.stdout.decode("utf-8")
    if not markdown.strip():
        raise ConversionError("empty_book", "No readable content was found in this EPUB.")
    return markdown
