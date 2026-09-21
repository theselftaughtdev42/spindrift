"""Fixtures for the suite: one fresh deployment per test, and a valid snapshot to spoil.

Every test gets its own catalogue in a temporary directory, so no test can see another's
games and none can reach the catalogue in the working copy.
"""

import html
import io
import json
import re
from collections.abc import Iterable
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from spindrift import create_app
from spindrift.identity import ProxyAuth
from spindrift.snapshot import FORMAT_VERSION


@pytest.fixture
def catalogue_path(tmp_path: Path) -> Path:
    return tmp_path / "catalogue.sqlite3"


@pytest.fixture
def app(catalogue_path: Path) -> Flask:
    return create_app(catalogue_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


# Where the proxy's application hub lives, for the deployments that name one.
HUB = "https://auth.example.com/hub"


@pytest.fixture
def guarded_app(catalogue_path: Path) -> Flask:
    """A deployment that has been told a proxy stands in front of it."""
    return create_app(catalogue_path, ProxyAuth(hub_url=HUB))


@pytest.fixture
def guarded_client(guarded_app: Flask) -> FlaskClient:
    return guarded_app.test_client()


# htmx sends this on every request it makes; its absence is a browser without JavaScript.
HTMX = {"HX-Request": "true"}

# What Authentik's outpost puts on a request it has let through.
AUTHENTIK = {
    "X-authentik-uid": "6f1c1e2a",
    "X-authentik-name": "Tim MacKay",
    "X-authentik-username": "tim",
    "X-authentik-email": "tim@example.com",
}

# A second cataloguer on the same deployment, with a catalogue of their own.
SOMEONE_ELSE = {
    "X-authentik-uid": "9b04d7c3",
    "X-authentik-name": "Sam Rivera",
}


def signed_in(app: Flask, headers: dict[str, str]) -> FlaskClient:
    """A client every request from which comes through the proxy as one cataloguer."""
    client = app.test_client()
    client.environ_base.update(
        {f"HTTP_{header.upper().replace('-', '_')}": value for header, value in headers.items()}
    )
    return client


def snapshot_data(**overrides: object) -> dict[str, object]:
    """A snapshot this deployment accepts. A refusal test changes the one field it is about."""
    data: dict[str, object] = {
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


def import_snapshot(
    client: FlaskClient,
    data: dict[str, object] | bytes,
    confirm: bool = True,
    filename: str = "snapshot.json",
) -> TestResponse:
    """Upload a snapshot the way the settings page does.

    `data` is a dict to serialise, or the bytes of a file that may not be a snapshot at all.
    """
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    # Annotated, or the confirmation below would not fit beside the file it confirms.
    form: dict[str, object] = {"snapshot": (io.BytesIO(body), filename)}
    if confirm:
        form["confirm"] = "yes"
    return client.post("/settings/import", data=form, content_type="multipart/form-data")


def row(body: str, game: int) -> str:
    """One game's row, as the page opens it — the attributes a cataloguer's page acts on."""
    match = re.search(
        rf'<div\s[^>]*class="row"[^>]*>(?:(?!<div\s[^>]*class="row").)*?id="name-{game}"',
        body,
        re.DOTALL,
    )
    assert match, f"no row for game {game}"
    return match[0].split(">", 1)[0]


def add_game(client: FlaskClient, name: str, platforms: Iterable[str] = ()) -> int:
    """A game in the catalogue, and its id."""
    client.post("/games", data={"name": name, "platform": list(platforms)})
    return game_id(client, name)


def game_id(client: FlaskClient, name: str) -> int:
    """The id of a named game, read the way the page identifies its rows."""
    body = client.get("/").get_data(as_text=True)
    match = re.search(
        rf'id="name-(\d+)"[^>]*value="{re.escape(html.escape(name, quote=True))}"', body
    )
    assert match, f"{name} is not in the catalogue"
    return int(match[1])
