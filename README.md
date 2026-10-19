# epub-convert

Python API and CLI for the EPUB → HTML → Markdown → cleaned Markdown workflow in
`../iooh-epub/convert-epub-md`. Conversion runs locally, without an LLM or a hosted service.

## Run

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Pandoc with `--sandbox`
support. Tested with Python 3.12.13 and Pandoc 3.1.3.

```sh
sudo apt install pandoc  # Linux; macOS: brew install pandoc
uv sync --locked
uv run epub-convert serve
```

The API listens on `http://127.0.0.1:3000`. Interactive upload docs: `/docs`.
Use `--host 0.0.0.0 --port 3000` to listen on other interfaces, or set `HOST` and `PORT`.
There is no authentication; the default bind is local. `PANDOC_BIN` can select a specific
Pandoc installation. `uv.lock` pins Python dependencies; install the same Pandoc version
when byte-for-byte output across deployments matters.

## Convert

```sh
curl --fail-with-body http://127.0.0.1:3000/convert \
  -F 'file=@../iooh-epub/convert-epub-md/artifacts/To Sell Is Human.epub' \
  -o book.md

# Raw EPUB bodies work too.
curl --fail-with-body http://127.0.0.1:3000/convert \
  -H 'Content-Type: application/epub+zip' --data-binary @book.epub -o book.md

# The identical pipeline is available without a running server.
uv run epub-convert convert book.epub -o book.md
```

`POST /convert` returns UTF-8 `text/markdown` with an attachment filename and
`X-Conversion-Pipeline: iooh-epub-v1`. Multipart uploads take exactly one `file`.
Raw `application/octet-stream` is also accepted. `GET /health` reports readiness
after startup has checked dependencies. `/openapi.json` describes the API.

## Baked-in conversion

The three source steps run in the original order:

1. `src/00-pandoc.sh`: Pandoc reads the EPUB in its reading order and writes HTML.
   The API uses local Pandoc with `--sandbox`, rather than the source script's
   unpinned `pandoc/latex` Docker image. Its default HTML wrapping is preserved.
2. `src/01-main.py`: `markdownify==0.14.1` renders that HTML with
   `heading_style="ATX"`, including pipe tables. All five Python converter
   dependency versions match the source `uv.lock`.
3. `src/02-double-newline.py`: the same three regular expressions, in the same
   order, join wrapped lines while preserving table rows, turn a leading space
   into a newline, and replace Markdown hyperlinks with their visible text.

The cleanup is preserved literally, including whitespace. It is intended for the
source's reading/audiobook workflow: link destinations are discarded, list/code
formatting can flatten, and complex nested links inherit the source regex's
limitations. Image syntax and relative references follow the original behavior;
the response does not bundle image assets. No additional typography rewriting,
paragraph heuristics, trimming, or summarization is applied.

## Limits and failures

- 64 MiB per EPUB; 65 MiB total request including multipart overhead, enforced
  while reading even without `Content-Length`.
- ZIP validation: EPUB mimetype and package document, at most 10,000 entries and
  256 MiB declared expanded size; encrypted ZIP entries are rejected. Archives
  are never extracted by application code.
- Two conversions at a time per server process. Extra requests get `503` with
  `Retry-After: 5`. Pandoc runs with sandboxing; each subprocess has a 120-second
  timeout. Each request has its own temporary directory, removed on success or failure.
- `400`: empty/malformed upload; `413`: size limit; `415`: content type;
  `422`: invalid, unreadable, empty, or unsupported EPUB; `504`: conversion timeout.
  Conversion errors return JSON with `error` and `message`.

## Verify

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python scripts/verify_source.py
# Optional alternate source conversion directory:
uv run python scripts/verify_source.py /path/to/iooh-epub/convert-epub-md
```

The verification command runs all source EPUBs through the API, independently
runs the original `01-main.py` and `02-double-newline.py` after Pandoc, and
requires byte-for-byte agreement. It also checks the three stored HTML artifacts
against the original scripts to isolate the Python stages from Pandoc versions.
It saves converted books and a SHA-256/size/timing report in
`artifacts/verification/` (gitignored). Source books and scripts are never modified.

All four source EPUBs match fresh execution of the original scripts byte for byte.
Three also match the historical clean Markdown exactly. The saved HTML for
`age-of-invisible-machines-ed2.epub` has empty endnote sections and footnote entries;
fresh Pandoc includes those notes, producing 633,493 bytes versus the historical
612,935 bytes. Running either implementation against the saved HTML reproduces
the historical output. The scripts do not record a note-removal step, so the API
preserves the notes Pandoc produces. Historical-file agreement is reported
separately from agreement with the executable source pipeline.

## Container image

GitHub Actions tests the image and a real HTTP conversion before publishing
`ghcr.io/bioshazard/epub-convert` for `linux/amd64` and `linux/arm64`.
Release tags publish `v0.1.0`, `0.1.0`, SHA and `latest` tags (with the
version taken from each tag). Main pushes and pull requests test without
publishing. Base images and Actions are pinned by digest/commit.

```sh
docker build -t epub-convert:local .
python3 scripts/smoke_image.py epub-convert:local
docker run --rm --read-only --tmpfs /tmp:rw,nosuid,noexec,size=256m \
  --cap-drop=ALL --security-opt=no-new-privileges \
  -p 127.0.0.1:3000:3000 ghcr.io/bioshazard/epub-convert:v0.1.0
```

The runtime includes Pandoc, runs as UID/GID 10001, and uses temporary request
storage only. Bind the host port to loopback unless placing it behind your own
authenticating gateway. Private GHCR packages require `docker login ghcr.io`.
The Docker build context allowlist excludes credentials and book artifacts.
