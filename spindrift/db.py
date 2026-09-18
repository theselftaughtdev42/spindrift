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
    # The intent is a flag on an availability rather than a column on the game, so it
    # cannot name a platform the game is not playable on and is deleted along with it. The
    # partial index is what makes a decision singular: one intended row per game.
    """
    ALTER TABLE game_platforms ADD COLUMN intended INTEGER NOT NULL DEFAULT 0;
    CREATE UNIQUE INDEX game_platforms_one_intent
        ON game_platforms (game_id) WHERE intended;
    """,
    # The outcome is a column on the game: "finished" is a fact about the game, and the
    # intent beside it already records where. Nullable with no backfill, because absence
    # means nothing has been recorded, which is not the same as not started. The value set
    # is closed on the write path beside the platform list rather than as a CHECK here.
    """
    ALTER TABLE games ADD COLUMN status TEXT;
    """,
    # `active` is a flag on the row rather than a pointer held elsewhere, so deleting the
    # active URL simply leaves nothing active — the state that means no search button — with
    # no dangling id to guard. The partial index makes that singular. The URL's shape is
    # enforced on the write path; only its uniqueness is something a request cannot evade.
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
