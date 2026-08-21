import os
import sqlite3

from flask import Flask, abort, make_response, render_template, request

from spindrift import db
from spindrift.platforms import PLATFORMS
from spindrift.statuses import STATUSES


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
    # The same, for the status control's options: the row partial is rendered from three
    # different endpoints and none of them should have to remember to pass this.
    app.jinja_env.globals["statuses"] = STATUSES

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
            "SELECT game_platforms.platform, games.name, games.status"
            " FROM game_platforms JOIN games ON games.id = game_platforms.game_id"
            " WHERE game_platforms.intended"
            " ORDER BY games.name COLLATE NOCASE"
        ).fetchall()

        # Rows rather than bare names, now that a game brings its outcome here as well as
        # its name. The page still lists decided games only — a finished one is not dropped
        # from it, for the same reason the catalogue does not hide one: this is a record of
        # what was decided, and something that was played is the strongest case of that.
        games = {}
        for decision in decisions:
            games.setdefault(decision["platform"], []).append(decision)
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
        # Nothing to rename to. The row comes back carrying the name it still has, which
        # is the same silent revert an empty add gets.
        if not name:
            return render_template("_row.html", **game_row(game_id))

        connection = db.get_connection()
        try:
            connection.execute(
                "UPDATE games SET name = ? WHERE id = ?", (name, game_id)
            )
        except sqlite3.IntegrityError:
            # The one outcome of a rename that reaches past the row: the banner lives
            # above the grid, shared with the add form's, so this answer has to be the
            # whole list and has to say so in its headers.
            return retargeted_catalogue(f"{name} is already in the catalogue.")
        connection.commit()
        # One row, like the two endpoints below and unlike the three that change the
        # list's membership. This used to answer with the whole list, which bought the
        # error somewhere to appear and put the row back in alphabetical order for free;
        # what it cost was everything else on the page being rebuilt around a one-word
        # change. That cost stopped being affordable when the field started saving on
        # blur: the entry form is rebuilt with it, and its `autofocus` then pulls the
        # page back to the top of the catalogue on every save. Worse, a rename saved by
        # clicking into the next game's name field would destroy the field just clicked
        # into, half-typed.
        #
        # What it gives up is the re-sort: a renamed game keeps its place until the list
        # is next drawn whole, by an add, a delete or a reload. That is the right trade
        # now rather than a merely acceptable one — a save on every blur that reordered
        # the catalogue would move rows out from under the pointer as a matter of course.
        return render_template("_row.html", **game_row(game_id))

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

        if row is None:
            try:
                connection.execute(
                    "INSERT INTO game_platforms (game_id, platform) VALUES (?, ?)",
                    (game_id, platform),
                )
            except sqlite3.IntegrityError:
                # The foreign key refusing to attach an availability to a game that is not
                # there — which means another device deleted it after this page was drawn.
                # Caught so it comes back as the 404 the other paths give, rather than as a
                # traceback: the same stale-page situation, so the same answer.
                abort(404)
            available, intended = True, False
        elif not row["intended"]:
            # Deciding on one platform un-decides the previous one and stops there: the
            # game stays playable everywhere it was playable a moment ago. Clearing first
            # is also what keeps the write within the one-intent-per-game index, which
            # would reject the pair existing together even for the length of a statement.
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

        # The whole row, always. Deciding on a platform un-decides another, so the click
        # can change two cells — and the cell that lost its marker is always elsewhere in
        # this same row, never outside it. Answering with the row covers both cases in one
        # shape: this used to widen the response to the entire catalogue and tell htmx
        # where to put it with a pair of retarget headers, purely because there was no row
        # partial to return. There is one now, so they are gone.
        #
        # The row is re-read from the database rather than assembled from what this
        # handler just decided, so the interface cannot show a state that was never
        # stored.
        return render_template("_row.html", **game_row(game_id))

    @app.post("/games/<int:game_id>/status")
    def set_status(game_id):
        """Record what became of a game — or clear the record back to nothing.

        One form field carrying the whole answer, rather than a path segment naming a
        status the way the cycle endpoint names a platform: clearing has to be expressible,
        and an empty path segment is not a thing a select can submit.
        """
        status = request.form["status"]
        # The status set is closed for the same reason the platform set is: a value
        # nothing can render is a value the catalogue must not be able to hold. Checked
        # before the write, so a request carrying a bad one changes nothing at all. The
        # empty string is the exception and is not a value — it is how the control says
        # "back to not started", and it is stored as the absence that means exactly that.
        if status and status not in STATUSES:
            abort(400)

        connection = db.get_connection()
        connection.execute(
            "UPDATE games SET status = ? WHERE id = ?", (status or None, game_id)
        )
        connection.commit()
        # One row, because a status change is contained by one: it tints that row's status
        # cell and dims or undims the rest of it, and touches nothing above or below.
        # Measured against the real catalogue, 116 rows render whole in 463 KB and one row
        # in 3.9 KB, so an afternoon of backfilling costs half a megabyte rather than fifty
        # — and, which matters more while doing it, the page does not flicker and the
        # scroll position stays where it was.
        return render_template("_row.html", **game_row(game_id))

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

    def retargeted_catalogue(error):
        """The whole list, answering a request that asked for a single row.

        Only the rename uses this, and only when the name it was given is already taken.
        The response has to carry its own target because it does not match the one the
        request declared: the row asked for a row back, and this is the page-level banner
        plus everything under it.

        The pair of headers is the same pair the cycle endpoint used to need before there
        was a row partial to answer with. There it was papering over a missing shape and
        went as soon as one existed. Here the two shapes are real — a rename either
        changes one row or raises a banner that belongs to the page — so the retarget is
        saying something true about this particular answer.
        """
        response = make_response(
            render_template("_catalogue.html", error=error, **catalogue())
        )
        response.headers["HX-Retarget"] = "#catalogue"
        response.headers["HX-Reswap"] = "innerHTML"
        return response

    def catalogue():
        """Everything the grid draws: the games, which cells are set, and which is meant."""
        connection = db.get_connection()
        games = connection.execute(
            "SELECT id, name, status FROM games ORDER BY name COLLATE NOCASE"
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

    def game_row(game_id):
        """The same thing `catalogue()` returns, narrowed to one game.

        The row partial is rendered from inside a whole-catalogue render and on its own as
        a mutation's response, and it must draw the same either way — so it is given the
        same names, holding the same shapes, from both directions. Only the query is
        narrower: one game and its own availabilities rather than every game and all of
        them.

        Which is why a missing game is a 404 rather than a `None` handed to the template:
        `catalogue()` cannot produce a row without a game, so neither may this, and the
        shapes stay the same in both directions. It happens when a second device deleted
        the game after this page was drawn — `delete_game` chose deliberately not to raise
        the failure banner in that situation, because the deletion had in fact happened;
        here the opposite is true. The change being asked for genuinely was not saved, and
        the banner saying so is the honest answer.
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
