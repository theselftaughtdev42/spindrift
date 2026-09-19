"""How a catalogue is built and upgraded, and the rules it goes on enforcing (stories 77-80)."""

import gc
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from spindrift import create_app
from spindrift.db import MIGRATIONS, connect
from tests.conftest import HTMX, add_game, game_id

# Every open file the process holds, on both this machine and CI.
OPEN_FILES = Path("/dev/fd")


def half_migrated(catalogue_path: Path, versions: int) -> sqlite3.Connection:
    """A catalogue left at an older version, built the way `migrate` builds one."""
    connection = connect(catalogue_path)
    for version, migration in enumerate(MIGRATIONS[:versions], start=1):
        connection.executescript(migration)
        connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    return connection


def catalogue_version(catalogue_path: Path) -> int:
    connection = connect(catalogue_path)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def page(client: FlaskClient) -> str:
    return client.get("/").get_data(as_text=True)


def test_a_new_deployment_builds_its_own_catalogue_on_first_run(catalogue_path: Path):
    assert not catalogue_path.exists()

    client = create_app(catalogue_path).test_client()
    add_game(client, "Hades", ["Steam"])

    assert "Hades" in page(client)


def test_a_game_in_an_older_catalogue_survives_the_upgrade(catalogue_path: Path):
    connection = half_migrated(catalogue_path, 2)
    connection.execute("INSERT INTO games (name) VALUES ('Hades')")
    connection.commit()
    connection.close()

    client = create_app(catalogue_path).test_client()

    assert "Hades" in page(client)


def test_an_upgraded_catalogue_records_what_the_later_migrations_added(catalogue_path: Path):
    connection = half_migrated(catalogue_path, 2)
    connection.execute("INSERT INTO games (name) VALUES ('Hades')")
    connection.commit()
    connection.close()
    client = create_app(catalogue_path).test_client()
    game = game_id(client, "Hades")

    client.post(f"/games/{game}/status", data={"status": "playing"}, headers=HTMX)
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(
        "/settings/urls",
        data={"url": "https://example.com/search?q={}"},
        headers=HTMX,
    )

    body = page(client)
    assert 'data-status="playing"' in body
    assert "data-intended" in body
    assert "example.com" in client.get("/settings").get_data(as_text=True)


def test_starting_twice_over_the_same_catalogue_changes_nothing(catalogue_path: Path):
    first = create_app(catalogue_path).test_client()
    add_game(first, "Hades", ["Steam"])

    second = create_app(catalogue_path).test_client()

    assert "Hades" in page(second)


def test_an_upgraded_catalogue_records_one_version_per_migration(catalogue_path: Path):
    """The version is a count of what has run, not a marker that something did: a release
    that appends a migration expects every deployment to run that one and no other."""
    half_migrated(catalogue_path, 2).close()

    create_app(catalogue_path)

    assert catalogue_version(catalogue_path) == len(MIGRATIONS)


def test_a_second_start_leaves_the_catalogue_version_alone(catalogue_path: Path):
    create_app(catalogue_path)
    after_first = catalogue_version(catalogue_path)

    create_app(catalogue_path)

    assert catalogue_version(catalogue_path) == after_first


# The one place the database is asserted on directly: an index is a promise the app relies
# on, and a migration could quietly drop one without any page looking different.
@pytest.fixture
def catalogue(catalogue_path: Path) -> Iterator[sqlite3.Connection]:
    create_app(catalogue_path)
    connection = connect(catalogue_path)
    yield connection
    connection.close()


def indexes(connection: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }


def test_a_game_name_is_unique_regardless_of_capitalisation(catalogue: sqlite3.Connection):
    assert "games_name_unique" in indexes(catalogue)
    catalogue.execute("INSERT INTO games (name) VALUES ('Hades')")

    with pytest.raises(sqlite3.IntegrityError):
        catalogue.execute("INSERT INTO games (name) VALUES ('hades')")


def test_a_game_has_at_most_one_intent(catalogue: sqlite3.Connection):
    assert "game_platforms_one_intent" in indexes(catalogue)
    catalogue.execute("INSERT INTO games (id, name) VALUES (1, 'Hades')")
    catalogue.execute(
        "INSERT INTO game_platforms (game_id, platform, intended) VALUES (1, 'Steam', 1)"
    )

    with pytest.raises(sqlite3.IntegrityError):
        catalogue.execute(
            "INSERT INTO game_platforms (game_id, platform, intended) VALUES (1, 'Switch', 1)"
        )


def test_a_search_url_is_unique_regardless_of_capitalisation(catalogue: sqlite3.Connection):
    assert "search_urls_url_unique" in indexes(catalogue)
    catalogue.execute("INSERT INTO search_urls (url) VALUES ('https://Example.com/{}')")

    with pytest.raises(sqlite3.IntegrityError):
        catalogue.execute("INSERT INTO search_urls (url) VALUES ('https://example.com/{}')")


def test_at_most_one_search_url_is_active(catalogue: sqlite3.Connection):
    assert "search_urls_one_active" in indexes(catalogue)
    catalogue.execute("INSERT INTO search_urls (url, active) VALUES ('https://one.example/{}', 1)")

    with pytest.raises(sqlite3.IntegrityError):
        catalogue.execute(
            "INSERT INTO search_urls (url, active) VALUES ('https://two.example/{}', 1)"
        )


def test_deleting_a_game_deletes_its_availabilities(catalogue: sqlite3.Connection):
    catalogue.execute("INSERT INTO games (id, name) VALUES (1, 'Hades')")
    catalogue.execute("INSERT INTO game_platforms (game_id, platform) VALUES (1, 'Steam')")

    catalogue.execute("DELETE FROM games WHERE id = 1")

    assert catalogue.execute("SELECT COUNT(*) FROM game_platforms").fetchone()[0] == 0


# Append-only once released: changing this number is the deliberate step in front of
# editing a migration that deployments have already run.
def test_the_catalogue_has_five_migrations():
    assert len(MIGRATIONS) == 5


def test_a_catalogue_that_cannot_be_opened_leaves_no_connection_behind(tmp_path: Path):
    """Opening is lazy, so the failure lands after the connection exists but before anyone
    holds it. Counted as open files, because a leak is only visible as one."""
    catalogue_path = tmp_path / "catalogue.sqlite3"
    catalogue_path.write_bytes(b"this is not a catalogue")
    gc.disable()
    try:
        open_files = len(list(OPEN_FILES.iterdir()))
        for _ in range(50):
            with pytest.raises(sqlite3.DatabaseError):
                connect(catalogue_path)

        assert len(list(OPEN_FILES.iterdir())) == open_files
    finally:
        gc.enable()
