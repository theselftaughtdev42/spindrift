import logging
import sqlite3
from datetime import date
from typing import Any, cast
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    abort,
    g,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from spindrift import db, deployment, identity, snapshot
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

# The checks the orchestration layer polls, and the files a page is built from. The
# container's own HEALTHCHECK reaches `/health` on localhost, going round the proxy
# entirely, so no identity can be asked of anything here.
UNGUARDED = frozenset({"health", "version", "static"})

# Methods that only read. Everything else changes the catalogue, and is logged with a
# name against it.
READS = frozenset({"GET", "HEAD", "OPTIONS"})


def search_host(url: str) -> str:
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


def create_app(database_path: db.DatabasePath, proxy_auth: ProxyAuth | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path)
    build_version = resolve_version()

    # jinja2 types `globals` from the defaults it ships, which admit nothing an app adds.
    jinja_globals = cast("dict[str, Any]", app.jinja_env.globals)  # pragma: no mutate
    jinja_globals["platforms"] = PLATFORMS
    jinja_globals["statuses"] = STATUSES
    jinja_globals["search_host"] = search_host
    jinja_globals["version"] = build_version

    # nginx serves /static/ in deployment, so the filename is the only cache-busting lever.
    static_manifest = manifest.load()

    @app.url_defaults
    def digest_static_filename(endpoint: str, values: dict[str, Any]):
        if endpoint == "static":
            filename = values.get("filename")
            if filename in static_manifest:
                values["filename"] = static_manifest[filename]

    # Digested names are only as fresh as the HTML quoting them.
    @app.after_request
    def revalidate_documents(response: Response) -> Response:
        if response.mimetype == "text/html":
            response.cache_control.no_cache = True
        return response

    db.migrate(app.config["DATABASE_PATH"])
    app.teardown_appcontext(db.close_connection)

    # Only where a deployment says a proxy is in front. Without that statement the
    # identity headers are never read, and this is the app it has always been: no
    # sign-in, nobody's name on anything, every device on the network equal.
    if proxy_auth is not None:
        # Flask's own handler is already on the logger; what it will pass is the question.
        app.logger.setLevel(logging.INFO)
        app.logger.info("Identity comes from the proxy in front")

        @app.before_request
        def identify_cataloguer() -> ResponseReturnValue | None:
            if request.endpoint in UNGUARDED:
                return None
            cataloguer = identity.identify(request.headers)
            if cataloguer is None:
                return unidentified()
            g.cataloguer = cataloguer
            if request.method not in READS:
                # The uid as well as the name, because the name is the one that changes.
                app.logger.info(
                    "%s %s by %s (%s)",
                    request.method,
                    request.path,
                    cataloguer.name,
                    cataloguer.uid,
                )
            return None

    def unidentified() -> ResponseReturnValue:
        """A request that arrived without passing the proxy the deployment promised.

        Only a whole navigation can be sent to sign in, because the proxy answers that
        one itself. An htmx request is told to become one rather than swapping whatever
        a sign-in page says into a table row.
        """
        if request.headers.get("HX-Request"):
            return "", 401, {"HX-Redirect": url_for("page")}
        return render_template("unidentified.html"), 401

    @app.context_processor
    def signed_in_as() -> Context:
        return {
            "cataloguer": g.get("cataloguer"),
            "auth_hub": proxy_auth.hub_url if proxy_auth else None,
            "behind_proxy": proxy_auth is not None,
        }

    @app.context_processor
    def active_search_link() -> Context:
        row = db.get_connection().execute("SELECT url FROM search_urls WHERE active").fetchone()
        return {
            "active_search_url": row["url"] if row else None,
            "active_search_host": search_host(row["url"]) if row else None,
        }

    # The SELECT makes a green check mean the database is reachable too.
    @app.get("/health")
    def health() -> ResponseReturnValue:
        db.get_connection().execute("SELECT 1")
        return "ok", 200

    @app.get("/version")
    def version() -> ResponseReturnValue:
        return build_version, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def page() -> str:
        finished = FINISHED.get(request.args.get("finished"))
        return render_template("page.html", finished=finished, **catalogue())

    @app.get("/by-platform")
    def by_platform() -> str:
        connection = db.get_connection()
        decisions = connection.execute(
            "SELECT game_platforms.platform, games.name, games.status"
            " FROM game_platforms JOIN games ON games.id = game_platforms.game_id"
            " WHERE game_platforms.intended"
            " ORDER BY games.name COLLATE NOCASE"
        ).fetchall()

        games = {}
        for decision in decisions:
            games.setdefault(decision["platform"], []).append(decision)
        groups = [(platform, games[platform]) for platform in PLATFORMS if platform in games]
        return render_template("by_platform.html", groups=groups)

    @app.post("/games")
    def add_game() -> str:
        name = request.form["name"].strip()
        platforms = request.form.getlist("platform")
        # Checked first, so a bad platform leaves no game behind.
        if any(platform not in PLATFORMS for platform in platforms):
            abort(400)
        if not name:
            return render_template("_catalogue.html", **catalogue())

        connection = db.get_connection()
        try:
            cursor = connection.execute("INSERT INTO games (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            error = f"{name} is already in the catalogue."
            return render_template("_catalogue.html", error=error, **catalogue())
        # One write: a commit between the two could leave a game playable nowhere.
        connection.executemany(
            "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
            [(cursor.lastrowid, platform) for platform in platforms],
        )
        connection.commit()
        return render_template("_catalogue.html", **catalogue())

    @app.post("/games/<int:game_id>/name")
    def rename_game(game_id: int) -> ResponseReturnValue:
        name = request.form["name"].strip()
        if not name:
            return render_template("_row.html", **game_row(game_id))

        connection = db.get_connection()
        try:
            connection.execute("UPDATE games SET name = ? WHERE id = ?", (name, game_id))
        except sqlite3.IntegrityError:
            return retargeted_catalogue(f"{name} is already in the catalogue.")
        connection.commit()
        # One row, not the list: rebuilding it would steal focus from the field just used.
        return render_template("_row.html", **game_row(game_id))

    @app.post("/games/<int:game_id>/platforms/<platform>")
    def cycle_platform(game_id: int, platform: str) -> str:
        """Advance one cell through: not playable → playable → the way I'll play it."""
        if platform not in PLATFORMS:
            abort(404)

        connection = db.get_connection()
        # Read first: which way a third state goes cannot be inferred from a blind delete.
        row = connection.execute(
            "SELECT intended FROM game_platforms WHERE game_id = ? AND platform = ?",
            (game_id, platform),
        ).fetchone()

        if row is None:
            try:
                connection.execute(
                    "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
                    (game_id, platform),
                )
            except sqlite3.IntegrityError:
                # The foreign key refusing a game another device deleted.
                abort(404)
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
        return render_template("_row.html", **game_row(game_id))

    @app.post("/games/<int:game_id>/status")
    def set_status(game_id: int) -> str:
        status = request.form["status"]
        # The empty string is the control saying nothing is recorded, not a status.
        if status and status not in STATUSES:
            abort(400)

        connection = db.get_connection()
        connection.execute("UPDATE games SET status = ? WHERE id = ?", (status or None, game_id))
        connection.commit()
        return render_template("_row.html", **game_row(game_id))

    @app.delete("/games/<int:game_id>")
    def delete_game(game_id: int) -> str:
        connection = db.get_connection()
        # No row check: a game already gone is the outcome asked for.
        connection.execute("DELETE FROM games WHERE id = ?", (game_id,))
        connection.commit()
        return render_template("_catalogue.html", **catalogue())

    @app.get("/settings")
    def settings() -> str:
        return render_template("settings.html", **saved_search_urls())

    @app.post("/settings/urls")
    def add_search_url() -> ResponseReturnValue:
        url = request.form["url"].strip()
        if not url:
            return search_group()
        problem = search_url_problem(url)
        if problem:
            return search_group(error=problem, draft=url)

        connection = db.get_connection()
        try:
            connection.execute("INSERT INTO search_urls (url) VALUES (?)", (url,))
        except sqlite3.IntegrityError:
            return search_group(error="That URL is already saved.", draft=url)
        connection.commit()
        return search_group(note=f"{search_host(url)} added.")

    @app.post("/settings/urls/<int:url_id>/delete")
    def delete_search_url(url_id: int) -> ResponseReturnValue:
        connection = db.get_connection()
        connection.execute("DELETE FROM search_urls WHERE id = ?", (url_id,))
        connection.commit()
        return search_group(note="Search URL deleted.")

    @app.post("/settings/active")
    def set_active_search_url() -> ResponseReturnValue:
        """Point the search control somewhere, or nowhere; the empty value turns it off."""
        active = request.form["active"]
        connection = db.get_connection()
        note = "Search button turned off."
        if active:
            # Checked before clearing, or a URL another device deleted turns the control off.
            chosen = connection.execute(
                "SELECT url FROM search_urls WHERE id = ?", (active,)
            ).fetchone()
            if chosen is None:
                return search_group()
            note = f"Searching with {search_host(chosen['url'])}."
        # Cleared first, then set: the partial index allows only one active row.
        connection.execute("UPDATE search_urls SET active = 0 WHERE active")
        if active:
            connection.execute("UPDATE search_urls SET active = 1 WHERE id = ?", (active,))
        connection.commit()
        return search_group(note=note)

    @app.get("/settings/export")
    def export_snapshot() -> ResponseReturnValue:
        filename = f"spindrift-{date.today().isoformat()}.json"
        return (
            deployment.export(db.get_connection()),
            200,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.post("/settings/import")
    def import_snapshot() -> ResponseReturnValue:
        """Replace the deployment's entire state with an uploaded snapshot.

        Everything that can refuse runs before anything is deleted.
        """
        if not request.form.get("confirm"):
            return refused(
                "snapshot",
                "Tick the box to confirm an import replaces everything. Nothing was imported.",
            )
        upload = request.files.get("snapshot")
        data = upload.read() if upload else b""
        if not data:
            return refused("snapshot", "Choose a snapshot file to import. Nothing was imported.")
        try:
            parsed = snapshot.parse(data)
        except snapshot.SnapshotError as error:
            return refused("snapshot", str(error))
        try:
            deployment.replace(db.get_connection(), parsed)
        except sqlite3.IntegrityError:
            return refused(
                "snapshot",
                f"Import failed — that snapshot breaks one of the catalogue's rules, such"
                f" as two games with the same name. {snapshot.UNCHANGED}",
            )
        return redirect(url_for("page", finished="imported"))

    @app.post("/settings/reset")
    def reset_deployment() -> ResponseReturnValue:
        if not request.form.get("confirm"):
            return refused(
                "reset",
                "Tick the box to confirm a reset deletes everything. Nothing was deleted.",
            )
        deployment.reset(db.get_connection())
        return redirect(url_for("page", finished="reset"))

    def refused(group: str, error: str) -> str:
        """The settings page again, reopened at the group that refused."""
        return render_template(
            "settings.html", error=error, open_group=group, **saved_search_urls()
        )

    def search_group(
        error: str | None = None, draft: str | None = None, note: str | None = None
    ) -> ResponseReturnValue:
        """The search URL group on its own, for htmx; the whole page for anything else.

        An error renders rather than redirects, because a redirect cannot carry the message.
        """
        group = {
            "search_error": error,
            "draft": draft,
            "note": note,
            **saved_search_urls(),
        }
        if request.headers.get("HX-Request"):  # pragma: no mutate
            return render_template("_search_urls.html", **group)
        if error:
            return render_template("settings.html", open_group="search", **group)
        return redirect(url_for("settings"))

    def saved_search_urls() -> Context:
        connection = db.get_connection()
        return {
            "search_urls": connection.execute(
                "SELECT id, url, active FROM search_urls ORDER BY id"  # pragma: no mutate
            ).fetchall()
        }

    def retargeted_catalogue(error: str) -> Response:
        """The whole list, answering a request that asked for a single row.

        It carries its own target, which no longer matches the one the request declared.
        """
        response = make_response(render_template("_catalogue.html", error=error, **catalogue()))
        response.headers["HX-Retarget"] = "#catalogue"  # pragma: no mutate
        response.headers["HX-Reswap"] = "innerHTML"  # pragma: no mutate
        return response

    def catalogue() -> Context:
        connection = db.get_connection()
        games = connection.execute(
            "SELECT id, name, status FROM games ORDER BY name COLLATE NOCASE"  # pragma: no mutate
        ).fetchall()
        availability = set()
        intents = {}
        for row in connection.execute(
            "SELECT game_id, platform, intended FROM game_platforms"  # pragma: no mutate
        ):
            availability.add((row["game_id"], row["platform"]))  # pragma: no mutate
            if row["intended"]:  # pragma: no mutate
                intents[row["game_id"]] = row["platform"]  # pragma: no mutate
        return {"games": games, "availability": availability, "intents": intents}

    def game_row(game_id: int) -> Context:
        """What `catalogue()` returns, narrowed to one game."""
        connection = db.get_connection()
        game = connection.execute(
            "SELECT id, name, status FROM games WHERE id = ?",  # pragma: no mutate
            (game_id,),
        ).fetchone()
        if game is None:
            abort(404)
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

    return app
