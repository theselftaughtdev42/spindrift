"""Fixtures for the suite: one fresh deployment per test, and a valid snapshot to spoil.

Every test gets its own catalogue in a temporary directory, so no test can see another's
games and none can reach the catalogue in the working copy.
"""

import html
import io
import json
import re

import pytest

from spindrift import create_app
from spindrift.snapshot import FORMAT_VERSION


@pytest.fixture
def catalogue_path(tmp_path):
    return tmp_path / "catalogue.sqlite3"


@pytest.fixture
def app(catalogue_path):
    return create_app(catalogue_path)


@pytest.fixture
def client(app):
    return app.test_client()


# htmx sends this on every request it makes; its absence is a browser without JavaScript.
HTMX = {"HX-Request": "true"}


def snapshot_data(**overrides):
    """A snapshot this deployment accepts. A refusal test changes the one field it is about."""
    data = {
        "spindrift": FORMAT_VERSION,
        "games": [
            {
                "name": "Hades",
                "status": "playing",
                "platforms": ["Steam", "Switch"],
                "intended": "Steam",
            }
        ],
        "search_urls": [{"url": "https://example.com/search?q={}", "active": True}],
    }
    data.update(overrides)
    return data


def import_snapshot(client, data, confirm=True, filename="snapshot.json"):
    """Upload a snapshot the way the settings page does.

    `data` is a dict to serialise, or the bytes of a file that may not be a snapshot at all.
    """
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    form = {"snapshot": (io.BytesIO(body), filename)}
    if confirm:
        form["confirm"] = "yes"
    return client.post("/settings/import", data=form, content_type="multipart/form-data")


def row(body, game):
    """One game's row, as the page opens it — the attributes a cataloguer's page acts on."""
    match = re.search(
        rf'<div class="row"[^>]*>(?:(?!<div class="row").)*?id="name-{game}"',
        body,
        re.DOTALL,
    )
    assert match, f"no row for game {game}"
    return match[0].split(">", 1)[0]


def add_game(client, name, platforms=()):
    """A game in the catalogue, and its id."""
    client.post("/games", data={"name": name, "platform": list(platforms)})
    return game_id(client, name)


def game_id(client, name):
    """The id of a named game, read the way the page identifies its rows."""
    body = client.get("/").get_data(as_text=True)
    match = re.search(
        rf'id="name-(\d+)"[^>]*value="{re.escape(html.escape(name, quote=True))}"', body
    )
    assert match, f"{name} is not in the catalogue"
    return int(match[1])
