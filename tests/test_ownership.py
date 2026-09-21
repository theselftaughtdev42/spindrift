"""A cataloguer owns a catalogue: two on one deployment never see or change each other's (#42).

Every test here drives two cataloguers through the same deployment and reads what each one's
page, settings or export shows, because separation is only real where it is observable.
"""

import html
import json
import re
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from spindrift import create_app
from spindrift.identity import ProxyAuth
from tests.conftest import (
    AUTHENTIK,
    HTMX,
    SOMEONE_ELSE,
    add_game,
    game_id,
    import_snapshot,
    row,
    signed_in,
    snapshot_data,
)

SEARCH_URL = "https://example.com/search?q={}"
OTHER_SEARCH_URL = "https://protondb.com/search?q={}"


@pytest.fixture
def tim(guarded_app: Flask) -> FlaskClient:
    return signed_in(guarded_app, AUTHENTIK)


@pytest.fixture
def sam(guarded_app: Flask) -> FlaskClient:
    return signed_in(guarded_app, SOMEONE_ELSE)


def page(client: FlaskClient, path: str = "/") -> str:
    return client.get(path).get_data(as_text=True)


def exported(client: FlaskClient) -> dict[str, Any]:
    return json.loads(client.get("/settings/export").get_data())


def save_search_url(client: FlaskClient, url: str) -> int:
    """A search URL saved the way the settings page saves one, and its id."""
    client.post("/settings/urls", data={"url": url}, headers=HTMX)
    match = re.search(
        rf'value="(\d+)"[^>]*>\s*<span class="host">[^<]*</span>'
        rf'\s*<span class="url">{re.escape(url)}</span>',
        page(client, "/settings"),
    )
    assert match, f"{url} is not saved"
    return int(match[1])


def activate(client: FlaskClient, url_id: int | str):
    client.post("/settings/active", data={"active": url_id}, headers=HTMX)


def checked(client: FlaskClient) -> list[str]:
    """The values of the radios the settings page shows checked; the empty one is search off."""
    shown = re.findall(
        r'<input\s[^>]*name="active"[^>]*value="([^"]*)"[^>]*\bchecked',
        page(client, "/settings"),
    )
    return [str(value) for value in shown]


def saved(client: FlaskClient) -> list[str]:
    """The search URLs the settings page lists, not the example its empty field suggests."""
    shown = re.findall(r'<span class="url">([^<]*)</span>', page(client, "/settings"))
    return [html.unescape(url) for url in shown]


def decide(client: FlaskClient, game: int, platform: str):
    """Two taps: available there, then the way the game will be played."""
    client.post(f"/games/{game}/platforms/{platform}", headers=HTMX)
    client.post(f"/games/{game}/platforms/{platform}", headers=HTMX)


# Separate catalogues


def test_a_game_one_cataloguer_adds_is_not_in_anothers_catalogue(
    tim: FlaskClient, sam: FlaskClient
):
    add_game(tim, "Hades", ["Steam"])

    assert "Hades" in page(tim)
    assert "Hades" not in page(sam)


def test_a_new_cataloguer_starts_with_an_empty_catalogue(tim: FlaskClient, sam: FlaskClient):
    add_game(tim, "Hades", ["Steam"])

    assert "No games yet" in page(sam)


def test_two_cataloguers_can_each_have_a_game_of_the_same_name(tim: FlaskClient, sam: FlaskClient):
    add_game(tim, "Hades", ["Steam"])

    sam.post("/games", data={"name": "hades", "platform": ["Switch"]})

    assert "already in the catalogue" not in page(sam)
    assert [game["name"] for game in exported(sam)["games"]] == ["hades"]
    assert [game["name"] for game in exported(tim)["games"]] == ["Hades"]


def test_a_game_name_is_still_unique_within_one_catalogue(tim: FlaskClient, sam: FlaskClient):
    add_game(sam, "Hades")
    add_game(tim, "Hades")

    response = tim.post("/games", data={"name": "HADES"})

    assert "HADES is already in the catalogue." in response.get_data(as_text=True)


def test_renaming_to_a_name_in_another_catalogue_is_allowed(tim: FlaskClient, sam: FlaskClient):
    add_game(sam, "Hades")
    game = add_game(tim, "Tunic")

    response = tim.post(f"/games/{game}/name", data={"name": "Hades"}, headers=HTMX)

    assert response.status_code == 200
    assert [entry["name"] for entry in exported(tim)["games"]] == ["Hades"]


