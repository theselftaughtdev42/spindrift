"""The wishlist: a per-cataloguer feature marking availabilities as on a store wishlist."""

import re

from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from tests.conftest import (
    AUTHENTIK,
    HTMX,
    SOMEONE_ELSE,
    add_game,
    import_snapshot,
    signed_in,
    snapshot_data,
)
from tests.test_by_platform import decide, plan_row
from tests.test_export import exported


def turn_on(client: FlaskClient):
    client.post("/settings/wishlist", data={"enabled": "yes"})


def turn_off(client: FlaskClient):
    client.post("/settings/wishlist", data={})


def toggle(client: FlaskClient, game: int, platform: str = "Steam") -> TestResponse:
    return client.post(f"/games/{game}/platforms/{platform}/wishlist", headers=HTMX)


def by_platform(client: FlaskClient) -> str:
    return client.get("/by-platform").get_data(as_text=True)


def wishlisted(body: str, name: str) -> bool:
    match = re.search(r'aria-pressed="true"', plan_row(body, name))
    assert "aria-pressed" in plan_row(body, name), f"{name} has no wishlist toggle"
    return match is not None


def test_the_wishlist_is_off_until_turned_on(client: FlaskClient):
    decide(client, add_game(client, "Hades"), "Steam")

    assert "Wishlisted" not in by_platform(client)
    assert 'name="enabled" value="yes" checked' not in client.get("/settings").get_data(
        as_text=True
    )


def test_turning_it_on_adds_the_column(client: FlaskClient):
    decide(client, add_game(client, "Hades"), "Steam")
    turn_on(client)

    body = by_platform(client)

    assert '<th scope="col">Wishlisted</th>' in body
    assert not wishlisted(body, "Hades")


def test_saving_the_setting_reopens_its_group_saying_what_it_did(client: FlaskClient):
    response = client.post("/settings/wishlist", data={"enabled": "yes"}, follow_redirects=True)

    body = response.get_data(as_text=True)
    assert "Wishlist turned on." in body
    assert 'name="enabled" value="yes" checked' in body


def test_a_toggle_marks_and_unmarks_a_game(client: FlaskClient):
    game = add_game(client, "Hades")
    decide(client, game, "Steam")
    turn_on(client)

    response = toggle(client, game)
    assert 'aria-pressed="true"' in response.get_data(as_text=True)
    assert wishlisted(by_platform(client), "Hades")

    toggle(client, game)
    assert not wishlisted(by_platform(client), "Hades")


def test_a_toggle_without_htmx_goes_back_to_the_page(client: FlaskClient):
    game = add_game(client, "Hades")
    decide(client, game, "Steam")
    turn_on(client)

    response = client.post(f"/games/{game}/platforms/Steam/wishlist")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/by-platform")


def test_turning_it_off_hides_the_marks_but_keeps_them(client: FlaskClient):
    game = add_game(client, "Hades")
    decide(client, game, "Steam")
    turn_on(client)
    toggle(client, game)

    turn_off(client)
    assert "Wishlisted" not in by_platform(client)

    turn_on(client)
    assert wishlisted(by_platform(client), "Hades")


def test_a_toggle_is_refused_while_the_wishlist_is_off(client: FlaskClient):
    game = add_game(client, "Hades")
    decide(client, game, "Steam")

    assert toggle(client, game).status_code == 404


def test_a_toggle_is_refused_where_the_game_is_not_available(client: FlaskClient):
    game = add_game(client, "Hades", ["Steam"])
    turn_on(client)

    assert toggle(client, game, "Switch").status_code == 404
    assert toggle(client, game, "Nowhere").status_code == 404


def test_a_mark_belongs_to_its_platform_not_the_game(client: FlaskClient):
    game = add_game(client, "Hades", ["Steam", "Switch"])
    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    turn_on(client)
    toggle(client, game, "Steam")

    client.post(f"/games/{game}/platforms/Switch", headers=HTMX)
    assert not wishlisted(by_platform(client), "Hades")

    client.post(f"/games/{game}/platforms/Steam", headers=HTMX)
    assert wishlisted(by_platform(client), "Hades")


def test_the_setting_and_marks_are_each_cataloguers_own(guarded_app: Flask):
    tim = signed_in(guarded_app, AUTHENTIK)
    sam = signed_in(guarded_app, SOMEONE_ELSE)
    game = add_game(tim, "Hades")
    decide(tim, game, "Steam")
    turn_on(tim)
    decide(sam, add_game(sam, "Tunic"), "Steam")

    assert "Wishlisted" not in by_platform(sam)
    turn_on(sam)
    assert toggle(sam, game).status_code == 404


def test_an_export_holds_the_marks_and_the_setting(client: FlaskClient):
    game = add_game(client, "Hades", ["Steam", "Switch"])
    turn_on(client)
    toggle(client, game, "Switch")

    snapshot = exported(client)

    assert snapshot["wishlist"] is True
    assert snapshot["games"][0]["wishlisted"] == ["Switch"]


def test_an_import_brings_the_marks_and_the_setting(client: FlaskClient):
    game = {"name": "Hades", "status": None, "platforms": ["Steam"], "intended": "Steam"}
    import_snapshot(client, snapshot_data(games=[{**game, "wishlisted": ["Steam"]}], wishlist=True))

    assert wishlisted(by_platform(client), "Hades")


def test_a_snapshot_from_before_the_wishlist_imports_with_it_off(client: FlaskClient):
    turn_on(client)
    data = snapshot_data(
        spindrift="1.0",
        games=[{"name": "Hades", "status": None, "platforms": ["Steam"], "intended": "Steam"}],
    )
    del data["wishlist"]

    import_snapshot(client, data)

    assert "Hades" in by_platform(client)
    assert "Wishlisted" not in by_platform(client)


def test_a_reset_turns_the_wishlist_off(client: FlaskClient):
    turn_on(client)

    client.post("/settings/reset", data={"confirm": "yes"})

    assert exported(client)["wishlist"] is False
