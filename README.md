# epub-convert

Reading-ready Markdown from EPUBs, as a CLI, Python function, or HTTP API.
No LLM, network service, or extracted book assets.

## Run

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and
[Pandoc](https://pandoc.org/) 3.12.1 (`brew install pandoc` on macOS;
`sudo apt install pandoc` only if the distribution provides version 3.12.1).

```sh
uv sync --locked
uv run epub-convert convert book.epub -o book.md
uv run epub-convert convert book.epub > book.md
cat book.epub | uv run epub-convert convert -
uv run epub-convert serve
```

The API defaults to `http://127.0.0.1:3000`; interactive upload docs are at `/docs`.
`serve --host 0.0.0.0 --port 3000` changes its bind. `HOST`, `PORT`, and
`PANDOC_BIN` are optional overrides. No authentication is built in.

```sh
curl --fail-with-body http://127.0.0.1:3000/convert \
  -F 'file=@book.epub' -o book.md
# Raw EPUB bodies work too.
curl --fail-with-body http://127.0.0.1:3000/convert \
  -H 'Content-Type: application/epub+zip' --data-binary @book.epub -o book.md
```

```python
from epub_convert import convert_epub

markdown = convert_epub(epub_bytes)
```

All three interfaces return the same Markdown. Conversion failures leave an
existing CLI output file untouched. CLI diagnostics go to stderr.

## The Markdown contract

- Book/spine reading order, headings, paragraphs, emphasis and Unicode survive.
- Each ordinary paragraph occupies one source line; real paragraph boundaries,
  lists, quotations, code indentation and footnotes remain structural.
- Links retain their formatted labels; destinations are removed.
- Images become alt text; assets are not extracted or bundled. There is no OCR.
- Tables remain pipe tables, including captions and merged-cell placement.
  Multi-paragraph/list cells are flattened with word boundaries intact; spanned
  continuation cells are empty because pipe tables cannot express merged cells.
- Code uses fences; presentation wrappers, raw HTML and script/style content are
  excluded. Subscript/superscript retain their text without HTML wrappers.

The engine reads the EPUB into Pandoc's document tree, applies the small bundled
`reading.lua` policy, and writes Markdown with wrapping disabled. It never turns
finished Markdown back into prose with regexes. There are no worker scripts or
intermediate HTML/Markdown files. See [the design and evidence](docs/conversion.md).

Pipeline identifier: `reading-markdown-v1` (`X-Conversion-Pipeline` response header).
The former v0.1 image remains available; this changes document serialization, so
historical whitespace is not the compatibility contract.

## API behavior and limits

`POST /convert` accepts exactly one multipart `file`, or a raw
`application/epub+zip` / `application/octet-stream` body. Success is UTF-8
`text/markdown` with an attachment filename and `Cache-Control: no-store`.
`GET /health` becomes ready after checking Pandoc; `/openapi.json` documents uploads.

- 64 MiB per EPUB; 65 MiB total request, enforced while streaming without relying
  on `Content-Length`.
- ZIP validation before conversion: EPUB mimetype/package document, at most
  10,000 entries and 256 MiB declared expanded size; duplicate/encrypted entries
  and oversized/entity-bearing container XML are rejected. No archive extraction.
- Pandoc is version-checked (3.12.1) and uses `--sandbox` and a 120-second timeout. API admission is capped at two
  conversions per process; excess requests receive `503`, `Retry-After: 5`.
- JSON failures use `{error,message}`: `400` malformed/empty upload, `413` size,
  `415` content type, `422` invalid/unreadable/empty book, `504` timeout.

## Check it

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python scripts/verify_books.py /private/books --evidence /private/evidence
```

The real-book audit checks source document text/order against parsed output and
requires library, CLI and API bytes to agree. It saves protected Markdown/hashes
outside the repository. It never needs the old scripts or historical artifacts.
The tests use self-authored EPUBs, including nested lists, code, tricky link
labels, Unicode, merged/multiline tables, invalid input and concurrent requests.

## Container image

```sh
docker build -t epub-convert:local .
python3 scripts/smoke_image.py epub-convert:local
docker run --rm --read-only --tmpfs /tmp:rw,nosuid,noexec,size=256m \
  --cap-drop=ALL --security-opt=no-new-privileges \
  -p 127.0.0.1:3000:3000 epub-convert:local
```

The image includes Pandoc and runs as UID/GID 10001. Its root filesystem can be
read-only; multipart upload buffering may use `/tmp`. Bind the host port to
loopback unless using your own authenticating gateway.

GitHub Actions runs tests and an actual container HTTP conversion before publishing
`ghcr.io/bioshazard/epub-convert` for amd64 and arm64. Main/PR builds test;
`vX.Y.Z` tags publish versioned images and `latest`, and must match the package
version. Base images and Actions are pinned by digest/commit. Build context is an
allowlist that excludes credentials and private book artifacts.