# Another cataloguer's game is as good as absent


def test_renaming_another_cataloguers_game_is_not_found(tim: FlaskClient, sam: FlaskClient):
    game = add_game(tim, "Hades")

    response = sam.post(f"/games/{game}/name", data={"name": "Tunic"}, headers=HTMX)

    assert response.status_code == 404
    assert [entry["name"] for entry in exported(tim)["games"]] == ["Hades"]


def test_renaming_another_cataloguers_game_adds_nothing_to_your_own(
    tim: FlaskClient, sam: FlaskClient
):
    game = add_game(tim, "Hades")

    sam.post(f"/games/{game}/name", data={"name": "Tunic"}, headers=HTMX)

    assert exported(sam)["games"] == []


def test_tapping_a_platform_on_another_cataloguers_game_is_not_found(
    tim: FlaskClient, sam: FlaskClient
):
    game = add_game(tim, "Hades", ["Steam"])

    responses = [
        sam.post(f"/games/{game}/platforms/{platform}", headers=HTMX)
        for platform in ["Steam", "Switch"]
    ]

    assert [response.status_code for response in responses] == [404, 404]
    assert exported(tim)["games"][0]["platforms"] == ["Steam"]
    assert exported(tim)["games"][0]["intended"] is None


def test_setting_the_status_of_another_cataloguers_game_is_not_found(
    tim: FlaskClient, sam: FlaskClient
):
    game = add_game(tim, "Hades")

    response = sam.post(f"/games/{game}/status", data={"status": "abandoned"}, headers=HTMX)

    assert response.status_code == 404
    assert 'data-status="abandoned"' not in row(page(tim), game)


def test_deleting_another_cataloguers_game_leaves_it_where_it_was(
    tim: FlaskClient, sam: FlaskClient
):
    game = add_game(tim, "Hades")

    sam.delete(f"/games/{game}", headers=HTMX)

    assert game_id(tim, "Hades") == game


def test_changes_to_your_own_game_leave_a_namesake_in_another_catalogue_alone(
    tim: FlaskClient, sam: FlaskClient
):
    theirs = add_game(sam, "Hades", ["Switch"])
    mine = add_game(tim, "Hades", ["Steam"])
    decide(tim, mine, "Steam")
    tim.post(f"/games/{mine}/status", data={"status": "finished"}, headers=HTMX)

    tim.delete(f"/games/{mine}", headers=HTMX)

    assert game_id(sam, "Hades") == theirs
    assert exported(sam)["games"] == [
        {"name": "Hades", "status": None, "platforms": ["Switch"], "intended": None}
    ]


# Search URLs


def test_a_search_url_one_cataloguer_saves_is_not_in_anothers_settings(
    tim: FlaskClient, sam: FlaskClient
):
    save_search_url(tim, SEARCH_URL)

    assert saved(sam) == []
    assert "No search URLs yet" in page(sam, "/settings")


def test_two_cataloguers_can_each_save_the_same_search_url(tim: FlaskClient, sam: FlaskClient):
    save_search_url(tim, SEARCH_URL)

    response = sam.post("/settings/urls", data={"url": SEARCH_URL.upper()}, headers=HTMX)

    assert "already saved" not in response.get_data(as_text=True)
    assert SEARCH_URL.upper() in saved(sam)


def test_a_search_url_is_still_unique_within_one_catalogue(tim: FlaskClient, sam: FlaskClient):
    save_search_url(sam, SEARCH_URL)
    save_search_url(tim, SEARCH_URL)

    response = tim.post("/settings/urls", data={"url": SEARCH_URL}, headers=HTMX)

    assert "That URL is already saved." in response.get_data(as_text=True)


def test_each_cataloguer_has_their_own_active_search_url(tim: FlaskClient, sam: FlaskClient):
    mine = save_search_url(tim, SEARCH_URL)
    theirs = save_search_url(sam, OTHER_SEARCH_URL)

    activate(tim, mine)
    activate(sam, theirs)

    assert checked(tim) == [str(mine)]
    assert checked(sam) == [str(theirs)]


def test_turning_search_off_leaves_another_cataloguers_on(tim: FlaskClient, sam: FlaskClient):
    mine = save_search_url(tim, SEARCH_URL)
    theirs = save_search_url(sam, OTHER_SEARCH_URL)
    activate(tim, mine)
    activate(sam, theirs)

    activate(tim, "")

    assert checked(sam) == [str(theirs)]


