import sqlite3

from flask import current_app, g

# A migration's position is its version. Append-only once released, never edited in place.
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
    """
    ALTER TABLE game_platforms ADD COLUMN intended INTEGER NOT NULL DEFAULT 0;
    CREATE UNIQUE INDEX game_platforms_one_intent
        ON game_platforms (game_id) WHERE intended;
    """,
    # Nullable: absence is how this schema says nothing has been recorded.
    """
    ALTER TABLE games ADD COLUMN status TEXT;
    """,
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
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_connection():
    if "connection" not in g:
        g.connection = connect(current_app.config["DATABASE_PATH"])
    return g.connection


def close_connection(exception=None):
    connection = g.pop("connection", None)
    if connection is not None:
        connection.close()


def migrate(database_path):
    connection = connect(database_path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        for index, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            connection.executescript(migration)
            connection.execute(f"PRAGMA user_version = {index}")
        connection.commit()
    finally:
        connection.close()
