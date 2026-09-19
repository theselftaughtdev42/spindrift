"""What the by-platform view shows, in what order, and when it shows none (stories 35-39)."""

import re

from flask.testing import FlaskClient

from tests.conftest import HTMX, add_game


def decide(client: FlaskClient, game: int, platform: str):
    """Two taps: available there, then the way the game will be played."""
    client.post(f"/games/{game}/platforms/{platform}", headers=HTMX)
    client.post(f"/games/{game}/platforms/{platform}", headers=HTMX)


def plan_row(body: str, name: str) -> str:
    match = re.search(
        rf"<tr[^>]*>(?:(?!<tr).)*?<td>{re.escape(name)}</td>.*?</tr>", body, re.DOTALL
    )
    assert match, f"{name} is not in the by-platform view"
    return match[0]


def test_only_decided_games_are_shown(client: FlaskClient):
    decided = add_game(client, "Hades")
    decide(client, decided, "Steam")
    available = add_game(client, "Celeste")
    client.post(f"/games/{available}/platforms/Steam", headers=HTMX)

    body = client.get("/by-platform").get_data(as_text=True)

    assert "Hades" in body
    assert "Celeste" not in body


def test_platforms_are_listed_in_the_order_spindrift_lists_them(client: FlaskClient):
    for name, platform in [("Hades", "Switch"), ("Celeste", "PS1"), ("Bastion", "Steam")]:
        decide(client, add_game(client, name), platform)

    body = client.get("/by-platform").get_data(as_text=True)

    assert (
        body.index('data-platform="Steam"')
        < body.index('data-platform="PS1"')
        < body.index('data-platform="Switch"')
    )


def test_games_on_a_platform_are_ordered_by_name_whatever_the_capitalisation(client: FlaskClient):
    for name in ["zelda", "Anno", "braid"]:
        decide(client, add_game(client, name), "Steam")

    body = client.get("/by-platform").get_data(as_text=True)

    assert body.index("<td>Anno</td>") < body.index("<td>braid</td>") < body.index("<td>zelda</td>")


def test_platforms_nothing_is_decided_on_are_absent(client: FlaskClient):
    decide(client, add_game(client, "Hades"), "Steam")

    body = client.get("/by-platform").get_data(as_text=True)

    assert 'data-platform="Steam"' in body
    undecided = ["GoG", "Xbox", "Xbox 360", "Xbox One", "PS1", "PS2", "Switch", "Emulator"]
    for platform in undecided:
        assert f'data-platform="{platform}"' not in body


def test_each_game_shows_its_status_beside_it(client: FlaskClient):
    playing = add_game(client, "Hades")
    decide(client, playing, "Steam")
    client.post(f"/games/{playing}/status", data={"status": "playing"}, headers=HTMX)
    decide(client, add_game(client, "Celeste"), "Steam")

    body = client.get("/by-platform").get_data(as_text=True)

    assert "Playing" in plan_row(body, "Hades")
    assert "Playing" not in plan_row(body, "Celeste")


def test_an_empty_deployment_is_told_nothing_is_decided_yet(client: FlaskClient):
    body = client.get("/by-platform").get_data(as_text=True)

    assert "Nothing decided yet" in body
    assert "<table" not in body
