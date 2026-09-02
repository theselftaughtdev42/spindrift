# Spindrift

A catalogue of games and the ways they can be played. Runs on your own machine, reachable
from any device on the home network.

## Run it

```
uv run main.py
```

Then open <http://localhost:8000>, or this machine's hostname on port 8000 from a phone or
tablet. macOS will ask to allow incoming connections the first time.

## Test it

```
uv run pytest
```

## Container

The image is published to `ghcr.io/theselftaughtdev42/spindrift:latest` on every merge to
`main` (also tagged `sha-<short>` for rollback). It's built for `linux/amd64`.

Run contract for the orchestration layer:

- **Port:** the app serves HTTP on `8000`. Publish it to loopback only —
  `127.0.0.1:8000:8000` — and terminate TLS at a reverse proxy in front.
- **Data:** the catalogue lives at `/data/catalogue.sqlite3` (set by `SPINDRIFT_DB`).
  Mount a named volume at `/data`; it's created and migrated on first boot.
- **Health:** `GET /health` returns `200 ok` when the app is up and the database is
  reachable. The image's `HEALTHCHECK` already polls it.

```
docker run -d --name spindrift \
  -p 127.0.0.1:8000:8000 \
  -v spindrift-data:/data \
  ghcr.io/theselftaughtdev42/spindrift:latest
```
