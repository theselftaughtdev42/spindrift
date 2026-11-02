import logging
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, cast
from urllib.parse import quote, urlencode, urlsplit

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from jinja2.runtime import Context as TemplateContext

from spindrift import db, deployment, identity, ownership, pwa, snapshot
from spindrift import static_manifest as manifest
from spindrift.identity import ProxyAuth
from spindrift.platforms import PLATFORMS
from spindrift.search_urls import search_url_problem
from spindrift.statuses import STATUSES
from spindrift.version import resolve_version

# What a template is handed. The values are rows, sets and strings a template reads and
# nothing here does, so naming them would say more than the code knows.
type Context = dict[str, Any]

FINISHED = {
    "imported": "Snapshot imported",
    "reset": "Data reset completed",
}

# Methods that only read. Everything else changes the catalogue, and is logged with a
# name against it.
READS = frozenset({"GET", "HEAD", "OPTIONS"})

PACKAGE = Path(__file__).resolve().parent

# Uvicorn attaches no handler to an application's logger, so the app brings its own.
logger = logging.getLogger("spindrift")

# A redirect that sends a POST on as a GET. FastAPI's default, 307, would repeat the POST.
FOUND = 302


def search_host(url: str) -> str:
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


class Unidentified(Exception):
    """A request that arrived without passing the proxy the deployment promised."""


Connection = Annotated[sqlite3.Connection, Depends(db.get_connection)]


def owner(request: Request, connection: Connection) -> int:
    """Whose catalogue this request reads and writes, settled before any route runs."""
    proxy_auth = cast("ProxyAuth | None", request.app.state.proxy_auth)  # pragma: no mutate
    # Nobody to own anything, so the deployment's one catalogue is the default owner's.
    if proxy_auth is None:
        request.state.owner = ownership.DEFAULT_OWNER
        return ownership.DEFAULT_OWNER
    cataloguer = identity.identify(request.headers)
    if cataloguer is None:
        raise Unidentified
    request.state.cataloguer = cataloguer
    request.state.owner = ownership.owner_of(connection, cataloguer.uid)
    if request.method not in READS:
        # The uid as well as the name, because the name is the one that changes.
        logger.info(
            "%s %s by %s (%s)", request.method, request.url.path, cataloguer.name, cataloguer.uid
        )
    return request.state.owner


Owner = Annotated[int, Depends(owner)]


@dataclass(frozen=True)
class Field:
    """A required text field, kept as sent.

    `Form()` reads an empty value as a missing one, and here the empty value means something:
    a cleared status, a search control turned off, a name left blank.
    """

    name: str

    async def __call__(self, request: Request) -> str:
        value = (await request.form()).get(self.name)
        if not isinstance(value, str):
            raise HTTPException(400)
        return value


def route_path(request: Request, name: str, params: Mapping[str, object]) -> str:
    """A route's path, relative like the ones the proxy forwards, never an absolute URL."""
    if name == "static":
        # nginx serves /static/ in deployment, so the filename is the only cache-busting lever.
        filename = str(params["filename"])
        digested = request.app.state.static.get(filename, filename)
        return str(request.app.url_path_for("static", path=digested))
    # Percent-encoded, so a platform's space is %20. No platform has a slash for `safe` to
    # matter to, and a number reads the same encoded or not.
    quoted = {key: quote(str(value), safe="") for key, value in params.items()}  # pragma: no mutate
    return str(request.app.url_path_for(name, **quoted))


def path_for(
    request: Request,
    name: str,
    /,
    *,
    query: Mapping[str, str] | None = None,
    anchor: str | None = None,
    **params: object,
) -> str:
    """`route_path`, with the query string and anchor a redirect may carry."""
    path = route_path(request, name, params)
    if query:
        path += "?" + urlencode(query)
    if anchor:
        path += "#" + anchor
    return path


@pass_context
def url_for(context: TemplateContext, name: str, /, **params: object) -> str:
    return route_path(context["request"], name, params)


def signed_in_as(request: Request) -> Context:
    proxy_auth = cast("ProxyAuth | None", request.app.state.proxy_auth)  # pragma: no mutate
    return {
        "cataloguer": getattr(request.state, "cataloguer", None),
        "auth_hub": proxy_auth.hub_url if proxy_auth else None,
        "behind_proxy": proxy_auth is not None,
        "version": request.app.state.version,
        "theme_colour": pwa.theme_colour(),
    }


