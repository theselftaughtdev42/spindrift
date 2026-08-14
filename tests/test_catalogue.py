from spindrift import create_app


def test_added_game_appears_in_the_catalogue(client):
    client.post("/games", data={"name": "Hades"})

    page = client.get("/").get_data(as_text=True)

    assert "Hades" in page


def test_empty_catalogue_explains_itself(client):
    page = client.get("/").get_data(as_text=True)

    assert "No games yet" in page


def test_the_catalogue_survives_a_restart(database_path):
    create_app(database_path).test_client().post("/games", data={"name": "Hades"})

    page = create_app(database_path).test_client().get("/").get_data(as_text=True)

    assert "Hades" in page


def test_games_are_listed_alphabetically_ignoring_case(client):
    for name in ["Tunic", "hades", "Braid"]:
        client.post("/games", data={"name": name})

    page = client.get("/").get_data(as_text=True)

    assert page.index("Braid") < page.index("hades") < page.index("Tunic")


def test_a_new_game_lands_in_its_alphabetical_position_immediately(client):
    client.post("/games", data={"name": "Braid"})
    client.post("/games", data={"name": "Tunic"})

    response = client.post("/games", data={"name": "Hades"}).get_data(as_text=True)

    assert response.index("Braid") < response.index("Hades") < response.index("Tunic")


def test_a_name_already_listed_is_rejected_whatever_its_case(client):
    client.post("/games", data={"name": "Hades"})

    response = client.post("/games", data={"name": "hades"})

    assert "already" in response.get_data(as_text=True).lower()
    assert client.get("/").get_data(as_text=True).lower().count("hades") == 1


def test_surrounding_whitespace_is_stripped_from_a_name(client):
    client.post("/games", data={"name": "  Hades  "})

    page = client.get("/").get_data(as_text=True)

    assert "Hades" in page
    assert "  Hades  " not in page


def test_whitespace_only_name_creates_nothing(client):
    client.post("/games", data={"name": "   "})

    page = client.get("/").get_data(as_text=True)

    assert "No games yet" in page
