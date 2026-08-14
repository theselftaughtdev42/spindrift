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
