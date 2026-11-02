"""Saving, deleting and activating search URLs, and the three ways a settings action answers."""

import html
import re

from tests.conftest import HTMX, Client, Response, add_game, import_snapshot, snapshot_data, text

SEARCH_URL = "https://example.com/search?q={}"
OTHER_SEARCH_URL = "https://protondb.com/search?q={}"


def save_search_url(client: Client, url: str) -> int:
    """A search URL saved the way the settings page saves one, and its id."""
    client.post("/settings/urls", data={"url": url}, headers=HTMX)
    return search_url_id(client, url)


def search_url_id(client: Client, url: str) -> int:
    body = text(client.get("/settings"))
    match = re.search(
        rf'value="(\d+)"[^>]*>\s*<span class="host">[^<]*</span>'
        rf'\s*<span class="url">{re.escape(url)}</span>',
        body,
    )
    assert match, f"{url} is not saved"
    return int(match[1])


def words(response: Response) -> str:
    """What the cataloguer reads, with the page's escaping undone."""
    return html.unescape(text(response))


def refusal(response: Response) -> str:
    """The whole sentence a refusal is put in, so a test reads what the cataloguer reads.

    Matched on the alert itself rather than searched for in the page, because a message with
    something extra on either end still contains the sentence it was supposed to be.
    """
    match = re.search(r'<p class="error" role="alert">([^<]*)</p>', text(response))
    assert match, "nothing was refused"
    return html.unescape(match[1])


def checked(response: Response) -> list[str]:
    """The values of the radios shown checked; the empty one is the search button off."""
    shown = re.findall(
        r'<input\s[^>]*name="active"[^>]*value="([^"]*)"[^>]*\bchecked',
        text(response),
    )
    return [str(value) for value in shown]


def reopened_groups(response: Response) -> list[str]:
    """The names of the settings groups the page comes back open at."""
    groups = re.findall(
        r'<details([^>]*)>.*?<h2 class="group-name">([^<]+)</h2>',
        text(response),
        re.DOTALL,
    )
    return [name for attributes, name in groups if "open" in attributes]


def test_saving_a_search_url_says_which_host_was_added(client: Client):
    response = client.post("/settings/urls", data={"url": SEARCH_URL}, headers=HTMX)

    assert "example.com added." in words(response)


def test_a_search_url_without_the_placeholder_says_where_the_games_name_goes(client: Client):
    response = client.post(
        "/settings/urls", data={"url": "https://example.com/search"}, headers=HTMX
    )

    assert refusal(response) == "That URL needs {} in it, where the game's name goes."


def test_a_refused_search_url_is_left_in_the_field(client: Client):
    response = client.post(
        "/settings/urls", data={"url": "https://example.com/search"}, headers=HTMX
    )

    assert 'value="https://example.com/search"' in text(response)


def test_a_search_url_that_is_not_http_or_https_is_refused(client: Client):
    response = client.post("/settings/urls", data={"url": "javascript:alert(1){}"}, headers=HTMX)

    assert refusal(response) == "That URL needs to start with http:// or https://."


def test_a_blank_search_url_saves_nothing(client: Client):
    response = client.post("/settings/urls", data={"url": "   "}, headers=HTMX)

    assert response.status_code == 200
    assert "No search URLs yet" in words(client.get("/settings"))


def test_a_search_url_already_saved_is_refused_whatever_its_capitalisation(client: Client):
    save_search_url(client, "https://example.com/search?q={}")

    response = client.post(
        "/settings/urls", data={"url": "https://EXAMPLE.com/Search?q={}"}, headers=HTMX
    )

    assert "That URL is already saved." in words(response)


def test_deleting_a_search_url_says_it_is_gone(client: Client):
    url_id = save_search_url(client, SEARCH_URL)

    response = client.post(f"/settings/urls/{url_id}/delete", headers=HTMX)

    assert "Search URL deleted." in words(response)


def test_making_a_search_url_active_says_which_host_searches_will_use(client: Client):
    url_id = save_search_url(client, "https://www.protondb.com/search?q={}")

    response = client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    assert "Searching with protondb.com." in words(response)


def test_making_a_second_search_url_active_deactivates_the_first(client: Client):
    first = save_search_url(client, SEARCH_URL)
    second = save_search_url(client, OTHER_SEARCH_URL)
    client.post("/settings/active", data={"active": first}, headers=HTMX)

    client.post("/settings/active", data={"active": second}, headers=HTMX)

    assert checked(client.get("/settings")) == [str(second)]


def test_turning_search_off_says_it_is_off(client: Client):
    url_id = save_search_url(client, SEARCH_URL)
    client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    response = client.post("/settings/active", data={"active": ""}, headers=HTMX)

    assert "Search button turned off." in words(response)


def test_activating_a_search_url_another_device_deleted_leaves_the_active_one_alone(
    client: Client,
):
    kept = save_search_url(client, SEARCH_URL)
    doomed = save_search_url(client, OTHER_SEARCH_URL)
    client.post("/settings/active", data={"active": kept}, headers=HTMX)
    client.post(f"/settings/urls/{doomed}/delete", headers=HTMX)

    client.post("/settings/active", data={"active": doomed}, headers=HTMX)

    assert checked(client.get("/settings")) == [str(kept)]


def test_the_catalogue_offers_no_search_control_while_no_search_url_is_active(client: Client):
    add_game(client, "Hollow Knight")

    assert 'class="search"' not in text(client.get("/"))


def test_the_catalogue_offers_a_search_control_once_a_search_url_is_active(client: Client):
    add_game(client, "Hollow Knight")
    url_id = save_search_url(client, SEARCH_URL)

    client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    assert 'class="search"' in text(client.get("/"))


def test_the_search_control_carries_the_games_name_url_encoded(client: Client):
    add_game(client, "Hollow Knight")
    url_id = save_search_url(client, SEARCH_URL)
    client.post("/settings/active", data={"active": url_id}, headers=HTMX)

    body = text(client.get("/"))

    assert "https://example.com/search?q=Hollow%20Knight" in body


def test_a_refused_search_url_reopens_the_settings_page_at_the_search_group(client: Client):
    response = client.post("/settings/urls", data={"url": "https://example.com/search"})

    assert reopened_groups(response) == ["Search URL"]


def test_a_refused_import_reopens_the_settings_page_at_the_snapshot_group(client: Client):
    response = import_snapshot(client, snapshot_data(), confirm=False)

    assert reopened_groups(response) == ["Snapshot"]


def test_a_refused_reset_reopens_the_settings_page_at_the_reset_group(client: Client):
    response = client.post("/settings/reset", data={})

    assert reopened_groups(response) == ["Reset"]


def test_without_javascript_a_saved_search_url_returns_to_the_settings_page(client: Client):
    response = client.post("/settings/urls", data={"url": SEARCH_URL})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")


def test_with_htmx_a_saved_search_url_answers_with_the_search_group_itself(client: Client):
    response = client.post("/settings/urls", data={"url": SEARCH_URL}, headers=HTMX)

    assert response.status_code == 200
    assert 'id="search-urls"' in text(response)
