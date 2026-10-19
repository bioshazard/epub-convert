# epub-convert

- One conversion contract: `convert_epub(bytes) -> str`; CLI and HTTP only adapt IO.
- Pandoc parses EPUB to a document tree, `reading.lua` applies reading policy,
  Pandoc writes unwrapped GFM. No HTML round-trip, post-render regexes or workers.
- Preserve book text/order, paragraph boundaries, headings, tables, lists, code,
  footnotes and Unicode. Links keep labels; images keep alt text. See docs/conversion.md.
- Table spans must retain column placement and cell word boundaries; test both.
- Requires Python 3.12+, Pandoc 3.12.1, `uv sync --locked`.
- CLI: `uv run epub-convert convert book.epub [-o book.md]`; '-' reads stdin.
- API: `uv run epub-convert serve`; defaults to unauthenticated `127.0.0.1:3000`.
- Checks: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`.
- Real-book verification: scripts/verify_books.py with explicit private paths.
  Compare document text/order and CLI/API/library equality, not legacy regex output.
- Never commit EPUBs, PDFs, book text, conversion artifacts, credentials or env files.
- Docker/CI use pinned Python/uv images, Pandoc and non-root UID/GID 10001.
- Release package/lock versions must match Git vX.Y.Z; don't move released tags.