def active_search_link(request: Request) -> Context:
    # No owner is a request refused before it was identified, which has nobody's link.
    owner = getattr(request.state, "owner", None)
    row = (
        None
        if owner is None
        else request.state.connection.execute(
            "SELECT url FROM search_urls WHERE owner_id = ? AND active",  # pragma: no mutate
            (owner,),
        ).fetchone()
    )
    return {
        "active_search_url": row["url"] if row else None,  # pragma: no mutate
        "active_search_host": search_host(row["url"]) if row else None,  # pragma: no mutate
    }


templates = Jinja2Templates(
    directory=PACKAGE / "templates", context_processors=[signed_in_as, active_search_link]
)
# jinja2 types `globals` from the defaults it ships, which admit nothing an app adds.
jinja_globals = cast("dict[str, Any]", templates.env.globals)  # pragma: no mutate
# Over Starlette's own, which returns absolute URLs and knows nothing of the digests.
jinja_globals["url_for"] = url_for
jinja_globals["platforms"] = PLATFORMS
jinja_globals["statuses"] = STATUSES
jinja_globals["search_host"] = search_host


def render(request: Request, name: str, status_code: int = 200, **context: object) -> Response:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(path: str) -> Response:
    return RedirectResponse(path, status_code=FOUND)


def htmx(request: Request) -> bool:
    return bool(request.headers.get("HX-Request"))  # pragma: no mutate


# The checks the orchestration layer polls, and the files a page is built from. The
# container's own HEALTHCHECK reaches `/health` on localhost, going round the proxy
# entirely, so no identity can be asked of anything here. The manifest and service worker
# are files a page is built from too, and say nothing about anyone's catalogue.
unguarded = APIRouter()

# Everything else: whose catalogue it is gets settled before the route runs.
guarded = APIRouter(dependencies=[Depends(owner)])


# The SELECT makes a green check mean the database is reachable too.
@unguarded.api_route("/health", methods=["GET", "HEAD"])
def health(connection: Connection) -> Response:
    connection.execute("SELECT 1")
    return PlainTextResponse("ok")


# Not `version`, which would hide the module of that name on the package.
@unguarded.api_route("/version", methods=["GET", "HEAD"], name="version")
def build_version(request: Request) -> Response:
    return PlainTextResponse(request.app.state.version)


@unguarded.get("/manifest.webmanifest")
def web_manifest(request: Request) -> Response:
    """What an installed Spindrift is called, where it opens, and the icons it shows."""
    icons = [
        ("icon-192.png", "192x192", "any"),
        ("icon-512.png", "512x512", "any"),
        ("icon-maskable-512.png", "512x512", "maskable"),
    ]
    page_path = path_for(request, "page")
    content = {
        "id": page_path,
        "name": "Spindrift",
        "short_name": "Spindrift",
        "description": "A catalogue of games and the ways they can be played.",
        "start_url": page_path,
        "scope": page_path,
        "display": "standalone",
        "background_color": pwa.theme_colour(),
        "theme_color": pwa.theme_colour(),
        "icons": [
            {
                "src": path_for(request, "static", filename=filename),
                "sizes": sizes,
                "type": "image/png",
                "purpose": purpose,
            }
            for filename, sizes, purpose in icons
        ],
    }
    return JSONResponse(content, media_type="application/manifest+json")


# At the root, not under /static/: a service worker only reaches pages at or below the
# path it was served from. Revalidated every time, so a new one is never stuck behind a
# cache.
@unguarded.get("/sw.js")
def service_worker() -> Response:
    return Response(
        pwa.service_worker(), media_type="text/javascript", headers={"Cache-Control": "no-cache"}
    )


@guarded.get("/")
def page(
    request: Request, connection: Connection, owner: Owner, finished: str | None = None
) -> Response:
    return render(
        request,
        "page.html",
        finished=FINISHED.get(finished or ""),
        **catalogue(connection, owner),
    )


