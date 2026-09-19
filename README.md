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

## Work on it

`make check` runs the lot: ruff, ty, then the suite. `make format` fixes what ruff can fix
itself.

`make mutants` is mutation testing, by [mutmut](https://github.com/boxed/mutmut): it changes
the source in ways the suite ought to notice and reports what it slept through — coverage says
a line ran, this says an assertion depended on it. A cold sweep is about ninety seconds and
re-runs afterwards are seconds, since only mutants in changed code are checked again. Read the
survivors with `make mutants.results`, or `make mutants.browse` for the same thing in a
terminal UI. It isn't part of `make check`.

`make hooks` installs the git hooks, which run ruff and ty on each commit, refuse a commit
made on `main`, and run the suite on each push — once per clone. They're managed by
[prek](https://github.com/j178/prek), a drop-in replacement for pre-commit that reads the same
`.pre-commit-config.yaml`; it comes with the dev dependencies, so there's nothing else to
install. `make hooks.run` runs every hook over the whole tree rather than the staged files.

## Container

The image is published to `ghcr.io/theselftaughtdev42/spindrift` for `linux/amd64`, and
only when a release is cut — see below. Pushes to `main` don't publish; they build on the
pull request beforehand purely to prove the image still builds.

### Releases

A release is a `v*` git tag. Cut one with `make release VERSION=0.2.0`, which bumps
`pyproject.toml`, tags `v0.2.0`, and pushes it; the publish workflow then builds one image
and tags it three ways:

- `…/spindrift:0.2.0` — that exact release, forever.
- `…/spindrift:0.2` — the newest patch on the `0.2` line.
- `…/spindrift:latest` — the newest release, for staying current.

Pin a version for anything you want to be able to roll back to; rolling back is re-running
the pinned tag you want. Confirm which build is actually up with `GET /version` (see below).

Run contract for the orchestration layer:

- **Port:** the app serves HTTP on `8000`. Publish it to loopback only —
  `127.0.0.1:8000:8000` — and terminate TLS at a reverse proxy in front.
- **Static:** `/static/` may be served straight off disk by the proxy rather than passed
  through. The image build gives every static file a second name carrying a digest of its
  contents — `theme.css` is also served as `theme.<digest>.css` — and the app writes those
  digested names into the HTML. A name therefore always returns the same bytes, so cache
  them for as long as you like:

  ```
  location /static/ {
      alias /srv/spindrift/static/;
      expires 1y;
      add_header Cache-Control "public, immutable";
  }
  ```

  Copy `/app/spindrift/static/` out of the image on each deploy, **adding to what is
  already there rather than replacing it**. Leaving the previous release's digested files
  in place is what makes the deploy safe in any order: static files and a container can
  never change in the same instant, and a page served from either side of that gap asks
  for a name that is still on disk. Sweep the directory later if it ever grows enough to
  matter, keeping the last release or two.

  Documents are a different matter: the app marks every HTML response `no-cache`, and the
  proxy must pass that through — a cached page carries the digested names it was built
  against and would go on asking for them.
- **Data:** the catalogue lives at `/data/catalogue.sqlite3` (set by `SPINDRIFT_DB`).
  Mount a named volume at `/data`; it's created and migrated on first boot.
- **Health:** `GET /health` returns `200 ok` when the app is up and the database is
  reachable. The image's `HEALTHCHECK` already polls it.
- **Version:** `GET /version` returns the release the running image was built from, as
  plain text (e.g. `0.2.0`) — the outside check that a deploy or rollback landed the build
  you asked for. It reads nothing and touches no database, so it's safe to poll.

```
docker run -d --name spindrift \
  -p 127.0.0.1:8000:8000 \
  -v spindrift-data:/data \
  ghcr.io/theselftaughtdev42/spindrift:latest
```
