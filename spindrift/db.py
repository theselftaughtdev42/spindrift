import os
import sqlite3

from flask import current_app, g

# What `sqlite3.connect` will take, and so what every caller here may pass along.
type DatabasePath = str | os.PathLike[str]

# A migration's position is its version. Append-only once released, never edited in place.
MIGRATIONS: list[str] = [
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
    # A catalogue gets an owner (ADR-0003). Everything already here goes to the default
    # owner, row 1, which has no uid until the first cataloguer to sign in adopts it. The
    # owned tables are rebuilt rather than altered, so an owner is required of every row
    # instead of quietly defaulting to whoever row 1 turns out to be. The one-intent index
    # stays as it is: a game has one owner, so one intent per game is already per owner.
    """
    CREATE TABLE cataloguers (
        id INTEGER PRIMARY KEY,
        uid TEXT UNIQUE,
        CHECK (uid IS NOT NULL OR id = 1)
    );
    INSERT INTO cataloguers (id) VALUES (1);

    CREATE TABLE owned_games (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES cataloguers (id),
        name TEXT NOT NULL,
        status TEXT
    );
    INSERT INTO owned_games (id, owner_id, name, status) SELECT id, 1, name, status FROM games;
    DROP TABLE games;
    ALTER TABLE owned_games RENAME TO games;
    CREATE UNIQUE INDEX games_name_unique ON games (owner_id, name COLLATE NOCASE);

    CREATE TABLE owned_search_urls (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES cataloguers (id),
        url TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO owned_search_urls (id, owner_id, url, active)
        SELECT id, 1, url, active FROM search_urls;
    DROP TABLE search_urls;
    ALTER TABLE owned_search_urls RENAME TO search_urls;
    CREATE UNIQUE INDEX search_urls_url_unique ON search_urls (owner_id, url COLLATE NOCASE);
    CREATE UNIQUE INDEX search_urls_one_active ON search_urls (owner_id) WHERE active;
    """,
]


def connect(database_path: DatabasePath) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")  # pragma: no mutate
        connection.execute("PRAGMA busy_timeout = 5000")  # pragma: no mutate
        connection.execute("PRAGMA foreign_keys = ON")  # pragma: no mutate
    except Exception:
        connection.close()
        raise
    return connection


def get_connection() -> sqlite3.Connection:
    # `isinstance` rather than a cast, because `g` hands back `Any` and the caller is owed
    # a connection proved rather than promised.
    connection = g.get("connection")
    if not isinstance(connection, sqlite3.Connection):
        connection = connect(current_app.config["DATABASE_PATH"])
        g.connection = connection
    return connection


def close_connection(exception: BaseException | None = None) -> None:
    connection = g.pop("connection", None)
    if connection is not None:
        connection.close()


def migrate(database_path: DatabasePath) -> None:
    connection = connect(database_path)
    try:
        # Off while migrating, or rebuilding a table other tables refer to would cascade the
        # drop through them. Only takes effect outside a transaction, hence first.
        connection.execute("PRAGMA foreign_keys = OFF")  # pragma: no mutate
        version = connection.execute("PRAGMA user_version").fetchone()[0]  # pragma: no mutate
        for index, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            # One transaction each, version included, so a migration that fails partway
            # leaves the catalogue exactly as the one before it left it.
            connection.executescript(f"BEGIN;\n{migration}\nPRAGMA user_version = {index};")
            connection.commit()
    finally:
        connection.close()