@guarded.get("/by-platform")
def by_platform(request: Request, connection: Connection, owner: Owner) -> Response:
    decisions = connection.execute(
        "SELECT game_platforms.platform, game_platforms.wishlisted,"
        " games.id, games.name, games.status"
        " FROM game_platforms JOIN games ON games.id = game_platforms.game_id"
        " WHERE games.owner_id = ? AND game_platforms.intended"
        " ORDER BY games.name COLLATE NOCASE",
        (owner,),
    ).fetchall()

    games = {}
    for decision in decisions:
        games.setdefault(decision["platform"], []).append(decision)
    groups = [(platform, games[platform]) for platform in PLATFORMS if platform in games]
    return render(
        request,
        "by_platform.html",
        groups=groups,
        wishlist=deployment.wishlist_enabled(connection, owner),
    )


@guarded.post("/games/{game_id:int}/platforms/{platform}/wishlist")
def toggle_wishlisted(
    request: Request, connection: Connection, owner: Owner, game_id: int, platform: str
) -> Response:
    """Mark or unmark one availability as on that platform's store wishlist."""
    # The feature off is as if the route weren't there.
    if not deployment.wishlist_enabled(connection, owner):
        raise HTTPException(404)
    # Through the game, so another cataloguer's availability is as absent as a missing one.
    row = connection.execute(
        "SELECT game_platforms.wishlisted, games.name FROM game_platforms"
        " JOIN games ON games.id = game_platforms.game_id"
        " WHERE games.id = ? AND games.owner_id = ? AND game_platforms.platform = ?",
        (game_id, owner, platform),
    ).fetchone()
    if row is None:
        raise HTTPException(404)
    wishlisted = not row["wishlisted"]
    connection.execute(
        "UPDATE game_platforms SET wishlisted = ? WHERE game_id = ? AND platform = ?",
        (wishlisted, game_id, platform),
    )
    connection.commit()
    if not htmx(request):
        # Back to the row, or a long page would land at the top.
        anchor = f"wishlisted-{game_id}-{platform.replace(' ', '-')}"
        return redirect(path_for(request, "by_platform", anchor=anchor))
    return render(
        request,
        "_wishlisted.html",
        game={"id": game_id, "name": row["name"], "wishlisted": wishlisted},
        platform=platform,
    )


@guarded.post("/games")
def add_game(
    request: Request,
    connection: Connection,
    owner: Owner,
    name: Annotated[str, Depends(Field("name"))],
    platform: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI copies defaults
) -> Response:
    name = name.strip()
    # Checked first, so a bad platform leaves no game behind.
    if any(chosen not in PLATFORMS for chosen in platform):
        raise HTTPException(400)
    if not name:
        return render(request, "_catalogue.html", **catalogue(connection, owner))

    try:
        cursor = connection.execute(
            "INSERT INTO games (owner_id, name) VALUES (?, ?)", (owner, name)
        )
    except sqlite3.IntegrityError:
        error = f"{name} is already in the catalogue."
        return render(request, "_catalogue.html", error=error, **catalogue(connection, owner))
    # One write: a commit between the two could leave a game playable nowhere.
    connection.executemany(
        "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
        [(cursor.lastrowid, chosen) for chosen in platform],
    )
    connection.commit()
    return render(request, "_catalogue.html", **catalogue(connection, owner))


@guarded.post("/games/{game_id:int}/name")
def rename_game(
    request: Request,
    connection: Connection,
    owner: Owner,
    game_id: int,
    name: Annotated[str, Depends(Field("name"))],
) -> Response:
    name = name.strip()
    if not name:
        return render(request, "_row.html", **game_row(connection, owner, game_id))

    try:
        connection.execute(
            "UPDATE games SET name = ? WHERE id = ? AND owner_id = ?",
            (name, game_id, owner),
        )
    except sqlite3.IntegrityError:
        return retargeted_catalogue(
            request, connection, owner, f"{name} is already in the catalogue."
        )
    connection.commit()
    # One row, not the list: rebuilding it would steal focus from the field just used.
    return render(request, "_row.html", **game_row(connection, owner, game_id))


