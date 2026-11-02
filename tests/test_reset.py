"""Rules for resetting a deployment: stories 74-76."""

from tests.conftest import Client, Response, add_game, text

SEARCH_URL = "https://kept.example/search?q={}"


def reset(client: Client, confirm: bool = True) -> Response:
    return client.post("/settings/reset", data={"confirm": "yes"} if confirm else {})


def test_a_reset_without_the_box_ticked_deletes_nothing(client: Client):
    add_game(client, "Hades", ["Steam"])
    client.post("/settings/urls", data={"url": SEARCH_URL})

    reset(client, confirm=False)

    assert "Hades" in text(client.get("/"))
    assert SEARCH_URL in text(client.get("/settings"))


def test_a_stopped_reset_says_nothing_was_deleted(client: Client):
    response = reset(client, confirm=False)

    assert "Tick the box to confirm a reset deletes everything. Nothing was deleted." in text(
        response
    )


def test_a_stopped_reset_reopens_the_reset_group(client: Client):
    response = reset(client, confirm=False)

    assert '<details class="group group--danger" open>' in text(response)


def test_a_confirmed_reset_leaves_an_empty_catalogue(client: Client):
    add_game(client, "Hades", ["Steam"])

    reset(client)

    catalogue = text(client.get("/"))
    assert "Hades" not in catalogue
    assert "No games yet" in catalogue


def test_a_confirmed_reset_leaves_no_search_urls(client: Client):
    client.post("/settings/urls", data={"url": SEARCH_URL})

    reset(client)

    settings = text(client.get("/settings"))
    assert SEARCH_URL not in settings
    assert "No search URLs yet" in settings


def test_a_reset_lands_on_the_catalogue_saying_it_happened(client: Client):
    response = reset(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/?finished=reset"
    assert "Data reset completed" in text(client.get(response.headers["Location"]))
