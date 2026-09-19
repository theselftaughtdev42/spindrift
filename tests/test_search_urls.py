"""Saving, deleting and activating search URLs, and the three ways a settings action answers."""

import html
import re

from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from tests.conftest import HTMX, add_game, import_snapshot, snapshot_data

SEARCH_URL = "https://example.com/search?q={}"
OTHER_SEARCH_URL = "https://protondb.com/search?q={}"


def save_search_url(client: FlaskClient, url: str) -> int:
    """A search URL saved the way the settings page saves one, and its id."""
    client.post("/settings/urls", data={"url": url}, headers=HTMX)
    return search_url_id(client, url)


def search_url_id(client: FlaskClient, url: str) -> int:
    body = client.get("/settings").get_data(as_text=True)
    match = re.search(
        rf'value="(\d+)"[^>]*>\s*<span class="host">[^<]*</span>'
        rf'\s*<span class="url">{re.escape(url)}</span>',
        body,
    )
    assert match, f"{url} is not saved"
    return int(match[1])


def words(response: TestResponse) -> str:
    """What the cataloguer reads, with the page's escaping undone."""
    return html.unescape(response.get_data(as_text=True))


def checked(response: TestResponse) -> list[str]:
    """The values of the radios shown checked; the empty one is the search button off."""
    shown = re.findall(
        r'<input type="radio" name="active" value="([^"]*)"\s*checked>',
        response.get_data(as_text=True),
    )
    return [str(value) for value in shown]


def reopened_groups(response: TestResponse) -> list[str]:
    """The names of the settings groups the page comes back open at."""
    groups = re.findall(
        r'<details([^>]*)>.*?<h2 class="group-name">([^<]+)</h2>',
        response.get_data(as_text=True),
        re.DOTALL,
    )
    return [name for attributes, name in groups if "open" in attributes]


def test_saving_a_search_url_says_which_host_was_added(client: FlaskClient):
    response = client.post("/settings/urls", data={"url": SEARCH_URL}, headers=HTMX)

    assert "example.com added." in words(response)


def test_a_search_url_without_the_placeholder_says_where_the_games_name_goes(client: FlaskClient):
    response = client.post(
        "/settings/urls", data={"url": "https://example.com/search"}, headers=HTMX
    )

    assert "That URL needs {} in it, where the game's name goes." in words(response)


def test_a_refused_search_url_is_left_in_the_field(client: FlaskClient):
    response = client.post(
        "/settings/urls", data={"url": "https://example.com/search"}, headers=HTMX
    )

    assert 'value="https://example.com/search"' in response.get_data(as_text=True)


def test_a_search_url_that_is_not_http_or_https_is_refused(client: FlaskClient):
    response = client.post("/settings/urls", data={"url": "javascript:alert(1){}"}, headers=HTMX)

    assert "That URL needs to start with http:// or https://." in words(response)


def test_a_blank_search_url_saves_nothing(client: FlaskClient):
    response = client.post("/settings/urls", data={"url": "   "}, headers=HTMX)

    assert response.status_code == 200
    assert "No search URLs yet" in words(client.get("/settings"))


def test_a_search_url_already_saved_is_refused_whatever_its_capitalisation(client: FlaskClient):
    save_search_url(client, "https://example.com/search?q={}")

    response = client.post(
        "/settings/urls", data={"url": "https://EXAMPLE.com/Search?q={}"}, headers=HTMX
    )

    assert "That URL is already saved." in words(response)


def test_deleting_a_search_url_says_it_is_gone(client: FlaskClient):
    url_id = save_search_url(client, SEARCH_URL)

    response = client.post(f"/settings/urls/{url_id}/delete", headers=HTMX)

    assert "Search URL deleted." in words(response)


def test_making_a_search_url_active_says_which_host_searches_will_use(client: FlaskClient):
    url_id = save_search_url(client, "https://www.protondb.com/search?q={}")

    response = client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    assert "Searching with protondb.com." in words(response)


def test_making_a_second_search_url_active_deactivates_the_first(client: FlaskClient):
    first = save_search_url(client, SEARCH_URL)
    second = save_search_url(client, OTHER_SEARCH_URL)
    client.post("/settings/active", data={"active": first}, headers=HTMX)

    client.post("/settings/active", data={"active": second}, headers=HTMX)

    assert checked(client.get("/settings")) == [str(second)]


def test_turning_search_off_says_it_is_off(client: FlaskClient):
    url_id = save_search_url(client, SEARCH_URL)
    client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    response = client.post("/settings/active", data={"active": ""}, headers=HTMX)

    assert "Search button turned off." in words(response)


def test_activating_a_search_url_another_device_deleted_leaves_the_active_one_alone(
    client: FlaskClient,
):
    kept = save_search_url(client, SEARCH_URL)
    doomed = save_search_url(client, OTHER_SEARCH_URL)
    client.post("/settings/active", data={"active": kept}, headers=HTMX)
    client.post(f"/settings/urls/{doomed}/delete", headers=HTMX)

    client.post("/settings/active", data={"active": doomed}, headers=HTMX)

    assert checked(client.get("/settings")) == [str(kept)]


def test_the_catalogue_offers_no_search_control_while_no_search_url_is_active(client: FlaskClient):
    add_game(client, "Hollow Knight")

    assert 'class="search"' not in client.get("/").get_data(as_text=True)


def test_the_catalogue_offers_a_search_control_once_a_search_url_is_active(client: FlaskClient):
    add_game(client, "Hollow Knight")
    url_id = save_search_url(client, SEARCH_URL)

    client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    assert 'class="search"' in client.get("/").get_data(as_text=True)


def test_the_search_control_carries_the_games_name_url_encoded(client: FlaskClient):
    add_game(client, "Hollow Knight")
    url_id = save_search_url(client, SEARCH_URL)
    client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    body = client.get("/").get_data(as_text=True)

    assert "https://example.com/search?q=Hollow%20Knight" in body


def test_a_refused_search_url_reopens_the_settings_page_at_the_search_group(client: FlaskClient):
    response = client.post("/settings/urls", data={"url": "https://example.com/search"})

    assert reopened_groups(response) == ["Search URL"]


def test_a_refused_import_reopens_the_settings_page_at_the_snapshot_group(client: FlaskClient):
    response = import_snapshot(client, snapshot_data(), confirm=False)

    assert reopened_groups(response) == ["Snapshot"]


def test_a_refused_reset_reopens_the_settings_page_at_the_reset_group(client: FlaskClient):
    response = client.post("/settings/reset", data={})

    assert reopened_groups(response) == ["Reset"]


def test_without_javascript_a_saved_search_url_returns_to_the_settings_page(client: FlaskClient):
    response = client.post("/settings/urls", data={"url": SEARCH_URL})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")


def test_with_htmx_a_saved_search_url_answers_with_the_search_group_itself(client: FlaskClient):
    response = client.post("/settings/urls", data={"url": SEARCH_URL}, headers=HTMX)

    assert response.status_code == 200
    assert 'id="search-urls"' in response.get_data(as_text=True)
