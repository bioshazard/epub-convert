FROM ghcr.io/astral-sh/uv:0.9.18@sha256:5713fa8217f92b80223bc83aac7db36ec80a84437dbc0d04bbc659cae030d8c9 AS uv
FROM python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates
RUN python - <<'PYTHON'
import hashlib, os, urllib.request
checksums = {
    "amd64": "b4217ac7c54067c442f9d4cd38bcd0c184a43f3e7053431a12263a6f92a33ba2",
    "arm64": "38f44718c0cb15cb81fc31026bd68c33e8628ca5f7ab15ca86494a7f24f7b8e4",
}
arch = os.environ["TARGETARCH"]
url = f"https://github.com/jgm/pandoc/releases/download/3.12.1/pandoc-3.12.1-1-{arch}.deb"
with urllib.request.urlopen(url, timeout=120) as response:
    package = response.read()
assert hashlib.sha256(package).hexdigest() == checksums[arch], "Pandoc checksum mismatch"
with open("/tmp/pandoc.deb", "wb") as output:
    output.write(package)
PYTHON
RUN apt-get install -y --no-install-recommends /tmp/pandoc.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/pandoc.deb
WORKDIR /app

FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY epub_convert ./epub_convert
RUN uv sync --locked --no-dev --no-editable

FROM build AS test
COPY tests ./tests
COPY scripts ./scripts
RUN uv sync --locked --no-editable \
    && uv run --locked ruff check . \
    && uv run --locked ruff format --check .
CMD ["uv", "run", "--locked", "pytest", "-q"]

FROM base AS runtime
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --home-dir /nonexistent app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=3).close()"]
ENTRYPOINT ["epub-convert"]
CMD ["serve", "--host", "0.0.0.0", "--port", "3000"]
