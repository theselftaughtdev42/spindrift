# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
COPY . .

RUN uv sync --frozen --no-install-project --no-dev

# The venv on PATH makes `python` the project interpreter. The database lives on a volume
# mounted at /data, overriding main.py's beside-source default.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPINDRIFT_DB=/data/catalogue.sqlite3

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

CMD ["python", "main.py"]
