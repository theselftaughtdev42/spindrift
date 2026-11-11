# syntax=docker/dockerfile:1

# Build: resolve the environment and digest the static files. uv lives only in this stage.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS build

# Use the base image's interpreter, so the venv's links still resolve in the runtime stage.
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .

# Give every static file a second name carrying a digest of its contents, and write the
# manifest the app reads to find them. On the base image's own interpreter, because the
# script is stdlib only — `uv run` would re-resolve the environment and pull the dev group
# back in, putting pytest in the release image.
RUN python3 spindrift/static_manifest.py


# Runtime: the same Python, without uv.
FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72

WORKDIR /app
COPY --from=build /app /app

# Mount a volume here to keep the catalogue; without one it lives and dies with the container.
RUN mkdir /data

# The release comes from pyproject, which `make release` bumps on the commit it tags.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPINDRIFT_DB=/data/catalogue.sqlite3

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "spindrift.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
