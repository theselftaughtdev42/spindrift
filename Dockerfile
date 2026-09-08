# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
COPY . .

RUN uv sync --frozen --no-install-project --no-dev

# The release this image was cut from, handed in by the publish workflow — the `v*` tag
# for a release, the moving name for a main build. It defaults to nothing so a plain
# `docker build` still works; the app then falls back to the version in pyproject.toml,
# which the source ships anyway. Baking it as an env var is what lets `GET /version`
# answer which build is running without the image having to carry any git history.
ARG SPINDRIFT_VERSION=
# The venv on PATH makes `python` the project interpreter. The database lives on a volume
# mounted at /data, overriding main.py's beside-source default.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPINDRIFT_DB=/data/catalogue.sqlite3 \
    SPINDRIFT_VERSION=${SPINDRIFT_VERSION}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

CMD ["gunicorn", "spindrift.wsgi:app", "--bind", "0.0.0.0:8000"]
