"""The connection one request works through.

Its own seam because a connection is invisible over HTTP: a page looks the same whether it
was served through one connection or a fresh one per query, and whether that connection was
closed afterwards or left open.
"""

import sqlite3
import threading
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends
from starlette.datastructures import State

from spindrift.db import get_connection
from tests.conftest import App, client_for, text


class _Request:
    """As much of a request as the dependency reads: its app's state, and its own."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.state = State()


@pytest.fixture
def request_(app: App) -> _Request:
    return _Request(app)


@pytest.fixture
def dependency(request_: _Request) -> Iterator[Generator[sqlite3.Connection]]:
    """The dependency as FastAPI drives it: advanced once to open, closed once answered."""
    # A stand-in, not a Starlette request: the dependency reads two attributes of it.
    opened = get_connection(request_)  # ty: ignore[invalid-argument-type]
    yield opened
    opened.close()


def test_the_connection_is_to_the_deployment_s_own_catalogue(
    dependency: Generator[sqlite3.Connection], catalogue_path: Path
):
    database = next(dependency).execute("PRAGMA database_list").fetchone()["file"]

    assert Path(database) == catalogue_path.resolve()


def test_the_connection_is_kept_on_the_request_for_the_page_around_it(
    dependency: Generator[sqlite3.Connection], request_: _Request
):
    connection = next(dependency)

    assert request_.state.connection is connection


def test_the_connection_is_closed_once_the_request_is_answered(
    dependency: Generator[sqlite3.Connection],
):
    connection = next(dependency)

    dependency.close()

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_the_connection_works_from_a_thread_other_than_the_one_that_opened_it(
    dependency: Generator[sqlite3.Connection],
):
    """A request's setup, route and cleanup can each run on a different worker thread."""
    connection = next(dependency)
    failures: list[Exception] = []

    def query():
        try:
            connection.execute("SELECT 1")
        except Exception as error:  # noqa: BLE001 - reported back to the test's own thread
            failures.append(error)

    worker = threading.Thread(target=query)
    worker.start()
    worker.join()

    assert failures == []


def test_one_request_works_through_one_connection(app: App):
    """The second caller is handed the connection the first one opened, rather than a second
    connection against the same file."""

    @app.get("/probe")
    def probe(
        first: Annotated[sqlite3.Connection, Depends(get_connection)],
        second: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> str:
        return str(first is second)

    assert text(client_for(app).get("/probe")) == '"True"'
