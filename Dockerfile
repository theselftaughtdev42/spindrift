# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
COPY . .

# Give every static file a second name carrying a digest of its contents, and write the
# manifest the app reads to find them: nginx serves these off disk, so a name fixed to its
# bytes is what lets it cache them hard. Ahead of the sync and on the base image's own
# interpreter, because the script is stdlib only — `uv run` would re-resolve the environment
# and pull the dev group back in, putting pytest in the release image.
RUN python3 spindrift/static_manifest.py

RUN uv sync --frozen --no-install-project --no-dev

# The release this image was cut from, handed in by the publish workflow. It defaults to
# nothing so a plain `docker build` still works, and the app then falls back to pyproject.
ARG SPINDRIFT_VERSION=
# The venv on PATH makes `python` the project interpreter; the database lives on a volume.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPINDRIFT_DB=/data/catalogue.sqlite3 \
    SPINDRIFT_VERSION=${SPINDRIFT_VERSION}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

CMD ["gunicorn", "spindrift.wsgi:app", "--bind", "0.0.0.0:8000"]
