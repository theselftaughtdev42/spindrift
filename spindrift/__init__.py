import sqlite3
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

from spindrift import db
from spindrift.platforms import PLATFORMS
from spindrift.statuses import STATUSES

# The placeholder a saved search URL has to contain: the spot the game's name is written
# into. Mandatory rather than appended-when-absent, so a mistyped `{nme}` is refused on
# the spot instead of quietly degrading into a URL with a game's name stuck on the end.
SEARCH_PLACEHOLDER = "{}"

# The only schemes a saved URL may use. The value lands in an `href` on every row of the
# catalogue, which is the sharp reason — `javascript:` there would run on a click — but
# the plain one is that a search destination which is not a web address is not a search
# destination.
SEARCH_SCHEMES = ("http", "https")


def search_host(url):
    """What a saved search URL is called — derived every time, never stored.

    An entry carries no name of its own. The settings page reads this over the address
    itself and the catalogue's button announces it, and because it is computed from the
    URL there is no second field to keep in step: nothing can go on calling an entry
    "Steam" after the address stopped pointing there.

    `www.` comes off because it distinguishes nothing — no two entries differ by it alone
    and mean different sites. The URL itself is the fallback for anything `urlsplit` finds
    no host in, which the write path already refuses; it is here so this has an answer
    rather than a `None` for every caller to handle.
    """
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


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

    # Only the settings page needs this, and it needs it once per row; the catalogue is
    # served the active one ready-made by the context processor below.
    app.jinja_env.globals["search_host"] = search_host

    db.migrate(app.config["DATABASE_PATH"])
    app.teardown_appcontext(db.close_connection)

    # Where the row's search control points. It is rendered from four endpoints, which is
    # the same argument that makes `platforms` and `statuses` globals above — none of them
    # should have to remember to pass this. A context processor rather than a global
    # because the answer comes out of the database and can differ from one request to the
    # next, where those two are fixed for the life of the process.
    #
    # This is what replaced a `GAME_SEARCH_URL` environment variable read once at startup.
    # That made the destination a property of a running server, so changing it was a
    # restart and only one could ever be known — the wrong shape for something switched by
    # mood rather than by deployment. There is no fallback to it and no override by it: the
    # database is the only place this is configured, so there is one answer rather than two
    # that can disagree.
    #
    # One small SELECT per response rather than per row: the whole catalogue renders in a
    # single template context, so the include inside the loop reads what this returned once.
    @app.context_processor
    def active_search_link():
        row = (
            db.get_connection()
            .execute("SELECT url FROM search_urls WHERE active")
            .fetchone()
        )
        # Both `None` when nothing is active, which is what the row partial asks about:
        # no active URL means no search control at all, rather than one pointing nowhere.
        return {
            "active_search_url": row["url"] if row else None,
            "active_search_host": search_host(row["url"]) if row else None,
        }

    # A liveness probe the container's HEALTHCHECK hits. The SELECT is the point: it makes
    # a green check mean the app is up *and* the database is reachable — the failure worth
    # catching when the data lives on a mounted volume that could be absent or locked.
    @app.get("/health")
    def health():
        db.get_connection().execute("SELECT 1")
        return "ok", 200

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

    @app.get("/settings")
    def settings():
        """The catalogue's configuration: where its search control points.

        A page rather than a control in the masthead. The switching this exists for happens
        by mood over a session — a storefront while shopping, a wiki while deciding — not
        game by game, so a configuration widget parked permanently over the grid would be
        answering a question nobody is asking while looking at it.

        No htmx here, and no script at all. The machinery on the catalogue is paid for by a
        problem this page does not have: 116 rows toggled in quick succession, where a
        whole-page rebuild costs flicker, scroll position and the focused control. This is
        five rows touched about as often as a mood changes, so it is plain forms, and the
        layout's script block stays empty exactly as the by-platform page leaves it.
        """
        return render_template("settings.html", **saved_search_urls())

    @app.post("/settings/urls")
    def add_search_url():
        url = request.form["url"].strip()
        # Nothing typed: the page comes back as it was. The same silent revert an empty
        # game name gets, and for the same reason — there is no mistake here to report.
        if not url:
            return redirect(url_for("settings"))
        # Both checks before the write, so a request carrying a bad URL leaves nothing
        # behind at all — the rule the platform and status sets are enforced by.
        if SEARCH_PLACEHOLDER not in url:
            return rejected_search_url(
                url,
                f"That URL needs {SEARCH_PLACEHOLDER} in it, where the game's name goes.",
            )
        if urlsplit(url).scheme not in SEARCH_SCHEMES:
            return rejected_search_url(
                url, "That URL needs to start with http:// or https://."
            )

        connection = db.get_connection()
        try:
            connection.execute("INSERT INTO search_urls (url) VALUES (?)", (url,))
        except sqlite3.IntegrityError:
            # The unique index, reported the way a duplicate game name is: the banner over
            # the list, and the address still in the field to be corrected rather than
            # retyped.
            return rejected_search_url(url, "That URL is already saved.")
        connection.commit()
        # Saved, not selected. Turning the search button on is the one thing this page does
        # that changes the catalogue, so it is asked for by choosing and saving rather than
        # arriving as a side effect of writing down an address to try later.
        return redirect(url_for("settings"))

    @app.post("/settings/urls/<int:url_id>/delete")
    def delete_search_url(url_id):
        connection = db.get_connection()
        # No row check and no confirmation. A URL already gone is the outcome asked for —
        # `delete_game`'s reasoning — and unlike a game there is nothing irreplaceable
        # behind this button: the cost of a misclick is retyping an address.
        #
        # If this was the active one the flag goes with it, leaving nothing active, which
        # is the state that means the catalogue shows no search control. That is why the
        # flag sits on the row: there is no pointer left over to find and clear.
        connection.execute("DELETE FROM search_urls WHERE id = ?", (url_id,))
        connection.commit()
        return redirect(url_for("settings"))

    @app.post("/settings/active")
    def set_active_search_url():
        """Point the catalogue's search control somewhere, or nowhere.

        The empty value is not an id and is not a failure: it is the first radio, and it is
        how the control is turned off. Absence is the off switch here exactly as it is for a
        status or an intent, so there is no second boolean beside the selection that could
        disagree with it about whether the feature is on — and switching off costs the saved
        list nothing.
        """
        active = request.form["active"]
        connection = db.get_connection()
        if active:
            # A page drawn before another device deleted this URL. Clearing the flag and
            # then failing to set it would turn the search control off as the side effect
            # of a request that asked to point it somewhere, so nothing is changed at all
            # and the reload shows what is actually there.
            chosen = connection.execute(
                "SELECT id FROM search_urls WHERE id = ?", (active,)
            ).fetchone()
            if chosen is None:
                return redirect(url_for("settings"))
        # Cleared first, then set, never both at once: the partial index allows one active
        # row in the table and would reject the pair existing together even for the length
        # of a statement. The same two steps deciding on a platform takes, for the same
        # reason.
        connection.execute("UPDATE search_urls SET active = 0 WHERE active")
        if active:
            connection.execute(
                "UPDATE search_urls SET active = 1 WHERE id = ?", (active,)
            )
        connection.commit()
        return redirect(url_for("settings"))

    def rejected_search_url(url, error):
        """The settings page again, carrying the reason and what was typed.

        Rendered rather than redirected to, and the one place this page departs from
        post-then-redirect. Carrying a message through a redirect means either a session —
        which this app does not have, and which would mean a secret to generate, store and
        keep out of git — or putting the message in the address, where it survives a
        bookmark and reappears on a reload. Neither is worth it for one line of text.

        What it costs is that a reload re-submits, which for a URL that was refused means
        being told the same thing a second time. The paths that succeed all redirect, so
        the reload that actually matters — the one after something was written — is the one
        that stays safe.
        """
        return render_template(
            "settings.html", error=error, draft=url, **saved_search_urls()
        )

    def saved_search_urls():
        """The list the settings page draws, oldest first.

        By id rather than by host or by URL: the order a radio group is read in should not
        change under a person because they added an entry, and insertion order is the one
        ordering nothing can rearrange. There are only ever a handful of these.
        """
        connection = db.get_connection()
        return {
            "search_urls": connection.execute(
                "SELECT id, url, active FROM search_urls ORDER BY id"
            ).fetchall()
        }

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
