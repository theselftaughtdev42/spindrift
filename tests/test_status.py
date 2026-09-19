"""What a status on a game does, clears to, and survives (stories 31-34)."""

import re

from tests.conftest import HTMX, add_game, row


def selected_status(body, game):
    """The option one game's status dropdown opens on; the empty string is the blank one."""
    match = re.search(rf'<select id="status-{game}".*?</select>', body, re.DOTALL)
    assert match, f"no status control for game {game}"
    chosen = re.search(r'<option value="([^"]*)"\s*selected>', match[0])
    assert chosen, f"no option is selected for game {game}"
    return chosen[1]


def test_a_status_set_on_a_game_sticks(client):
    game = add_game(client, "Hades")

    client.post(f"/games/{game}/status", data={"status": "playing"}, headers=HTMX)

    body = client.get("/").get_data(as_text=True)
    assert 'data-status="playing"' in row(body, game)
    assert selected_status(body, game) == "playing"


def test_a_status_can_be_cleared_back_to_nothing_recorded(client):
    game = add_game(client, "Hades")
    client.post(f"/games/{game}/status", data={"status": "playing"}, headers=HTMX)

    client.post(f"/games/{game}/status", data={"status": ""}, headers=HTMX)

    body = client.get("/").get_data(as_text=True)
    assert "data-status" not in row(body, game)
    assert selected_status(body, game) == ""


def test_a_status_spindrift_does_not_have_is_rejected(client):
    game = add_game(client, "Hades")

    response = client.post(f"/games/{game}/status", data={"status": "completed"}, headers=HTMX)

    assert response.status_code == 400


def test_a_status_survives_renaming_the_game_and_changing_its_platforms(client):
    game = add_game(client, "Hades", ["Steam"])
    client.post(f"/games/{game}/status", data={"status": "100%"}, headers=HTMX)

    client.post(f"/games/{game}/name", data={"name": "Hades II"}, headers=HTMX)
    client.post(f"/games/{game}/platforms/Switch", headers=HTMX)
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)

    body = client.get("/").get_data(as_text=True)
    assert 'data-status="100%"' in row(body, game)
