import sqlite3
from datetime import date
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from spindrift import db, deployment, snapshot
from spindrift import static_manifest as manifest
from spindrift.platforms import PLATFORMS
from spindrift.search_urls import search_url_problem
from spindrift.statuses import STATUSES
from spindrift.version import resolve_version


FINISHED = {
    "imported": "Snapshot imported",
    "reset": "Data reset completed",
}


def search_host(url):
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


def create_app(database_path):
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path)
    app.config["VERSION"] = resolve_version()

    app.jinja_env.globals["platforms"] = PLATFORMS
    app.jinja_env.globals["statuses"] = STATUSES
    app.jinja_env.globals["search_host"] = search_host
    app.jinja_env.globals["version"] = app.config["VERSION"]

    # nginx, not Flask, serves /static/ where it matters, so a digested filename is the
    # app's only cache-busting lever. No manifest means plain names.
    static_manifest = manifest.load()

    @app.url_defaults
    def digest_static_filename(endpoint, values):
        if endpoint == "static":
            filename = values.get("filename")
            if filename in static_manifest:
                values["filename"] = static_manifest[filename]

    # Digested names are only as fresh as the HTML quoting them, so documents must always
    # revalidate.
    @app.after_request
    def revalidate_documents(response):
        if response.mimetype == "text/html":
            response.cache_control.no_cache = True
        return response

    db.migrate(app.config["DATABASE_PATH"])
    app.teardown_appcontext(db.close_connection)

    # A context processor rather than a jinja global, because the answer comes out of the
    # database and can differ from one request to the next.
    @app.context_processor
    def active_search_link():
        row = (
            db.get_connection()
            .execute("SELECT url FROM search_urls WHERE active")
            .fetchone()
        )
        return {
            "active_search_url": row["url"] if row else None,
            "active_search_host": search_host(row["url"]) if row else None,
        }

    # The SELECT is the point: it makes a green check mean the database is reachable too.
    @app.get("/health")
    def health():
        db.get_connection().execute("SELECT 1")
        return "ok", 200

    @app.get("/version")
    def version():
        return app.config["VERSION"], 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def page():
        finished = FINISHED.get(request.args.get("finished"))
        return render_template("page.html", finished=finished, **catalogue())

    @app.get("/by-platform")
    def by_platform():
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
        groups = [
            (platform, games[platform])
            for platform in PLATFORMS
            if platform in games
        ]
        return render_template("by_platform.html", groups=groups)

    @app.post("/games")
    def add_game():
        name = request.form["name"].strip()
        platforms = request.form.getlist("platform")
        # Checked before the game is written, so a bad value leaves nothing behind.
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
    def rename_game(game_id):
        name = request.form["name"].strip()
        if not name:
            return render_template("_row.html", **game_row(game_id))

        connection = db.get_connection()
        try:
            connection.execute(
                "UPDATE games SET name = ? WHERE id = ?", (name, game_id)
            )
        except sqlite3.IntegrityError:
            return retargeted_catalogue(f"{name} is already in the catalogue.")
        connection.commit()
        # One row, not the whole list: the field saves on blur, and rebuilding the list would
        # pull focus back to the entry form and destroy a field just clicked into.
        return render_template("_row.html", **game_row(game_id))

    @app.post("/games/<int:game_id>/platforms/<platform>")
    def cycle_platform(game_id, platform):
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
                # The foreign key refusing a game another device deleted — the same stale
                # page as the other paths, so the same 404.
                abort(404)
            available, intended = True, False
        elif not row["intended"]:
            # Cleared first: the one-intent index rejects the pair even for the length of a
            # statement.
            connection.execute(
                "UPDATE game_platforms SET intended = 0 WHERE game_id = ? AND intended",
                (game_id,),
            )
            connection.execute(
                "UPDATE game_platforms SET intended = 1"
                " WHERE game_id = ? AND platform = ?",
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
    def set_status(game_id):
        status = request.form["status"]
        # Closed set, checked before the write. The empty string is not a value but the
        # control's way of saying nothing has been recorded.
        if status and status not in STATUSES:
            abort(400)

        connection = db.get_connection()
        connection.execute(
            "UPDATE games SET status = ? WHERE id = ?", (status or None, game_id)
        )
        connection.commit()
        return render_template("_row.html", **game_row(game_id))

    @app.delete("/games/<int:game_id>")
    def delete_game(game_id):
        connection = db.get_connection()
        # No row check: a game already gone is the outcome asked for, and a 404 would raise
        # the failure banner over a deletion that did happen.
        connection.execute("DELETE FROM games WHERE id = ?", (game_id,))
        connection.commit()
        return render_template("_catalogue.html", **catalogue())

    @app.get("/settings")
    def settings():
        return render_template("settings.html", **saved_search_urls())

    @app.post("/settings/urls")
    def add_search_url():
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
    def delete_search_url(url_id):
        connection = db.get_connection()
        connection.execute("DELETE FROM search_urls WHERE id = ?", (url_id,))
        connection.commit()
        return search_group(note="Search URL deleted.")

    @app.post("/settings/active")
    def set_active_search_url():
        """Point the catalogue's search control somewhere, or nowhere.

        The empty value is not a failure: it is the first radio, and how the control is
        turned off.
        """
        active = request.form["active"]
        connection = db.get_connection()
        if active:
            # A URL another device deleted. Clearing the flag and then failing to set it
            # would turn the search control off as a side effect.
            chosen = connection.execute(
                "SELECT url FROM search_urls WHERE id = ?", (active,)
            ).fetchone()
            if chosen is None:
                return search_group()
        # Cleared first, then set: the partial index allows only one active row.
        connection.execute("UPDATE search_urls SET active = 0 WHERE active")
        if active:
            connection.execute(
                "UPDATE search_urls SET active = 1 WHERE id = ?", (active,)
            )
        connection.commit()
        # Saving a radio that already looked chosen changes nothing you can see, so the
        # group has to say what it now does.
        note = (
            f"Searching with {search_host(chosen['url'])}."
            if active
            else "Search button turned off."
        )
        return search_group(note=note)

    @app.get("/settings/export")
    def export_snapshot():
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
    def import_snapshot():
        """Replace the deployment's entire state with an uploaded snapshot.

        Every step that can refuse runs before anything is deleted; the replacement itself
        is one transaction, so a constraint the snapshot breaks rolls it back whole.
        """
        if not request.form.get("confirm"):
            return refused(
                "snapshot",
                "Tick the box to confirm an import replaces everything."
                " Nothing was imported.",
            )
        upload = request.files.get("snapshot")
        data = upload.read() if upload else b""
        if not data:
            return refused(
                "snapshot", "Choose a snapshot file to import. Nothing was imported."
            )
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
    def reset_deployment():
        if not request.form.get("confirm"):
            return refused(
                "reset",
                "Tick the box to confirm a reset deletes everything. Nothing was deleted.",
            )
        deployment.reset(db.get_connection())
        return redirect(url_for("page", finished="reset"))

    def refused(group, error):
        """The settings page again, carrying why an import or reset did nothing.

        The group is named so the page reopens at whichever one refused.
        """
        return render_template(
            "settings.html", error=error, open_group=group, **saved_search_urls()
        )

    def search_group(error=None, draft=None, note=None):
        """The search URL group on its own, for htmx; the whole page for anything else.

        The same partial either way, so what a rejection says and where it says it does not
        depend on whether the swap happened. The whole page is rendered rather than
        redirected, the one departure from post-then-redirect here: a message through a
        redirect needs either a session or the address to carry it.
        """
        group = {
            "search_error": error,
            "draft": draft,
            "note": note,
            **saved_search_urls(),
        }
        if request.headers.get("HX-Request"):
            return render_template("_search_urls.html", **group)
        if error:
            return render_template("settings.html", open_group="search", **group)
        return redirect(url_for("settings"))

    def saved_search_urls():
        connection = db.get_connection()
        return {
            "search_urls": connection.execute(
                "SELECT id, url, active FROM search_urls ORDER BY id"
            ).fetchall()
        }

    def retargeted_catalogue(error):
        """The whole list, answering a request that asked for a single row.

        Only a rename onto a name already taken needs this, and the response has to carry
        its own target because it does not match the one the request declared.
        """
        response = make_response(
            render_template("_catalogue.html", error=error, **catalogue())
        )
        response.headers["HX-Retarget"] = "#catalogue"
        response.headers["HX-Reswap"] = "innerHTML"
        return response

    def catalogue():
        connection = db.get_connection()
        games = connection.execute(
            "SELECT id, name, status FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()
        availability = set()
        intents = {}
        for row in connection.execute(
            "SELECT game_id, platform, intended FROM game_platforms"
        ):
            availability.add((row["game_id"], row["platform"]))
            if row["intended"]:
                intents[row["game_id"]] = row["platform"]
        return {"games": games, "availability": availability, "intents": intents}

    def game_row(game_id):
        """What `catalogue()` returns, narrowed to one game.

        A missing game is a 404 rather than a `None` handed to the template: unlike a delete
        that finds nothing, the change asked for here genuinely was not saved.
        """
        connection = db.get_connection()
        game = connection.execute(
            "SELECT id, name, status FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        if game is None:
            abort(404)
        availability = set()
        intents = {}
        for row in connection.execute(
            "SELECT game_id, platform, intended FROM game_platforms WHERE game_id = ?",
            (game_id,),
        ):
            availability.add((row["game_id"], row["platform"]))
            if row["intended"]:
                intents[row["game_id"]] = row["platform"]
        return {"game": game, "availability": availability, "intents": intents}

    return app
