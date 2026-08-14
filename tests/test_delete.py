from tests.matrix_html import deletion, rows, set_platforms, toggle_url

PLATFORMS = ["Steam", "Xbox", "PS1", "PS2", "PS3", "PS4", "Switch", "Emulator"]


def test_deleting_a_game_removes_it_from_the_catalogue(client):
    client.post("/games", data={"name": "Hades"})
    page = client.get("/").get_data(as_text=True)

    client.delete(deletion(page, "Hades").url)

    assert "Hades" not in client.get("/").get_data(as_text=True)


def test_a_deleted_games_platforms_do_not_survive_it(client):
    client.post("/games", data={"name": "Hades", "platform": ["Steam", "Switch"]})
    page = client.get("/").get_data(as_text=True)

    client.delete(deletion(page, "Hades").url)

    # The next game added takes the id the deleted one gave up, so any availability row
    # left behind reappears attached to it. Nothing is ticked for Tunic, so anything set
    # on its row is Hades' data outliving Hades — the orphan made observable.
    client.post("/games", data={"name": "Tunic"})
    assert set_platforms(client.get("/").get_data(as_text=True), "Tunic") == set()


def test_the_games_left_behind_keep_their_names_and_their_platforms(client):
    client.post("/games", data={"name": "Braid", "platform": ["Steam"]})
    client.post("/games", data={"name": "Hades", "platform": ["Switch"]})
    client.post("/games", data={"name": "Tunic", "platform": ["PS4", "Emulator"]})
    page = client.get("/").get_data(as_text=True)

    client.delete(deletion(page, "Hades").url)

    page = client.get("/").get_data(as_text=True)
    assert set_platforms(page, "Braid") == {"Steam"}
    assert set_platforms(page, "Tunic") == {"PS4", "Emulator"}


def test_the_list_comes_back_in_order_with_the_gap_closed(client):
    for name in ["Braid", "hades", "Tunic"]:
        client.post("/games", data={"name": name})
    page = client.get("/").get_data(as_text=True)

    response = client.delete(deletion(page, "hades").url)

    # The response is what the cataloguer is left looking at, so it — not a later page
    # load — has to be the thing that is correctly ordered.
    assert rows(response.get_data(as_text=True)) == ["add", "Braid", "Tunic"]


def test_deleting_the_last_game_leaves_the_empty_catalogue_message(client):
    client.post("/games", data={"name": "Hades"})
    page = client.get("/").get_data(as_text=True)

    response = client.delete(deletion(page, "Hades").url)

    assert "No games yet" in response.get_data(as_text=True)


def test_the_delete_control_asks_before_it_deletes_anything(client):
    client.post("/games", data={"name": "Hades"})

    page = client.get("/").get_data(as_text=True)

    # The dialog itself belongs to the browser and is out of reach from here, so what is
    # checked is that the control carries a question at all, and that the question names
    # the game being destroyed — a confirmation that doesn't say what it is about is a
    # dialog people learn to dismiss without reading.
    confirm = deletion(page, "Hades").confirm
    assert confirm is not None
    assert "Hades" in confirm


def test_the_delete_control_sits_past_the_end_of_the_platform_cells(client):
    client.post("/games", data={"name": "Hades"})

    page = client.get("/").get_data(as_text=True)

    # The one control on the row that destroys data should not be reachable by a thumb
    # aiming at Emulator, so it comes after every toggle rather than among them.
    positions = [page.index(toggle_url(page, "Hades", p)) for p in PLATFORMS]
    assert positions == sorted(positions)
    # Anchored on the attribute: a toggle's URL has the delete URL as its prefix, so
    # looking for the URL alone finds the first toggle instead.
    assert page.index(f'hx-delete="{deletion(page, "Hades").url}"') > max(positions)
