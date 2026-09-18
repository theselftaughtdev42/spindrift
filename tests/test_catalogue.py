"""The catalogue's rules: adding, renaming and deleting games."""

import re

import pytest

from tests.conftest import HTMX, add_game, game_id


def catalogue(client):
    return client.get("/").get_data(as_text=True)


def names(body):
    """The names the catalogue shows, in the order it shows them."""
    return re.findall(r'id="name-\d+"[^>]*value="([^"]*)"', body)


def cell(body, game, platform):
    """The availability button for one game and platform, as it is rendered."""
    identifier = f'cell-{game}-{platform.replace(" ", "-")}'
    match = re.search(rf'<button[^>]*id="{identifier}"[^>]*>', body)
    assert match, f"{platform} is not shown for game {game}"
    return match[0]


def available(body, game, platform):
    return 'aria-pressed="true"' in cell(body, game, platform)


def intended(body, game, platform):
    return "data-intended" in cell(body, game, platform)


def status(body, game):
    """The status shown for a game, or None when none is recorded."""
    control = re.search(rf'<select id="status-{game}".*?</select>', body, re.S)
    assert control, f"game {game} has no status control"
    chosen = re.search(r'<option value="([^"]*)"[^>]*selected', control[0])
    return chosen[1] or None


def test_a_game_added_appears_in_the_catalogue(client):
    response = client.post("/games", data={"name": "Hades"}, headers=HTMX)

    assert response.status_code == 200
    assert names(catalogue(client)) == ["Hades"]


def test_a_game_can_be_added_with_no_platforms(client):
    game = add_game(client, "Hades")

    body = catalogue(client)
    assert not any(available(body, game, platform) for platform in ("Steam", "Switch"))


def test_a_game_added_with_platforms_comes_back_with_those_availabilities(client):
    game = add_game(client, "Hades", ["Steam", "Xbox 360"])

    body = catalogue(client)
    assert available(body, game, "Steam")
    assert available(body, game, "Xbox 360")
    assert not available(body, game, "Switch")


@pytest.mark.parametrize("name", ["", "   "])
def test_a_name_that_is_blank_or_only_spaces_is_refused_quietly(client, name):
    response = client.post("/games", data={"name": name}, headers=HTMX)

    body = response.get_data(as_text=True)
    assert 'class="error"' not in body
    assert "No games yet — add one above." in catalogue(client)


def test_a_name_already_taken_is_refused_with_a_message_naming_it(client):
    add_game(client, "Hades")

    response = client.post("/games", data={"name": "Hades"}, headers=HTMX)

    assert "Hades is already in the catalogue." in response.get_data(as_text=True)


def test_a_name_differing_only_in_capitalisation_is_already_taken(client):
    add_game(client, "Hades")

    response = client.post("/games", data={"name": "HADES"}, headers=HTMX)

    assert "HADES is already in the catalogue." in response.get_data(as_text=True)
    assert names(catalogue(client)) == ["Hades"]


def test_a_refused_duplicate_leaves_the_game_already_there_untouched(client):
    game = add_game(client, "Hades", ["Steam", "Switch"])
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/status", data={"status": "playing"}, headers=HTMX)

    client.post("/games", data={"name": "Hades", "platform": ["Xbox"]}, headers=HTMX)

    body = catalogue(client)
    assert available(body, game, "Steam")
    assert available(body, game, "Switch")
    assert not available(body, game, "Xbox")
    assert intended(body, game, "Steam")
    assert status(body, game) == "playing"


def test_the_catalogue_is_ordered_by_name_regardless_of_capitalisation(client):
    add_game(client, "celeste")
    add_game(client, "Bastion")
    add_game(client, "apex")

    assert names(catalogue(client)) == ["apex", "Bastion", "celeste"]


def test_renaming_a_game_returns_just_that_row(client):
    game = add_game(client, "Hades")
    add_game(client, "Celeste")

    response = client.post(
        f"/games/{game}/name", data={"name": "Hades II"}, headers=HTMX
    )

    body = response.get_data(as_text=True)
    assert names(body) == ["Hades II"]
    assert 'placeholder="Game name"' not in body


def test_a_rename_to_a_blank_name_leaves_the_game_named_as_it_was(client):
    game = add_game(client, "Hades")

    response = client.post(f"/games/{game}/name", data={"name": "   "}, headers=HTMX)

    assert names(response.get_data(as_text=True)) == ["Hades"]
    assert names(catalogue(client)) == ["Hades"]


def test_a_rename_onto_a_name_already_taken_redraws_the_whole_catalogue(client):
    add_game(client, "Hades")
    game = add_game(client, "Celeste")

    response = client.post(f"/games/{game}/name", data={"name": "Hades"}, headers=HTMX)

    assert response.headers["HX-Retarget"] == "#catalogue"
    assert response.headers["HX-Reswap"] == "innerHTML"
    assert "Hades is already in the catalogue." in response.get_data(as_text=True)


def test_a_refused_rename_leaves_the_original_name_intact(client):
    add_game(client, "Hades")
    game = add_game(client, "Celeste")

    client.post(f"/games/{game}/name", data={"name": "Hades"}, headers=HTMX)

    assert names(catalogue(client)) == ["Celeste", "Hades"]


def test_deleting_a_game_removes_it_from_the_catalogue(client):
    game = add_game(client, "Hades")
    add_game(client, "Celeste")

    response = client.delete(f"/games/{game}", headers=HTMX)

    assert names(response.get_data(as_text=True)) == ["Celeste"]
    assert names(catalogue(client)) == ["Celeste"]


def test_a_deleted_games_availabilities_intent_and_status_go_with_it(client):
    game = add_game(client, "Hades", ["Steam", "Switch"])
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/status", data={"status": "playing"}, headers=HTMX)
    client.delete(f"/games/{game}", headers=HTMX)

    add_game(client, "Hades")

    body = catalogue(client)
    again = game_id(client, "Hades")
    assert not any(available(body, again, platform) for platform in ("Steam", "Switch"))
    assert not intended(body, again, "Steam")
    assert status(body, again) is None


def test_deleting_a_game_already_deleted_is_treated_as_success(client):
    game = add_game(client, "Hades")
    client.delete(f"/games/{game}", headers=HTMX)

    response = client.delete(f"/games/{game}", headers=HTMX)

    assert response.status_code == 200


def test_a_platform_spindrift_does_not_have_is_rejected_and_leaves_no_game(client):
    response = client.post(
        "/games", data={"name": "Hades", "platform": ["Dreamcast"]}, headers=HTMX
    )

    assert response.status_code == 400
    assert "No games yet — add one above." in catalogue(client)
