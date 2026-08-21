import sqlite3

from flask import current_app, g

# Ordered schema ladder. A migration's position is its version: everything above the
# database's stored `user_version` is applied on startup, then the version is bumped.
# Migrations are append-only once released — never edited in place.
MIGRATIONS = [
    """
    CREATE TABLE games (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    );
    CREATE UNIQUE INDEX games_name_unique ON games (name COLLATE NOCASE);
    """,
    """
    CREATE TABLE game_platforms (
        game_id INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
        platform TEXT NOT NULL,
        PRIMARY KEY (game_id, platform)
    );
    """,
    # The intent — "this is the way I mean to play it" — is a flag on an availability
    # rather than a column on the game, and that placement is the whole design. An intent
    # cannot name a platform the game is not playable on, because there is no row to
    # carry the flag; deleting the game or untick-ing the platform takes the intent with
    # it; and the flag is layered over the availabilities rather than replacing them, so
    # deciding costs the other routes nothing. Every game starts undecided.
    #
    # The partial index is what makes "a decision" singular: one intended row per game,
    # enforced where it cannot be forgotten. It is partial rather than a plain unique
    # index over (game_id, intended) because a game has many rows that are *not*
    # intended, and only the intended ones are the ones that must be unique.
    """
    ALTER TABLE game_platforms ADD COLUMN intended INTEGER NOT NULL DEFAULT 0;
    CREATE UNIQUE INDEX game_platforms_one_intent
        ON game_platforms (game_id) WHERE intended;
    """,
    # The outcome — "this is what became of it" — is a column on the game, and that
    # placement is as deliberate as the intent's is above. The argument there was that an
    # intent inherently names a platform, so it belongs on the row that names one. The
    # same argument puts status here: "finished" is a fact about the game, and the intent
    # beside it already records where. On the availability it would make every status
    # change a second platform decision, and would let the two disagree — a game recorded
    # as finished on a platform it was never meant to be played on.
    #
    # Nullable, with no default and no backfill. Absence is how this schema already says
    # "not yet": no availability means not playable, no intent means undecided, and now no
    # status means nothing has been recorded. A `NOT NULL DEFAULT` would say instead that
    # every game already in the catalogue is known to be unstarted, which is not something
    # anyone has told it.
    #
    # The set of values is closed but is not spelled out here as a CHECK: it lives in the
    # statuses module beside the platform list, enforced on the write path exactly the way
    # the platform set is, so there is one place a value is admitted from rather than two
    # that can drift.
    """
    ALTER TABLE games ADD COLUMN status TEXT;
    """,
    # Where the catalogue's search control points, as a list rather than a single value.
    # This replaces a GAME_SEARCH_URL environment variable read once at startup, which got
    # two things wrong at once: changing the destination was a restart, and only one
    # destination could be known at a time. Both are the wrong shape for something switched
    # by mood — Steam while shopping, HowLongToBeat while deciding — rather than by
    # deployment.
    #
    # `active` is a flag on the row, not a pointer stored somewhere else, and that is the
    # same argument the intent flag makes two migrations above. A pointer can name a row
    # that has been deleted; a flag cannot. So deleting the active URL simply leaves
    # nothing active — which is already the state that means "no search button" — and
    # there is no cascade to write and no dangling id to guard.
    #
    # The partial index is what makes "active" singular, on the same principle as
    # game_platforms_one_intent. It is keyed on nothing but the flag itself, because the
    # scope of "at most one" here is the whole table rather than one game's rows.
    #
    # Nothing constrains the URL's shape here. The mandatory `{}` placeholder and the
    # http(s) scheme are enforced on the write path, beside where the platform and status
    # sets are enforced, so there is one place a value is admitted from rather than two
    # that can drift. The uniqueness of the URL is the exception and lives here for the
    # reason games_name_unique does: it is the only constraint the database can hold that
    # a request cannot talk its way around.
    """
    CREATE TABLE search_urls (
        id INTEGER PRIMARY KEY,
        url TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 0
    );
    CREATE UNIQUE INDEX search_urls_url_unique ON search_urls (url COLLATE NOCASE);
    CREATE UNIQUE INDEX search_urls_one_active ON search_urls (active) WHERE active;
    """,
]


def connect(database_path):
    """Open a connection configured for concurrent access from several devices."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_connection():
    """The connection for the current request, opened on first use."""
    if "connection" not in g:
        g.connection = connect(current_app.config["DATABASE_PATH"])
    return g.connection


def close_connection(exception=None):
    connection = g.pop("connection", None)
    if connection is not None:
        connection.close()


def migrate(database_path):
    """Bring the database up to the latest schema version."""
    connection = connect(database_path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        for index, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            connection.executescript(migration)
            connection.execute(f"PRAGMA user_version = {index}")
        connection.commit()
    finally:
        connection.close()
