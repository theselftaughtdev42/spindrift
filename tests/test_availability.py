"""Tapping a platform cell: availability, intent, and what a tap refuses (stories 24-30)."""

import re

from tests.conftest import HTMX, add_game, row


def cell(body, game, platform):
    """One game's cell for one platform, as the page writes the button."""
    match = re.search(
        rf'<button[^>]*id="cell-{game}-{re.escape(platform.replace(" ", "-"))}"[^>]*>',
        body,
    )
    assert match, f"no {platform} cell for game {game}"
    return match[0]


def test_one_tap_makes_the_game_available_on_that_platform(client):
    game = add_game(client, "Hades")

    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)

    assert 'aria-pressed="true"' in cell(
        client.get("/").get_data(as_text=True), game, "Steam"
    )


def test_a_second_tap_makes_that_platform_the_intent(client):
    game = add_game(client, "Hades")

    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)

    body = client.get("/").get_data(as_text=True)
    assert "data-intended" in cell(body, game, "Steam")
    assert "data-undecided" not in row(body, game)


def test_a_third_tap_clears_the_cell_of_availability_and_intent(client):
    game = add_game(client, "Hades")

    for _ in range(3):
        client.post(f"/games/{game}/platforms/Steam", headers=HTMX)

    body = client.get("/").get_data(as_text=True)
    assert 'aria-pressed="false"' in cell(body, game, "Steam")
    assert "data-intended" not in cell(body, game, "Steam")


def test_deciding_on_one_platform_undecides_the_previous_one(client):
    game = add_game(client, "Hades")
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)

    client.post(f"/games/{game}/platforms/Switch", headers=HTMX)
    client.post(f"/games/{game}/platforms/Switch", headers=HTMX)

    body = client.get("/").get_data(as_text=True)
    assert "data-intended" not in cell(body, game, "Steam")
    assert 'aria-pressed="true"' in cell(body, game, "Steam")
    assert "data-intended" in cell(body, game, "Switch")


def test_tapping_a_cell_answers_with_the_whole_row(client):
    game = add_game(client, "Hades")
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    client.post(f"/games/{game}/platforms/Switch", headers=HTMX)

    body = client.post(
        f"/games/{game}/platforms/Switch", headers=HTMX
    ).get_data(as_text=True)

    assert "data-intended" in cell(body, game, "Switch")
    assert "data-intended" not in cell(body, game, "Steam")


def test_a_platform_spindrift_does_not_have_is_rejected(client):
    game = add_game(client, "Hades")

    response = client.post(f"/games/{game}/platforms/Dreamcast", headers=HTMX)

    assert response.status_code == 404


def test_tapping_a_cell_on_a_deleted_game_is_refused(client):
    game = add_game(client, "Hades")
    client.delete(f"/games/{game}", headers=HTMX)

    refusal = client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    assert refusal.status_code == 404

    # The next game takes the deleted one's id, so an orphaned availability would show here.
    again = add_game(client, "Hades")
    assert again == game
    assert 'aria-pressed="true"' not in cell(
        client.get("/").get_data(as_text=True), again, "Steam"
    )
