"""Rules for importing a snapshot, at the HTTP seam: stories 60-73."""

import html

import pytest

from spindrift.snapshot import FORMAT_MAJOR
from tests.conftest import add_game, import_snapshot, snapshot_data


KEPT_SEARCH_URL = "https://kept.example/search?q={}"
SNAPSHOT_SEARCH_URL = "https://example.com/search?q={}"

DUPLICATE_NAMES = snapshot_data(
    games=[
        {"name": "Hades", "status": None, "platforms": [], "intended": None},
        {"name": "hades", "status": None, "platforms": [], "intended": None},
    ]
)


def shown(response):
    """The words the cataloguer reads, with the template's escaping undone."""
    return html.unescape(response.get_data(as_text=True))


def existing_data(client):
    add_game(client, "Tunic", ["Switch"])
    client.post("/settings/urls", data={"url": KEPT_SEARCH_URL})


def test_an_imported_snapshot_replaces_the_games_already_here(client):
    add_game(client, "Tunic", ["Switch"])

    import_snapshot(client, snapshot_data())

    catalogue = client.get("/").get_data(as_text=True)
    assert "Tunic" not in catalogue
    assert "Hades" in catalogue


def test_an_imported_snapshot_replaces_the_search_urls_already_here(client):
    client.post("/settings/urls", data={"url": KEPT_SEARCH_URL})

    import_snapshot(client, snapshot_data())

    settings = client.get("/settings").get_data(as_text=True)
    assert KEPT_SEARCH_URL not in settings
    assert SNAPSHOT_SEARCH_URL in settings


def test_an_import_without_the_box_ticked_imports_nothing(client):
    import_snapshot(client, snapshot_data(), confirm=False)

    assert "Hades" not in client.get("/").get_data(as_text=True)


def test_a_stopped_import_says_nothing_was_imported(client):
    response = import_snapshot(client, snapshot_data(), confirm=False)

    assert (
        "Tick the box to confirm an import replaces everything. Nothing was imported."
        in shown(response)
    )


def test_an_import_with_no_file_chosen_is_refused(client):
    response = import_snapshot(client, b"")

    assert "Choose a snapshot file to import. Nothing was imported." in shown(response)


def test_a_file_that_is_not_valid_json_is_refused(client):
    response = import_snapshot(client, b"{ this is not JSON")

    assert (
        "That file isn't a snapshot — it isn't valid JSON. Your data is unchanged."
        in shown(response)
    )


def test_a_file_that_does_not_say_which_format_it_is_is_refused(client):
    data = snapshot_data()
    del data["spindrift"]

    response = import_snapshot(client, data)

    assert (
        "That file doesn't say which snapshot format it is, so it can't be imported."
        f" This Spindrift reads format {FORMAT_MAJOR}.x. Your data is unchanged."
        in shown(response)
    )


def test_a_snapshot_from_a_different_major_format_is_refused(client):
    response = import_snapshot(client, snapshot_data(spindrift="2.0"))

    assert (
        "That snapshot is format 2.0, but this Spindrift reads format"
        f" {FORMAT_MAJOR}.x. Your data is unchanged." in shown(response)
    )


def test_a_snapshot_from_a_later_minor_of_the_same_major_imports(client):
    response = import_snapshot(client, snapshot_data(spindrift=f"{FORMAT_MAJOR}.7"))

    assert response.status_code == 302
    assert "Hades" in client.get("/").get_data(as_text=True)


def test_an_intent_on_a_platform_the_game_is_not_available_on_is_refused(client):
    response = import_snapshot(
        client,
        snapshot_data(
            games=[
                {
                    "name": "Hades",
                    "status": None,
                    "platforms": ["Steam"],
                    "intended": "Switch",
                }
            ]
        ),
    )

    assert (
        "games › 1: Hades is meant to be played on Switch, which isn't one of its"
        " platforms" in shown(response)
    )


def test_a_value_of_the_wrong_type_is_refused_rather_than_guessed_at(client):
    response = import_snapshot(
        client, snapshot_data(search_urls=[{"url": KEPT_SEARCH_URL, "active": "no"}])
    )

    assert "search_urls › 1 › active: Input should be a valid boolean" in shown(response)
    assert KEPT_SEARCH_URL not in client.get("/settings").get_data(as_text=True)


def test_a_refusal_names_the_first_problem_and_how_many_others(client):
    response = import_snapshot(
        client,
        snapshot_data(
            games=[
                {
                    "name": "Hades",
                    "status": "playing",
                    "platforms": ["Steam"],
                    "intended": "Steam",
                },
                {
                    "name": "Tunic",
                    "status": "someday",
                    "platforms": ["Switch"],
                    "intended": None,
                },
                {
                    "name": "Celeste",
                    "status": None,
                    "platforms": ["Dreamcast"],
                    "intended": None,
                },
                {
                    "name": "Braid",
                    "status": None,
                    "platforms": ["Steam"],
                    "intended": "Dreamcast",
                },
            ]
        ),
    )

    assert (
        "That snapshot can't be imported — games › 2 › status: someday is not a status"
        " Spindrift has (and 2 more problems). Your data is unchanged."
        in shown(response)
    )


def test_a_snapshot_that_breaks_a_catalogue_rule_is_refused(client):
    response = import_snapshot(client, DUPLICATE_NAMES)

    assert (
        "Import failed — that snapshot breaks one of the catalogue's rules, such as two"
        " games with the same name. Your data is unchanged." in shown(response)
    )


@pytest.mark.parametrize(
    "refused",
    [b"{ this is not JSON", snapshot_data(spindrift="2.0"), DUPLICATE_NAMES],
    ids=["not JSON", "another format", "a broken catalogue rule"],
)
def test_a_refused_import_deletes_nothing(client, refused):
    existing_data(client)

    import_snapshot(client, refused)

    assert "Tunic" in client.get("/").get_data(as_text=True)
    assert KEPT_SEARCH_URL in client.get("/settings").get_data(as_text=True)


def test_a_successful_import_lands_on_the_catalogue_saying_it_worked(client):
    response = import_snapshot(client, snapshot_data())

    assert response.status_code == 302
    assert response.headers["Location"] == "/?finished=imported"
    catalogue = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Snapshot imported" in catalogue
    assert "Hades" in catalogue
