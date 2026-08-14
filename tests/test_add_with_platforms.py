from tests.matrix_html import add_form, cells, rows

PLATFORMS = ["Steam", "Xbox", "PS1", "PS2", "PS3", "PS4", "Switch", "Emulator"]


def set_platforms(page, game):
    """Which platforms are set for one game, read off the rendered grid."""
    return {
        platform for (row, platform), is_set in cells(page).items() if row == game and is_set
    }


def test_a_game_added_with_platforms_ticked_has_exactly_those_set(client):
    client.post("/games", data={"name": "Hades", "platform": ["Steam", "Switch"]})

    page = client.get("/").get_data(as_text=True)

    assert set_platforms(page, "Hades") == {"Steam", "Switch"}


def test_an_add_naming_an_unrecognised_platform_creates_nothing(client):
    response = client.post("/games", data={"name": "Hades", "platform": ["Dreamcast"]})

    assert response.status_code == 400
    # The game is refused along with the platform: a half-written entry is worse than
    # a refused one, because nothing tells the cataloguer the platform went missing.
    assert "Hades" not in client.get("/").get_data(as_text=True)


def test_a_game_added_with_nothing_ticked_has_no_platforms_set(client):
    # Ticking nothing is a normal case, not an error — and the platforms of the add
    # before it must not carry over onto it.
    client.post("/games", data={"name": "Hades", "platform": ["Steam", "Switch"]})

    client.post("/games", data={"name": "Tunic"})

    page = client.get("/").get_data(as_text=True)
    assert set_platforms(page, "Tunic") == set()
    assert set_platforms(page, "Hades") == {"Steam", "Switch"}


def test_a_duplicate_name_is_refused_without_its_platforms_leaking_onto_the_original(
    client,
):
    client.post("/games", data={"name": "Hades"})

    response = client.post("/games", data={"name": "hades", "platform": ["Steam"]})

    assert "already" in response.get_data(as_text=True).lower()
    assert set_platforms(client.get("/").get_data(as_text=True), "Hades") == set()


def test_the_add_form_is_the_grids_first_row(client):
    client.post("/games", data={"name": "Braid"})
    client.post("/games", data={"name": "Tunic"})

    page = client.get("/").get_data(as_text=True)

    assert rows(page) == ["add", "Braid", "Tunic"]


def test_the_add_form_offers_one_checkbox_per_platform_in_column_order(client):
    page = client.get("/").get_data(as_text=True)

    # Same list, same order as the columns beneath: the checkbox a cataloguer ticks
    # sits under the column it means.
    assert add_form(page).platforms == PLATFORMS


def test_an_empty_name_creates_nothing_even_with_platforms_ticked(client):
    client.post("/games", data={"name": "   ", "platform": ["Steam"]})

    page = client.get("/").get_data(as_text=True)

    assert cells(page) == {}


def test_the_form_comes_back_completely_cleared_after_an_add(client):
    response = client.post(
        "/games", data={"name": "Hades", "platform": ["Steam", "Switch"]}
    )

    form = add_form(response.get_data(as_text=True))
    assert form.name == ""
    # Nothing stays ticked: a leftover tick would attach Hades' platforms to whatever
    # is typed next, and nothing would flag it.
    assert form.checked == set()
    assert form.focused


def test_a_new_game_arrives_in_alphabetical_position_with_its_cells_already_set(client):
    client.post("/games", data={"name": "Braid"})
    client.post("/games", data={"name": "Tunic"})

    response = client.post("/games", data={"name": "Hades", "platform": ["Switch"]})

    fragment = response.get_data(as_text=True)
    assert rows(fragment) == ["add", "Braid", "Hades", "Tunic"]
    assert set_platforms(fragment, "Hades") == {"Switch"}
