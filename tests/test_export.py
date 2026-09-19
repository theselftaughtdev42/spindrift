"""Rules for exporting a snapshot: stories 54-59."""

import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from spindrift.snapshot import FORMAT_VERSION
from tests.conftest import add_game, import_snapshot, snapshot_data

SEARCH_URL = "https://example.com/search?q={}"
OTHER_SEARCH_URL = "https://other.example/find?q={}"


def exported(client: FlaskClient) -> dict[str, Any]:
    return json.loads(client.get("/settings/export").get_data())


def search_url_id(client: FlaskClient, url: str) -> int:
    """The id a saved search URL is offered under, read from the radio that chooses it."""
    settings = client.get("/settings").get_data(as_text=True)
    for choice in settings.split('<div class="search-url">')[1:]:
        if f'<span class="url">{url}</span>' in choice:
            offered = re.search(r'value="(\d+)"', choice)
            assert offered, f"{url} is offered without an id"
            return int(offered[1])
    raise AssertionError(f"{url} is not a saved search URL")


def test_an_export_holds_every_game_with_its_availabilities_intent_and_status(client: FlaskClient):
    hades = add_game(client, "Hades", ["Steam", "Switch"])
    client.post(f"/games/{hades}/platforms/Steam")
    client.post(f"/games/{hades}/status", data={"status": "playing"})
    add_game(client, "Tunic", ["Switch"])

    assert exported(client)["games"] == [
        {
            "name": "Hades",
            "status": "playing",
            "platforms": ["Steam", "Switch"],
            "intended": "Steam",
        },
        {"name": "Tunic", "status": None, "platforms": ["Switch"], "intended": None},
    ]


def test_an_export_holds_every_search_url_and_which_one_is_active(client: FlaskClient):
    client.post("/settings/urls", data={"url": SEARCH_URL})
    client.post("/settings/urls", data={"url": OTHER_SEARCH_URL})
    client.post("/settings/active", data={"active": search_url_id(client, OTHER_SEARCH_URL)})

    assert exported(client)["search_urls"] == [
        {"url": SEARCH_URL, "active": False},
        {"url": OTHER_SEARCH_URL, "active": True},
    ]


def test_a_snapshot_declares_which_format_it_is(client: FlaskClient):
    assert exported(client)["spindrift"] == FORMAT_VERSION


def test_exports_of_unchanged_data_are_identical(client: FlaskClient):
    add_game(client, "Hades", ["Steam"])
    client.post("/settings/urls", data={"url": SEARCH_URL})

    assert client.get("/settings/export").get_data() == client.get("/settings/export").get_data()


def test_an_export_is_named_with_todays_date(client: FlaskClient):
    response = client.get("/settings/export")

    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="spindrift-{date.today().isoformat()}.json"'
    )


def test_an_export_is_sent_as_json(client: FlaskClient):
    assert (
        client.get("/settings/export").headers["Content-Type"] == "application/json; charset=utf-8"
    )


def test_an_empty_deployment_exports_an_empty_snapshot(client: FlaskClient):
    snapshot = exported(client)

    assert snapshot["games"] == []
    assert snapshot["search_urls"] == []


def test_a_platform_this_spindrift_no_longer_has_is_left_out_of_an_export(
    client: FlaskClient, catalogue_path: Path
):
    # Decided on the unknown platform: an export carrying that intent would name a platform
    # it had left out of the game's availabilities, which is a snapshot nothing can import.
    import_snapshot(client, snapshot_data())
    connection = sqlite3.connect(catalogue_path)
    with connection:
        connection.execute("UPDATE game_platforms SET intended = 0")
        connection.execute(
            "INSERT INTO game_platforms (game_id, platform, intended)"
            " SELECT id, 'Dreamcast', 1 FROM games WHERE name = 'Hades'"
        )
    connection.close()

    game = exported(client)["games"][0]
    assert game["platforms"] == ["Steam", "Switch"]
    assert game["intended"] is None


def test_an_export_carrying_a_platform_this_spindrift_no_longer_has_imports_back(
    client: FlaskClient, catalogue_path: Path
):
    import_snapshot(client, snapshot_data())
    connection = sqlite3.connect(catalogue_path)
    with connection:
        connection.execute("UPDATE game_platforms SET intended = 0")
        connection.execute(
            "INSERT INTO game_platforms (game_id, platform, intended)"
            " SELECT id, 'Dreamcast', 1 FROM games WHERE name = 'Hades'"
        )
    connection.close()
    snapshot = client.get("/settings/export").get_data()

    assert import_snapshot(client, snapshot).status_code == 302


def test_a_platform_this_spindrift_no_longer_has_does_not_cut_the_export_short(
    client: FlaskClient, catalogue_path: Path
):
    # Only that one availability is left out. Everything recorded after it is still a game's to
    # export, so one unknown platform cannot quietly empty the rest of the catalogue.
    hades = add_game(client, "Hades", ["Steam"])
    connection = sqlite3.connect(catalogue_path)
    with connection:
        connection.execute(
            "INSERT INTO game_platforms (game_id, platform) VALUES (?, 'Dreamcast')", (hades,)
        )
    connection.close()
    add_game(client, "Tunic", ["Switch"])

    assert exported(client)["games"] == [
        {"name": "Hades", "status": None, "platforms": ["Steam"], "intended": None},
        {"name": "Tunic", "status": None, "platforms": ["Switch"], "intended": None},
    ]


def test_an_export_is_indented_so_two_snapshots_can_be_read_and_compared(client: FlaskClient):
    # A snapshot is a file a cataloguer keeps. All on one line, every edit to it reads as the
    # same single change; nested two spaces at a time, a diff points at the game that moved.
    add_game(client, "Hades", ["Steam"])

    body = client.get("/settings/export").get_data(as_text=True)

    depths = {len(line) - len(line.lstrip(" ")) for line in body.splitlines() if line.strip()}
    assert depths == {0, 2, 4, 6, 8}
