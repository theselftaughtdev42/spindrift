import sqlite3

from spindrift import create_app
from tests.matrix_html import cells, only_cell, toggle_url

PLATFORMS = ["Steam", "Xbox", "PS1", "PS2", "PS3", "PS4", "Switch", "Emulator"]


def test_the_grid_shows_every_platform_as_a_column_in_display_order(client):
    client.post("/games", data={"name": "Hades"})

    page = client.get("/").get_data(as_text=True)

    positions = [page.index(heading) for heading in PLATFORMS]
    assert positions == sorted(positions)


def test_a_game_with_nothing_known_about_it_shows_every_platform_unset(client):
    client.post("/games", data={"name": "Hades"})

    page = client.get("/").get_data(as_text=True)

    assert cells(page) == {("Hades", platform): False for platform in PLATFORMS}


def test_toggling_an_unset_platform_sets_it(client):
    client.post("/games", data={"name": "Hades"})
    page = client.get("/").get_data(as_text=True)

    response = client.post(toggle_url(page, "Hades", "Steam"))

    cell = only_cell(response.get_data(as_text=True))
    assert cell.platform == "Steam"
    assert cell.pressed is True


def test_a_set_platform_is_still_set_on_a_later_request(client):
    client.post("/games", data={"name": "Hades"})
    client.post(toggle_url(client.get("/").get_data(as_text=True), "Hades", "Steam"))

    page = client.get("/").get_data(as_text=True)

    assert cells(page)[("Hades", "Steam")] is True
    assert cells(page)[("Hades", "Switch")] is False


def test_toggling_a_set_platform_unsets_it(client):
    client.post("/games", data={"name": "Hades"})
    url = toggle_url(client.get("/").get_data(as_text=True), "Hades", "Steam")
    client.post(url)

    response = client.post(url)

    assert only_cell(response.get_data(as_text=True)).pressed is False
    page = client.get("/").get_data(as_text=True)
    assert cells(page)[("Hades", "Steam")] is False


def test_a_toggle_naming_an_unrecognised_platform_is_rejected(client):
    client.post("/games", data={"name": "Hades"})
    url = toggle_url(client.get("/").get_data(as_text=True), "Hades", "Steam")

    response = client.post(url.replace("Steam", "Dreamcast"))

    assert response.status_code == 404
    assert "Dreamcast" not in client.get("/").get_data(as_text=True)


def test_one_game_holds_several_platforms_without_disturbing_another(client):
    client.post("/games", data={"name": "Hades"})
    client.post("/games", data={"name": "Tunic"})
    page = client.get("/").get_data(as_text=True)
    client.post(toggle_url(page, "Hades", "Steam"))
    client.post(toggle_url(page, "Hades", "Switch"))

    page = client.get("/").get_data(as_text=True)

    assert {platform for (game, platform), set_ in cells(page).items() if set_} == {
        "Steam",
        "Switch",
    }
    assert not any(set_ for (game, _), set_ in cells(page).items() if game == "Tunic")


def test_a_catalogue_from_before_platforms_survives_the_upgrade(database_path):
    # A database as slice 1 left it: schema version 1, no game_platforms table, and a
    # game the cataloguer typed in by hand and would be furious to lose.
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE UNIQUE INDEX games_name_unique ON games (name COLLATE NOCASE);
        INSERT INTO games (name) VALUES ('Hades');
        PRAGMA user_version = 1;
        """
    )
    connection.commit()
    connection.close()

    client = create_app(database_path).test_client()

    page = client.get("/").get_data(as_text=True)
    assert cells(page) == {("Hades", platform): False for platform in PLATFORMS}
    client.post(toggle_url(page, "Hades", "Steam"))
    assert cells(client.get("/").get_data(as_text=True))[("Hades", "Steam")] is True