@guarded.post("/games/{game_id:int}/platforms/{platform}")
def cycle_platform(
    request: Request, connection: Connection, owner: Owner, game_id: int, platform: str
) -> Response:
    """Advance one cell through: not playable → playable → the way I'll play it."""
    if platform not in PLATFORMS:
        raise HTTPException(404)

    # Read first: which way a third state goes cannot be inferred from a blind delete.
    # Through the game, so another cataloguer's is as absent as one that never was.
    row = connection.execute(
        "SELECT game_platforms.intended FROM games LEFT JOIN game_platforms"
        " ON game_platforms.game_id = games.id AND game_platforms.platform = ?"
        " WHERE games.id = ? AND games.owner_id = ?",
        (platform, game_id, owner),
    ).fetchone()
    if row is None:
        raise HTTPException(404)

    if row["intended"] is None:
        try:
            connection.execute(
                "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
                (game_id, platform),
            )
        except sqlite3.IntegrityError:
            # The foreign key refusing a game another device deleted.
            raise HTTPException(404) from None
    elif not row["intended"]:
        # Cleared first: the one-intent index rejects the pair mid-statement.
        connection.execute(
            "UPDATE game_platforms SET intended = 0 WHERE game_id = ? AND intended",
            (game_id,),
        )
        connection.execute(
            "UPDATE game_platforms SET intended = 1 WHERE game_id = ? AND platform = ?",
            (game_id, platform),
        )
    else:
        connection.execute(
            "DELETE FROM game_platforms WHERE game_id = ? AND platform = ?",
            (game_id, platform),
        )
    connection.commit()

    # The whole row, because deciding on a platform un-decides another cell in it.
    return render(request, "_row.html", **game_row(connection, owner, game_id))


@guarded.post("/games/{game_id:int}/status")
def set_status(
    request: Request,
    connection: Connection,
    owner: Owner,
    game_id: int,
    status: Annotated[str, Depends(Field("status"))],
) -> Response:
    # The empty string is the control saying nothing is recorded, not a status.
    if status and status not in STATUSES:
        raise HTTPException(400)

    connection.execute(
        "UPDATE games SET status = ? WHERE id = ? AND owner_id = ?",
        (status or None, game_id, owner),
    )
    connection.commit()
    return render(request, "_row.html", **game_row(connection, owner, game_id))


@guarded.delete("/games/{game_id:int}")
def delete_game(request: Request, connection: Connection, owner: Owner, game_id: int) -> Response:
    # No row check: a game already gone is the outcome asked for.
    connection.execute("DELETE FROM games WHERE id = ? AND owner_id = ?", (game_id, owner))
    connection.commit()
    return render(request, "_catalogue.html", **catalogue(connection, owner))


@guarded.get("/settings")
def settings(
    request: Request, connection: Connection, owner: Owner, saved: str | None = None
) -> Response:
    return render(
        request,
        "settings.html",
        open_group="wishlist" if saved == "wishlist" else None,
        **saved_search_urls(connection, owner),
        **wishlist_setting(connection, owner),
    )


@guarded.post("/settings/wishlist")
def set_wishlist(
    request: Request,
    connection: Connection,
    owner: Owner,
    enabled: Annotated[str | None, Form()] = None,
) -> Response:
    """Turn the wishlist on or off for this cataloguer. Marks survive turning it off."""
    with connection:
        deployment.set_wishlist(connection, owner, bool(enabled))
    return redirect(path_for(request, "settings", query={"saved": "wishlist"}))


@guarded.post("/settings/urls")
def add_search_url(
    request: Request,
    connection: Connection,
    owner: Owner,
    url: Annotated[str, Depends(Field("url"))],
) -> Response:
    url = url.strip()
    if not url:
        return search_group(request, connection, owner)
    problem = search_url_problem(url)
    if problem:
        return search_group(request, connection, owner, error=problem, draft=url)

    try:
        connection.execute("INSERT INTO search_urls (owner_id, url) VALUES (?, ?)", (owner, url))
    except sqlite3.IntegrityError:
        return search_group(
            request, connection, owner, error="That URL is already saved.", draft=url
        )
    connection.commit()
    return search_group(request, connection, owner, note=f"{search_host(url)} added.")


@guarded.post("/settings/urls/{url_id:int}/delete")
def delete_search_url(
    request: Request, connection: Connection, owner: Owner, url_id: int
) -> Response:
    connection.execute("DELETE FROM search_urls WHERE id = ? AND owner_id = ?", (url_id, owner))
    connection.commit()
    return search_group(request, connection, owner, note="Search URL deleted.")


