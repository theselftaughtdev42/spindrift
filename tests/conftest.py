"""Fixtures for the suite: one fresh deployment per test, and a valid snapshot to spoil.

Every test gets its own catalogue in a temporary directory, so no test can see another's
games and none can reach the catalogue in the working copy.
"""

import html
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spindrift import create_app
from spindrift.identity import ProxyAuth
from spindrift.snapshot import FORMAT_VERSION

# The framework's own types, named once here so the tests don't name the framework.
type App = FastAPI
type Client = TestClient
type Response = httpx2.Response


def client_for(app: App, headers: dict[str, str] | None = None) -> Client:
    """A client to send requests to `app` with, sending `headers` beneath any a request adds.

    Redirects are handed back rather than followed, so a test sees where it was sent, and an
    error in the app is answered with a 500 as a server would, rather than raised in the test.
    """
    return TestClient(app, headers=headers, follow_redirects=False, raise_server_exceptions=False)


def text(response: Response) -> str:
    """A response's body, decoded."""
    return response.text


def content(response: Response) -> bytes:
    """A response's body, as sent."""
    return response.content


def json_of(response: Response) -> Any:  # noqa: ANN401 - JSON is whatever was sent
    """A response's body, parsed as JSON."""
    return json.loads(content(response))


def content_type(response: Response) -> str:
    """A response's Content-Type header, in full."""
    return response.headers["Content-Type"]


@pytest.fixture
def catalogue_path(tmp_path: Path) -> Path:
    return tmp_path / "catalogue.sqlite3"


@pytest.fixture
def app(catalogue_path: Path) -> App:
    return create_app(catalogue_path)


@pytest.fixture
def client(app: App) -> Client:
    return client_for(app)


# Where the proxy's application hub lives, for the deployments that name one.
HUB = "https://auth.example.com/hub"


@pytest.fixture
def guarded_app(catalogue_path: Path) -> App:
    """A deployment that has been told a proxy stands in front of it."""
    return create_app(catalogue_path, ProxyAuth(hub_url=HUB))


@pytest.fixture
def guarded_client(guarded_app: App) -> Client:
    return client_for(guarded_app)


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


def signed_in(app: App, headers: dict[str, str]) -> Client:
    """A client every request from which comes through the proxy as one cataloguer."""
    return client_for(app, headers)


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
                "wishlisted": [],
            }
        ],
        "search_urls": [{"url": "https://example.com/search?q={}", "active": True}],
        "wishlist": False,
    }
    data.update(overrides)
    return data


def import_snapshot(
    client: Client,
    data: dict[str, object] | bytes,
    confirm: bool = True,
    filename: str = "snapshot.json",
) -> Response:
    """Upload a snapshot the way the settings page does.

    `data` is a dict to serialise, or the bytes of a file that may not be a snapshot at all.
    """
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    fields = {"confirm": "yes"} if confirm else {}
    return upload(client, "/settings/import", fields, {"snapshot": (filename, body)})


def upload(
    client: Client, path: str, fields: dict[str, str], files: dict[str, tuple[str, bytes]]
) -> Response:
    """A multipart form post: `fields` as text, `files` as (filename, bytes) by field name."""
    return client.post(path, data=fields, files=files)


def row(body: str, game: int) -> str:
    """One game's row, as the page opens it — the attributes a cataloguer's page acts on."""
    match = re.search(
        rf'<div\s[^>]*class="row"[^>]*>(?:(?!<div\s[^>]*class="row").)*?id="name-{game}"',
        body,
        re.DOTALL,
    )
    assert match, f"no row for game {game}"
    return match[0].split(">", 1)[0]


def add_game(client: Client, name: str, platforms: Iterable[str] = ()) -> int:
    """A game in the catalogue, and its id."""
    client.post("/games", data={"name": name, "platform": list(platforms)})
    return game_id(client, name)


def game_id(client: Client, name: str) -> int:
    """The id of a named game, read the way the page identifies its rows."""
    body = text(client.get("/"))
    match = re.search(
        rf'id="name-(\d+)"[^>]*value="{re.escape(html.escape(name, quote=True))}"', body
    )
    assert match, f"{name} is not in the catalogue"
    return int(match[1])
