"""What the by-platform view shows, in what order, and when it shows none (stories 35-39)."""

import re

from tests.conftest import HTMX, Client, add_game, text


def decide(client: Client, game: int, platform: str):
    """Two taps: available there, then the way the game will be played."""
    client.post(f"/games/{game}/platforms/{platform}", headers=HTMX)
    client.post(f"/games/{game}/platforms/{platform}", headers=HTMX)


def plan_row(body: str, name: str) -> str:
    match = re.search(
        rf"<tr[^>]*>(?:(?!<tr).)*?<td>{re.escape(name)}</td>.*?</tr>", body, re.DOTALL
    )
    assert match, f"{name} is not in the by-platform view"
    return match[0]


def test_only_decided_games_are_shown(client: Client):
    decided = add_game(client, "Hades")
    decide(client, decided, "Steam")
    available = add_game(client, "Celeste")
    client.post(f"/games/{available}/platforms/Steam", headers=HTMX)

    body = text(client.get("/by-platform"))

    assert "Hades" in body
    assert "Celeste" not in body


def test_platforms_are_listed_in_the_order_spindrift_lists_them(client: Client):
    for name, platform in [("Hades", "Switch"), ("Celeste", "PS1"), ("Bastion", "Steam")]:
        decide(client, add_game(client, name), platform)

    body = text(client.get("/by-platform"))

    assert (
        body.index('data-platform="Steam"')
        < body.index('data-platform="PS1"')
        < body.index('data-platform="Switch"')
    )


def test_games_on_a_platform_are_ordered_by_name_whatever_the_capitalisation(client: Client):
    for name in ["zelda", "Anno", "braid"]:
        decide(client, add_game(client, name), "Steam")

    body = text(client.get("/by-platform"))

    assert body.index("<td>Anno</td>") < body.index("<td>braid</td>") < body.index("<td>zelda</td>")


def test_platforms_nothing_is_decided_on_are_absent(client: Client):
    decide(client, add_game(client, "Hades"), "Steam")

    body = text(client.get("/by-platform"))

    assert 'data-platform="Steam"' in body
    undecided = ["GoG", "Xbox", "Xbox 360", "Xbox One", "PS1", "PS2", "Switch", "Emulator"]
    for platform in undecided:
        assert f'data-platform="{platform}"' not in body


def test_each_game_shows_its_status_beside_it(client: Client):
    playing = add_game(client, "Hades")
    decide(client, playing, "Steam")
    client.post(f"/games/{playing}/status", data={"status": "playing"}, headers=HTMX)
    decide(client, add_game(client, "Celeste"), "Steam")

    body = text(client.get("/by-platform"))

    assert "Playing" in plan_row(body, "Hades")
    assert "Playing" not in plan_row(body, "Celeste")


def test_an_empty_deployment_is_told_nothing_is_decided_yet(client: Client):
    body = text(client.get("/by-platform"))

    assert "Nothing decided yet" in body
    assert "<table" not in body
