# Served by FastAPI under uvicorn, not Flask under gunicorn

Spindrift began as a Flask app served by gunicorn. It is now a FastAPI app served by uvicorn.
Speed was not the reason: the app does blocking SQLite and renders HTML for htmx, so it is no
faster. What it gains is typed inputs and dependency injection. A route declares its path and
form parameters in its signature and receives them parsed, so ty checks handlers end to end;
the database connection and the request's owner are dependencies, rather than state hung on
Flask's `g` by `before_request` hooks. The templates stay Jinja2, and nothing a browser sees
changed.

## Consequences

- The entry point is `spindrift/asgi.py`, served with
  `uvicorn spindrift.asgi:app --host 0.0.0.0 --port 8000`, by `main.py` locally and by the
  image's `CMD`.
- gunicorn is gone rather than kept as a uvicorn process manager. One process is enough: the
  catalogue is one SQLite file in WAL mode, and extra workers would only queue on its write
  lock.
- Uvicorn attaches no handler to an application's logger, so the app configures its own.
- Starlette's `url_for` builds absolute URLs from the request's host. The templates use the
  app's own, which returns paths and the digested static names, so the app stays correct
  behind a proxy without trusting forwarded headers.
- Form parsing needs `python-multipart`, which is now a runtime dependency.
