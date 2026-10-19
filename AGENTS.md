# epub-convert

- Standalone EPUB → Pandoc sandboxed HTML → Markdownify → literal cleanup API/CLI.
- Source imported from bios-kubuntu: `/home/bios/Documents/bios-dev/incubator/epub-convert`.
- Install: Python 3.12+, Pandoc, `uv sync --locked`. Mac: `brew install pandoc`.
- Run: `uv run epub-convert serve`; default `127.0.0.1:3000`. No authentication.
- Check: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`.
- Preserve source pipeline behavior; output changes require deliberate parity review.
- `scripts/verify_source.py` optionally compares original source books/scripts, which
  live in the sibling `iooh-epub` project on bios-kubuntu and are not bundled here.
- Never commit EPUBs, PDFs, conversion artifacts, credentials or environment files.
- Dockerfile uses pinned Python/uv images, sandboxed Pandoc and non-root UID 10001.
- Image CI tests and smoke-converts before GHCR publication (amd64/arm64).
- Release version in pyproject.toml/uv.lock must match the Git vX.Y.Z tag.