def test_the_search_control_uses_only_your_own_active_search_url(
    tim: FlaskClient, sam: FlaskClient
):
    activate(tim, save_search_url(tim, SEARCH_URL))
    add_game(tim, "Hades")
    add_game(sam, "Hades")

    assert "https://example.com/search?q=Hades" in page(tim)
    assert 'class="search"' not in page(sam)


def test_deleting_another_cataloguers_search_url_leaves_it_saved(
    tim: FlaskClient, sam: FlaskClient
):
    url_id = save_search_url(tim, SEARCH_URL)

    sam.post(f"/settings/urls/{url_id}/delete", headers=HTMX)

    assert SEARCH_URL in saved(tim)


def test_activating_another_cataloguers_search_url_changes_nothing(
    tim: FlaskClient, sam: FlaskClient
):
    """Neither side moves: theirs stays off, and yours stays the one you chose."""
    mine = save_search_url(sam, OTHER_SEARCH_URL)
    activate(sam, mine)
    theirs = save_search_url(tim, SEARCH_URL)

    activate(sam, theirs)

    assert checked(tim) == [""]
    assert checked(sam) == [str(mine)]


# Snapshots and resets


def test_an_export_holds_only_your_own_catalogue(tim: FlaskClient, sam: FlaskClient):
    add_game(tim, "Hades", ["Steam"])
    save_search_url(tim, SEARCH_URL)
    add_game(sam, "Tunic", ["Switch"])
    save_search_url(sam, OTHER_SEARCH_URL)

    snapshot = exported(tim)

    assert [game["name"] for game in snapshot["games"]] == ["Hades"]
    assert [search_url["url"] for search_url in snapshot["search_urls"]] == [SEARCH_URL]


def test_an_export_names_no_owner(tim: FlaskClient):
    """A snapshot is one catalogue, and who imports it decides whose it becomes."""
    add_game(tim, "Hades")

    assert set(exported(tim)) == set(snapshot_data())


def test_an_import_lands_in_the_importers_catalogue(tim: FlaskClient, sam: FlaskClient):
    import_snapshot(tim, snapshot_data())

    assert "Hades" in page(tim)
    assert "Hades" not in page(sam)


def test_an_import_leaves_another_cataloguers_catalogue_alone(tim: FlaskClient, sam: FlaskClient):
    add_game(sam, "Tunic", ["Switch"])
    save_search_url(sam, OTHER_SEARCH_URL)

    import_snapshot(tim, snapshot_data())

    assert "Tunic" in page(sam)
    assert OTHER_SEARCH_URL in saved(sam)


def test_the_same_snapshot_can_be_imported_by_two_cataloguers(tim: FlaskClient, sam: FlaskClient):
    import_snapshot(tim, snapshot_data())

    import_snapshot(sam, snapshot_data())

    assert exported(tim) == exported(sam)
    assert [game["name"] for game in exported(sam)["games"]] == ["Hades"]


def test_an_exported_catalogue_imports_into_another_cataloguers(tim: FlaskClient, sam: FlaskClient):
    game = add_game(tim, "Hades", ["Steam", "Switch"])
    decide(tim, game, "Switch")
    activate(tim, save_search_url(tim, SEARCH_URL))

    import_snapshot(sam, exported(tim))

    assert exported(sam) == exported(tim)


def test_a_reset_empties_only_your_own_catalogue(tim: FlaskClient, sam: FlaskClient):
    add_game(sam, "Tunic", ["Switch"])
    save_search_url(sam, OTHER_SEARCH_URL)
    add_game(tim, "Hades", ["Steam"])

    tim.post("/settings/reset", data={"confirm": "yes"})

    assert "No games yet" in page(tim)
    assert "Tunic" in page(sam)
    assert OTHER_SEARCH_URL in saved(sam)


# The by-platform view


def test_the_by_platform_view_shows_only_your_own_decisions(tim: FlaskClient, sam: FlaskClient):
    decide(tim, add_game(tim, "Hades"), "Steam")
    decide(sam, add_game(sam, "Tunic"), "Switch")

    body = page(tim, "/by-platform")

    assert "Hades" in body
    assert "Tunic" not in body


