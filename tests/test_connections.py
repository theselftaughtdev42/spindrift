"""The connection one request works through.

Its own seam because a connection is invisible over HTTP: a page looks the same whether it
was served through one connection or a fresh one per query. Closing is not here — the
teardown that pops the connection is already proved by every test that opens a catalogue.
"""

from flask import Flask

from spindrift.db import get_connection


def test_one_request_works_through_one_connection(app: Flask):
    """The second caller is handed the connection the first one opened, rather than a second
    connection against the same file."""
    with app.test_request_context():
        assert get_connection() is get_connection()
