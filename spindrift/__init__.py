import os
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

    # The prefix a game's name is appended to for a web search — a whole storefront or
    # search engine's query URL, ending wherever the term goes. Unset is the normal
    # case and means the catalogue renders exactly as it did before this existed: no
    # search control anywhere, rather than one pointing nowhere.
    #
    # Empty string is treated as unset, because `GAME_SEARCH_URL=` in a shell profile or
    # a compose file reads as turning the feature off, not as searching the empty prefix.
    # Read once here, so the toggle is a property of a running server and flipping it is
    # a restart.
    app.config["GAME_SEARCH_URL"] = os.environ.get("GAME_SEARCH_URL") or None

    db.migrate(app.config["DATABASE_PATH"])
    app.teardown_appcontext(db.close_connection)

    @app.get("/")
    def page():
        return render_template("page.html", **catalogue())

    @app.get("/by-platform")
    def by_platform():
        """The decisions, gathered under the platform each one names.

        The catalogue answers "where could I play this" a row at a time. This answers
        "what am I playing on the Switch" — which the grid can only be read sideways for
        on a desktop, and not at all on a phone, where the reflow trades the columns away
        for cards. Decided games only: an undecided game has no answer to give here.
        """
        connection = db.get_connection()
        decisions = connection.execute(
            "SELECT game_platforms.platform, games.name"
            " FROM game_platforms JOIN games ON games.id = game_platforms.game_id"
            " WHERE game_platforms.intended"
            " ORDER BY games.name COLLATE NOCASE"
        ).fetchall()

        games = {}
        for decision in decisions:
            games.setdefault(decision["platform"], []).append(decision["name"])
        # Walking PLATFORMS rather than the rows does two things at once: the groups come
        # out in the same order as the grid's columns, and a platform nothing has been
        # decided on is simply absent — ten headings over eight empty spaces would be a
        # page mostly about what has not been decided.
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

    @app.post("/games/<int:game_id>/name")
    def rename_game(game_id):
        name = request.form["name"].strip()
        # Nothing to rename to. Re-rendering restores the name the field started with,
        # the same silent revert an empty add gets.
        if not name:
            return render_template("_catalogue.html", **catalogue())

        connection = db.get_connection()
        try:
            connection.execute(
                "UPDATE games SET name = ? WHERE id = ?", (name, game_id)
            )
        except sqlite3.IntegrityError:
            error = f"{name} is already in the catalogue."
            return render_template("_catalogue.html", error=error, **catalogue())
        connection.commit()
        # The whole list body rather than the renamed row alone: the error a collision
        # raises then has exactly one place to appear, shared with the add form's, and
        # the row lands back in alphabetical order for free.
        return render_template("_catalogue.html", **catalogue())

    @app.post("/games/<int:game_id>/platforms/<platform>")
    def cycle_platform(game_id, platform):
        """Advance one cell through: not playable → playable → the way I'll play it.

        Three states on one control rather than a toggle plus a second affordance beside
        it: the decision is about a platform, so it belongs on the platform, and a 2.75rem
        cell has no room for two targets. The cost is that clearing an availability the
        intent sits on takes two clicks rather than one — paid by the one cell per game
        that carries an intent, which is the cell least likely to be cleared by accident.
        """
        # The platform set is closed. An unrecognised value names nothing, so it is
        # rejected here rather than stored and rendered as a column that cannot exist.
        if platform not in PLATFORMS:
            abort(404)

        connection = db.get_connection()
        # A read first, unlike the two-state toggle this replaces: which way a third
        # state goes cannot be inferred from what a blind delete happened to remove.
        row = connection.execute(
            "SELECT intended FROM game_platforms WHERE game_id = ? AND platform = ?",
            (game_id, platform),
        ).fetchone()

        demoted = 0
        if row is None:
            connection.execute(
                "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
                (game_id, platform),
            )
            available, intended = True, False
        elif not row["intended"]:
            # Deciding on one platform un-decides the previous one and stops there: the
            # game stays playable everywhere it was playable a moment ago. Clearing first
            # is also what keeps the write within the one-intent-per-game index, which
            # would reject the pair existing together even for the length of a statement.
            demoted = connection.execute(
                "UPDATE game_platforms SET intended = 0 WHERE game_id = ? AND intended",
                (game_id,),
            ).rowcount
            connection.execute(
                "UPDATE game_platforms SET intended = 1"
                " WHERE game_id = ? AND platform = ?",
                (game_id, platform),
            )
            available, intended = True, True
        else:
            connection.execute(
                "DELETE FROM game_platforms WHERE game_id = ? AND platform = ?",
                (game_id, platform),
            )
            available, intended = False, False
        connection.commit()

        # A moved intent changed two cells, and the request only asked for one back. The
        # cell that lost it is elsewhere in the row, so the response is widened to the
        # whole list and htmx is told where to put it — rather than leaving a stale second
        # marker on screen claiming a decision the database no longer holds.
        if demoted:
            return render_template("_catalogue.html", **catalogue()), {
                "HX-Retarget": "#catalogue",
                "HX-Reswap": "innerHTML",
            }
        # The cell's appearance is derived from what was just persisted, never assumed,
        # so the interface cannot show a state that was never stored.
        return render_template(
            "_cell.html",
            game_id=game_id,
            platform=platform,
            available=available,
            intended=intended,
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
        """Everything the grid draws: the games, which cells are set, and which is meant."""
        connection = db.get_connection()
        games = connection.execute(
            "SELECT id, name FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()
        # A set of the availabilities that exist. The grid asks about every game against
        # every platform, so membership of one set beats a query per cell.
        availability = set()
        # The one intended platform per game, by game. A game absent from it is a game
        # not yet decided on, which is most of them and the state every game starts in.
        # Both come off the same read: an intent is an availability wearing a flag, so
        # asking for them separately would be reading the same rows twice.
        intents = {}
        for row in connection.execute(
            "SELECT game_id, platform, intended FROM game_platforms"
        ):
            availability.add((row["game_id"], row["platform"]))
            if row["intended"]:
                intents[row["game_id"]] = row["platform"]
        return {"games": games, "availability": availability, "intents": intents}

    return app