@guarded.post("/settings/active")
def set_active_search_url(
    request: Request,
    connection: Connection,
    owner: Owner,
    active: Annotated[str, Depends(Field("active"))],
) -> Response:
    """Point the search control somewhere, or nowhere; the empty value turns it off."""
    note = "Search button turned off."
    if active:
        # Checked before clearing, or a URL another device deleted turns the control off.
        chosen = connection.execute(
            "SELECT url FROM search_urls WHERE id = ? AND owner_id = ?", (active, owner)
        ).fetchone()
        if chosen is None:
            return search_group(request, connection, owner)
        note = f"Searching with {search_host(chosen['url'])}."
    # Cleared first, then set: the partial index allows only one active row.
    connection.execute("UPDATE search_urls SET active = 0 WHERE owner_id = ? AND active", (owner,))
    if active:
        connection.execute(
            "UPDATE search_urls SET active = 1 WHERE id = ? AND owner_id = ?",
            (active, owner),
        )
    connection.commit()
    return search_group(request, connection, owner, note=note)


@guarded.get("/settings/export")
def export_snapshot(connection: Connection, owner: Owner) -> Response:
    filename = f"spindrift-{date.today().isoformat()}.json"
    return Response(
        deployment.export(connection, owner),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@guarded.post("/settings/import")
async def import_snapshot(
    request: Request,
    connection: Connection,
    owner: Owner,
    confirm: Annotated[str | None, Form()] = None,
    snapshot_file: Annotated[UploadFile | None, Form(alias="snapshot")] = None,
) -> Response:
    """Replace this cataloguer's catalogue with an uploaded snapshot.

    Everything that can refuse runs before anything is deleted.
    """
    if not confirm:
        return refused(
            request,
            connection,
            owner,
            "snapshot",
            "Tick the box to confirm an import replaces everything. Nothing was imported.",
        )
    data = await snapshot_file.read() if snapshot_file else b""
    if not data:
        return refused(
            request,
            connection,
            owner,
            "snapshot",
            "Choose a snapshot file to import. Nothing was imported.",
        )
    try:
        parsed = snapshot.parse(data)
    except snapshot.SnapshotError as error:
        return refused(request, connection, owner, "snapshot", str(error))
    try:
        deployment.replace(connection, owner, parsed)
    except sqlite3.IntegrityError:
        return refused(
            request,
            connection,
            owner,
            "snapshot",
            f"Import failed — that snapshot breaks one of the catalogue's rules, such"
            f" as two games with the same name. {snapshot.UNCHANGED}",
        )
    return redirect(path_for(request, "page", query={"finished": "imported"}))


@guarded.post("/settings/reset")
def reset_deployment(
    request: Request,
    connection: Connection,
    owner: Owner,
    confirm: Annotated[str | None, Form()] = None,
) -> Response:
    if not confirm:
        return refused(
            request,
            connection,
            owner,
            "reset",
            "Tick the box to confirm a reset deletes everything. Nothing was deleted.",
        )
    deployment.reset(connection, owner)
    return redirect(path_for(request, "page", query={"finished": "reset"}))


def refused(
    request: Request, connection: sqlite3.Connection, owner: int, group: str, error: str
) -> Response:
    """The settings page again, reopened at the group that refused."""
    return render(
        request,
        "settings.html",
        error=error,
        open_group=group,
        **saved_search_urls(connection, owner),
        **wishlist_setting(connection, owner),
    )


def search_group(
    request: Request,
    connection: sqlite3.Connection,
    owner: int,
    error: str | None = None,
    draft: str | None = None,
    note: str | None = None,
) -> Response:
    """The search URL group on its own, for htmx; the whole page for anything else.

    An error renders rather than redirects, because a redirect cannot carry the message.
    """
    group: Context = {
        "search_error": error,
        "draft": draft,
        "note": note,
        **saved_search_urls(connection, owner),
    }
    if htmx(request):  # pragma: no mutate
        return render(request, "_search_urls.html", **group)
    if error:
        return render(
            request,
            "settings.html",
            open_group="search",
            **group,
            **wishlist_setting(connection, owner),
        )
    return redirect(path_for(request, "settings"))


def wishlist_setting(connection: sqlite3.Connection, owner: int) -> Context:
    return {"wishlist": deployment.wishlist_enabled(connection, owner)}


def saved_search_urls(connection: sqlite3.Connection, owner: int) -> Context:
    return {
        "search_urls": connection.execute(
            "SELECT id, url, active FROM search_urls WHERE owner_id = ?"  # pragma: no mutate
            " ORDER BY id",  # pragma: no mutate
            (owner,),
        ).fetchall(),
    }


def retargeted_catalogue(
    request: Request, connection: sqlite3.Connection, owner: int, error: str
) -> Response:
    """The whole list, answering a request that asked for a single row.

    It carries its own target, which no longer matches the one the request declared.
    """
    response = render(request, "_catalogue.html", error=error, **catalogue(connection, owner))
    response.headers["HX-Retarget"] = "#catalogue"  # pragma: no mutate
    response.headers["HX-Reswap"] = "innerHTML"  # pragma: no mutate
    return response


def catalogue(connection: sqlite3.Connection, owner: int) -> Context:
    games = connection.execute(
        "SELECT id, name, status FROM games WHERE owner_id = ?"  # pragma: no mutate
        " ORDER BY name COLLATE NOCASE",  # pragma: no mutate
        (owner,),
    ).fetchall()
    availability = set()
    intents = {}
    for row in connection.execute(
        "SELECT game_id, platform, intended FROM game_platforms"  # pragma: no mutate
        " JOIN games ON games.id = game_platforms.game_id"  # pragma: no mutate
        " WHERE games.owner_id = ?",  # pragma: no mutate
        (owner,),
    ):
        availability.add((row["game_id"], row["platform"]))  # pragma: no mutate
        if row["intended"]:  # pragma: no mutate
            intents[row["game_id"]] = row["platform"]  # pragma: no mutate
    return {"games": games, "availability": availability, "intents": intents}


def game_row(connection: sqlite3.Connection, owner: int, game_id: int) -> Context:
    """What `catalogue()` returns, narrowed to one game."""
    game = connection.execute(
        "SELECT id, name, status FROM games WHERE id = ? AND owner_id = ?",  # pragma: no mutate
        (game_id, owner),
    ).fetchone()
    if game is None:
        raise HTTPException(404)
    availability = set()
    intents = {}
    for row in connection.execute(
        "SELECT game_id, platform, intended FROM game_platforms"  # pragma: no mutate
        " WHERE game_id = ?",  # pragma: no mutate
        (game_id,),
    ):
        availability.add((row["game_id"], row["platform"]))  # pragma: no mutate
        if row["intended"]:  # pragma: no mutate
            intents[row["game_id"]] = row["platform"]  # pragma: no mutate
    return {"game": game, "availability": availability, "intents": intents}


async def unidentified(request: Request, _: Exception) -> Response:
    """Only a whole navigation can be sent to sign in, because the proxy answers that one
    itself. An htmx request is told to become one rather than swapping whatever a sign-in
    page says into a table row.
    """
    if htmx(request):
        # Header names are matched without regard to case, so their spelling is not a mutant.
        redirect_to = path_for(request, "page")
        return Response(status_code=401, headers={"HX-Redirect": redirect_to})  # pragma: no mutate
    return render(request, "unidentified.html", status_code=401)


async def bad_request(_: Request, __: Exception) -> Response:
    """A missing or malformed field is the client's mistake: 400, not FastAPI's 422."""
    return PlainTextResponse("Bad Request", status_code=400)


async def revalidate_documents(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Digested names are only as fresh as the HTML quoting them."""
    # Header names are matched without regard to case, so their spelling is not a mutant; nor
    # is the request handed on, which the middleware reads from the connection, not this.
    response = await call_next(request)  # pragma: no mutate
    content_type = response.headers.get("Content-Type", "")  # pragma: no mutate
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"  # pragma: no mutate
    return response


def create_app(database_path: db.DatabasePath, proxy_auth: ProxyAuth | None = None) -> FastAPI:
    # No API schema, and so none of the documentation pages built from it: nothing here is an API.
    app = FastAPI(openapi_url=None)
    app.state.database_path = str(database_path)
    app.state.proxy_auth = proxy_auth
    app.state.version = resolve_version()
    app.state.static = manifest.load()

    db.migrate(app.state.database_path)

    # Only where a deployment says a proxy is in front. Without that statement the
    # identity headers are never read, and this is the app it has always been: no
    # sign-in, nobody's name on anything, every device on the network equal.
    if proxy_auth is not None:
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
            )
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.info("Identity comes from the proxy in front")

    app.middleware("http")(revalidate_documents)
    app.add_exception_handler(Unidentified, unidentified)
    app.add_exception_handler(RequestValidationError, bad_request)
    app.include_router(unguarded)
    app.include_router(guarded)
    # nginx serves /static/ in deployment; this is the same files for a run from source.
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    return app
