"""Rules for resetting a deployment: stories 74-76."""

from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from tests.conftest import add_game

SEARCH_URL = "https://kept.example/search?q={}"


def reset(client: FlaskClient, confirm: bool = True) -> TestResponse:
    return client.post("/settings/reset", data={"confirm": "yes"} if confirm else {})


def test_a_reset_without_the_box_ticked_deletes_nothing(client: FlaskClient):
    add_game(client, "Hades", ["Steam"])
    client.post("/settings/urls", data={"url": SEARCH_URL})

    reset(client, confirm=False)

    assert "Hades" in client.get("/").get_data(as_text=True)
    assert SEARCH_URL in client.get("/settings").get_data(as_text=True)


def test_a_stopped_reset_says_nothing_was_deleted(client: FlaskClient):
    response = reset(client, confirm=False)

    assert (
        "Tick the box to confirm a reset deletes everything. Nothing was deleted."
        in response.get_data(as_text=True)
    )


def test_a_stopped_reset_reopens_the_reset_group(client: FlaskClient):
    response = reset(client, confirm=False)

    assert '<details class="group group--danger" open>' in response.get_data(as_text=True)


def test_a_confirmed_reset_leaves_an_empty_catalogue(client: FlaskClient):
    add_game(client, "Hades", ["Steam"])

    reset(client)

    catalogue = client.get("/").get_data(as_text=True)
    assert "Hades" not in catalogue
    assert "No games yet" in catalogue


def test_a_confirmed_reset_leaves_no_search_urls(client: FlaskClient):
    client.post("/settings/urls", data={"url": SEARCH_URL})

    reset(client)

    settings = client.get("/settings").get_data(as_text=True)
    assert SEARCH_URL not in settings
    assert "No search URLs yet" in settings


def test_a_reset_lands_on_the_catalogue_saying_it_happened(client: FlaskClient):
    response = reset(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/?finished=reset"
    assert "Data reset completed" in client.get(response.headers["Location"]).get_data(as_text=True)
