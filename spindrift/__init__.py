import sqlite3

from flask import Flask, abort, render_template, request

from spindrift import db
from spindrift.platforms import PLATFORMS


def create_app(database_path):
    """Construct an app against a specific database.

    Taking the path as an argument rather than defining a module-level app is what lets
    every test run against its own isolated database.
    """
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path)

    # Every template that renders any part of the matrix needs the column order, so it
    # is a global rather than an argument threaded through each render_template call.
    app.jinja_env.globals["platforms"] = PLATFORMS

    db.migrate(app.config["DATABASE_PATH"])
    app.teardown_appcontext(db.close_connection)

    @app.get("/")
    def page():
        return render_template("page.html", **catalogue())

    @app.post("/games")
    def add_game():
        name = request.form["name"].strip()
        platforms = request.form.getlist("platform")
        # Same closed set the toggle endpoint enforces. Checked before the game is
        # written so a request carrying a bad value leaves nothing behind at all.
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
        # The game and its availabilities are one write: a commit between them could
        # leave a game that momentarily claims to be playable nowhere.
        connection.executemany(
            "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
            [(cursor.lastrowid, platform) for platform in platforms],
        )
        connection.commit()
        return render_template("_catalogue.html", **catalogue())

    @app.post("/games/<int:game_id>/platforms/<platform>")
    def toggle_platform(game_id, platform):
        # The platform set is closed. An unrecognised value names nothing, so it is
        # rejected here rather than stored and rendered as a column that cannot exist.
        if platform not in PLATFORMS:
            abort(404)

        connection = db.get_connection()
        # Deleting first tells us which way the toggle went without a preceding read.
        removed = connection.execute(
            "DELETE FROM game_platforms WHERE game_id = ? AND platform = ?",
            (game_id, platform),
        ).rowcount
        if not removed:
            connection.execute(
                "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
                (game_id, platform),
            )
        connection.commit()
        # The cell's appearance is derived from what was just persisted, never assumed,
        # so the interface cannot show a state that was never stored.
        return render_template(
            "_cell.html", game_id=game_id, platform=platform, available=not removed
        )

    @app.delete("/games/<int:game_id>")
    def delete_game(game_id):
        connection = db.get_connection()
        # No row check: a game already gone is the outcome asked for, and on a second
        # device holding a stale page a 404 here would raise the failure banner over a
        # deletion that did in fact happen.
        connection.execute("DELETE FROM games WHERE id = ?", (game_id,))
        connection.commit()
        # The whole list body, because a deletion closes a gap: every row below it moves.
        return render_template("_catalogue.html", **catalogue())

    def catalogue():
        """Everything the grid draws: the games, and which of their cells are set."""
        connection = db.get_connection()
        games = connection.execute(
            "SELECT id, name FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()
        # A set of the availabilities that exist. The grid asks about every game against
        # every platform, so membership of one set beats a query per cell.
        availability = {
            (row["game_id"], row["platform"])
            for row in connection.execute("SELECT game_id, platform FROM game_platforms")
        }
        return {"games": games, "availability": availability}

    return app
