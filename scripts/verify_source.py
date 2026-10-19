"""Verify the API against the original source scripts and all source EPUBs."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from fastapi.testclient import TestClient

from epub_convert.api import app
from epub_convert.converter import PIPELINE, WORKER, pandoc_bin

ROOT = Path(__file__).resolve().parents[1]
SAVED_CLEAN = {
    "The Practice of Adaptive Leadership.epub": "tpoal.clean.md",
    "To Sell Is Human.epub": "To Sell Is Human.epub.clean.md",
    "age-of-invisible-machines-ed2.epub": "age-of-invisible-machines-ed2.clean.md",
    "iooh-og.epub": "iooh-clean.md",
}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "iooh-epub/convert-epub-md"
    artifacts = source / "artifacts"
    output = ROOT / "artifacts/verification"
    output.mkdir(parents=True, exist_ok=True)
    books = sorted(artifacts.glob("*.epub"))
    if not books:
        raise RuntimeError(f"No EPUBs found in {artifacts}")
    report = []
    stored_html = []
    with TemporaryDirectory(prefix="epub-verify-") as work, TestClient(app) as client:
        work = Path(work)
        html, raw, clean = (work / name for name in ("book.html", "raw.md", "clean.md"))
        for book in books:
            started = monotonic()
            # Equivalent to source 00-pandoc.sh, using local Pandoc instead of Docker.
            run([pandoc_bin(), str(book), "-o", str(html)])
            run([sys.executable, str(source / "src/01-main.py"), str(html), str(raw)])
            run([sys.executable, str(source / "src/02-double-newline.py"), str(raw), str(clean)])
            response = client.post(
                "/convert", files={"file": (book.name, book.read_bytes(), "application/epub+zip")}
            )
            response.raise_for_status()
            result = response.content
            identical = result == clean.read_bytes()
            (output / book.with_suffix(".md").name).write_bytes(result)
            record = {
                "book": book.name,
                "inputBytes": book.stat().st_size,
                "outputBytes": len(result),
                "sha256": hashlib.sha256(result).hexdigest(),
                "matchesOriginalPipeline": identical,
                "elapsedMs": round((monotonic() - started) * 1000),
            }
            saved_name = SAVED_CLEAN.get(book.name)
            if saved_name and (artifacts / saved_name).exists():
                record["matchesHistoricalClean"] = result == (artifacts / saved_name).read_bytes()
            report.append(record)
            print(json.dumps(record), flush=True)
            if not identical:
                raise AssertionError(f"Output differs from original pipeline for {book.name}")
        for html in sorted(artifacts.glob("*.epub.html")):
            actual = work / "new.md"
            run([sys.executable, str(source / "src/01-main.py"), str(html), str(raw)])
            run([sys.executable, str(source / "src/02-double-newline.py"), str(raw), str(clean)])
            run([sys.executable, str(WORKER), "render", str(html), str(actual)])
            if actual.read_bytes() != clean.read_bytes():
                raise AssertionError(f"Stored HTML differs: {html.name}")
            stored_html.append(html.name)
            print(f"Stored HTML matches original scripts: {html.name}", flush=True)
    (output / "report.json").write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(UTC).isoformat(),
                "pandoc": run([pandoc_bin(), "--version"]).stdout.splitlines()[0],
                "pipeline": PIPELINE,
                "books": report,
                "storedHtmlMatches": stored_html,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