def test_a_namesakes_status_does_not_reach_your_by_platform_view(
    tim: FlaskClient, sam: FlaskClient
):
    decide(tim, add_game(tim, "Hades"), "Steam")
    theirs = add_game(sam, "Hades")
    decide(sam, theirs, "Steam")
    sam.post(f"/games/{theirs}/status", data={"status": "abandoned"}, headers=HTMX)

    assert 'data-status="abandoned"' not in page(tim, "/by-platform")


# Adopting the catalogue a deployment already had


def test_the_first_cataloguer_to_sign_in_adopts_the_catalogue_already_there(
    catalogue_path: Path,
):
    add_game(create_app(catalogue_path).test_client(), "Hades", ["Steam"])

    guarded = create_app(catalogue_path, ProxyAuth())

    assert "Hades" in page(signed_in(guarded, AUTHENTIK))


def test_the_second_cataloguer_does_not_get_the_catalogue_already_there(
    catalogue_path: Path,
):
    add_game(create_app(catalogue_path).test_client(), "Hades", ["Steam"])
    guarded = create_app(catalogue_path, ProxyAuth())
    page(signed_in(guarded, AUTHENTIK))

    assert "Hades" not in page(signed_in(guarded, SOMEONE_ELSE))


def test_search_urls_already_there_are_adopted_too(catalogue_path: Path):
    before = create_app(catalogue_path).test_client()
    before.post("/settings/urls", data={"url": SEARCH_URL})

    guarded = create_app(catalogue_path, ProxyAuth())

    assert SEARCH_URL in saved(signed_in(guarded, AUTHENTIK))
    assert SEARCH_URL not in saved(signed_in(guarded, SOMEONE_ELSE))


def test_a_returning_cataloguer_gets_the_same_catalogue_after_a_restart(catalogue_path: Path):
    first = create_app(catalogue_path, ProxyAuth())
    add_game(signed_in(first, AUTHENTIK), "Hades")
    add_game(signed_in(first, SOMEONE_ELSE), "Tunic")

    restarted = create_app(catalogue_path, ProxyAuth())

    assert "Hades" in page(signed_in(restarted, AUTHENTIK))
    assert "Tunic" in page(signed_in(restarted, SOMEONE_ELSE))
    assert "Tunic" not in page(signed_in(restarted, AUTHENTIK))


def test_a_restart_does_not_hand_the_adopted_catalogue_to_someone_new(catalogue_path: Path):
    """Adoption happens once, ever: a later first-seen uid is new, not the first."""
    add_game(signed_in(create_app(catalogue_path, ProxyAuth()), AUTHENTIK), "Hades")

    restarted = create_app(catalogue_path, ProxyAuth())

    assert "Hades" not in page(signed_in(restarted, SOMEONE_ELSE))


def test_without_a_proxy_the_deployment_shows_the_adopted_catalogue(catalogue_path: Path):
    """The default owner is whoever adopted it, so dropping the proxy shows their catalogue."""
    guarded = create_app(catalogue_path, ProxyAuth())
    add_game(signed_in(guarded, AUTHENTIK), "Hades")
    add_game(signed_in(guarded, SOMEONE_ELSE), "Tunic")

    body = page(create_app(catalogue_path).test_client())

    assert "Hades" in body
    assert "Tunic" not in body


def test_without_a_proxy_every_device_shares_one_catalogue(client: FlaskClient, app: Flask):
    add_game(client, "Hades")

    assert "Hades" in page(app.test_client())


def test_without_a_proxy_identity_headers_do_not_choose_a_catalogue(app: Flask):
    add_game(signed_in(app, SOMEONE_ELSE), "Hades")

    assert "Hades" in page(signed_in(app, AUTHENTIK))


# Requests that never passed the proxy


def test_a_refused_request_shows_nobodys_search_url(tim: FlaskClient, guarded_client: FlaskClient):
    activate(tim, save_search_url(tim, SEARCH_URL))
    add_game(tim, "Hades")

    response = guarded_client.get("/")

    assert response.status_code == 401
    assert "example.com/search" not in response.get_data(as_text=True)


def test_a_refused_request_adds_nothing_to_anyones_catalogue(
    tim: FlaskClient, guarded_client: FlaskClient
):
    add_game(tim, "Hades")

    guarded_client.post("/games", data={"name": "Tunic"})

    assert [game["name"] for game in exported(tim)["games"]] == ["Hades"]
