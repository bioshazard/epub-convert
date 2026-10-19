"""Check real books for retained text/order and identical library, CLI and API output.

The oracle is the EPUB document tree, not old conversion scripts. Private books
and generated Markdown stay outside the repository. Only counts/hashes are logged.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from epub_convert import convert_epub
from epub_convert.api import create_app
from epub_convert.converter import PIPELINE, pandoc_bin


def document_text(node):
    if isinstance(node, list):
        return "".join(map(document_text, node))
    if not isinstance(node, dict):
        return ""
    kind, content = node.get("t"), node.get("c")
    if kind == "Str":
        return content
    if kind in {"Space", "SoftBreak", "LineBreak"}:
        return " "
    if kind in {"Code", "CodeBlock", "Math"}:
        return " " + content[-1] + " "
    if kind in {"RawBlock", "RawInline"}:
        return ""  # Non-reading markup/scripts are intentionally excluded.
    if kind == "Figure":
        # Pandoc stores caption before body; visual reading order is body then caption.
        return document_text(content[2]) + document_text(content[1])
    text = document_text(content)
    return " " + text + " " if kind in {"Para", "Plain", "Header", "Note"} else text


def words(document):
    text = unicodedata.normalize("NFKC", document_text(document["blocks"]))
    return re.findall(r"\w+", text)


def parse(data, format):
    result = subprocess.run(
        [pandoc_bin(), "--sandbox", "--from=" + format, "--to=json"],
        input=data,
        capture_output=True,
        timeout=120,
        check=True,
    )
    return json.loads(result.stdout)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("books", type=Path, help="An EPUB or directory containing EPUBs")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.evidence.resolve().is_relative_to(root):
        parser.error("Keep private evidence outside this repository")
    books = (
        [args.books]
        if args.books.is_file()
        else sorted(p for p in args.books.iterdir() if p.suffix.lower() == ".epub")
    )
    if not books:
        parser.error("No EPUBs found")
    args.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = []
    with TestClient(create_app()) as client:
        for book in books:
            started = time.monotonic()
            data = book.read_bytes()
            markdown = convert_epub(data).encode()
            response = client.post(
                "/convert", content=data, headers={"Content-Type": "application/epub+zip"}
            )
            response.raise_for_status()
            cli = subprocess.run(
                [sys.executable, "-m", "epub_convert.cli", "convert", "-"],
                input=data,
                capture_output=True,
                timeout=130,
                check=True,
            )
            assert response.content == cli.stdout == markdown, "Transport output mismatch"
            source, output = words(parse(data, "epub")), words(parse(markdown, "gfm"))
            missing = sum((Counter(source) - Counter(output)).values())
            added = sum((Counter(output) - Counter(source)).values())
            sha = hashlib.sha256(data).hexdigest()
            record = {
                "book": book.name,
                "epubSha256": sha,
                "sourceWords": len(source),
                "outputWords": len(output),
                "missingWords": missing,
                "addedWords": added,
                "sameReadingOrder": source == output,
                "cliApiLibraryIdentical": True,
                "markdownSha256": hashlib.sha256(markdown).hexdigest(),
                "milliseconds": round((time.monotonic() - started) * 1000),
            }
            report.append(record)
            (args.evidence / (sha[:20] + ".md")).write_bytes(markdown)
            (args.evidence / "report.json").write_text(
                json.dumps({"pipeline": PIPELINE, "books": report}, indent=2) + "\n"
            )
            print(json.dumps(record), flush=True)
            assert not missing and not added and source == output, (
                "Book reading text/order changed; inspect protected evidence"
            )
            assert b"[TABLE]" not in markdown, "Unrendered table placeholder"


if __name__ == "__main__":
    main()
