"""Pinned markdownify conversion and the original iooh-epub cleanup, verbatim."""

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from markdownify import markdownify


def validate(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 256 * 1024 * 1024:
                raise ValueError("EPUB exceeds archive limits (10,000 entries / 256 MiB expanded)")
            if any(e.flag_bits & 1 for e in entries):
                raise ValueError("Encrypted EPUB archives are unsupported")
            if archive.read("mimetype").strip() != b"application/epub+zip":
                raise ValueError("Missing EPUB mimetype")
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            roots = container.findall(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            if not roots or roots[0].get("full-path") not in archive.namelist():
                raise ValueError("Missing EPUB package document")
    except (zipfile.BadZipFile, KeyError, ValueError, ElementTree.ParseError, RuntimeError) as exc:
        print(f"Invalid EPUB: {exc}", file=sys.stderr)
        sys.exit(2)


def clean(text):
    # Preserve the order and semantics of 02-double-newline.py.
    text = re.sub(r"\r?\n(?!\r?\n|\|)", " ", text)
    text = re.sub(r"(?m)^ ", "\n", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text


if __name__ == "__main__":
    mode, source = sys.argv[1:3]
    if mode == "validate":
        validate(source)
    elif mode == "render":
        html = Path(source).read_text(encoding="utf-8")
        markdown = markdownify(html, heading_style="ATX")
        Path(sys.argv[3]).write_text(clean(markdown), encoding="utf-8")
    else:
        raise ValueError("Unknown pipeline mode")
