"""The validation matrix, calling `parse` directly: an upload per case would bury each rule."""

import json

import pytest

from spindrift.snapshot import UNCHANGED, SnapshotError, parse
from tests.conftest import snapshot_data


def game(**overrides: object) -> dict[str, object]:
    """A game Spindrift accepts. A refusal test changes the one field it is about."""
    return {"name": "Hades", "status": None, "platforms": [], "intended": None} | overrides


def refusal(data: dict[str, object] | bytes) -> str:
    """The message the cataloguer is shown when Spindrift refuses this file."""
    with pytest.raises(SnapshotError) as refused:
        parse(data if isinstance(data, bytes) else json.dumps(data))
    return str(refused.value)


def test_a_valid_snapshot_carries_the_games_and_search_urls_it_was_given():
    snapshot = parse(json.dumps(snapshot_data()))

    assert [(g.name, g.status, g.platforms, g.intended) for g in snapshot.games] == [
        ("Hades", "playing", ["Steam", "Switch"], "Steam")
    ]
    assert [(u.url, u.active) for u in snapshot.search_urls] == [
        ("https://example.com/search?q={}", True)
    ]


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.99"])
def test_a_later_minor_of_the_same_major_is_accepted(version: str):
    assert parse(json.dumps(snapshot_data(spindrift=version))).spindrift == version


def test_a_game_with_no_status_no_platforms_and_no_intent_is_valid():
    snapshot = parse(json.dumps(snapshot_data(games=[game()])))

    assert (snapshot.games[0].status, snapshot.games[0].platforms) == (None, [])
    assert snapshot.games[0].intended is None


def test_an_empty_deployments_snapshot_is_valid():
    snapshot = parse(json.dumps(snapshot_data(games=[], search_urls=[])))

    assert (snapshot.games, snapshot.search_urls) == ([], [])


def test_a_file_that_is_not_json_is_refused_as_not_valid_json():
    assert "isn't valid JSON" in refusal(b"this was never a snapshot")


@pytest.mark.parametrize("document", [b"[1, 2, 3]", b'"1.0"'], ids=["a-list", "a-bare-string"])
def test_a_json_file_that_is_not_an_object_does_not_say_which_format_it_is(document: bytes):
    assert "doesn't say which snapshot format it is" in refusal(document)


def test_a_file_with_no_spindrift_key_is_refused_naming_the_format_this_spindrift_reads():
    message = refusal({"games": [], "search_urls": []})

    assert "doesn't say which snapshot format it is" in message
    assert "reads format 1.x" in message


@pytest.mark.parametrize(
    "version",
    ["one", "1", "1.0.0", 1.0, None],
    ids=["a-word", "no-minor", "three-parts", "a-number", "null"],
)
def test_a_spindrift_value_that_is_not_a_version_string_is_refused(version: str | float | None):
    message = refusal(snapshot_data(spindrift=version))

    assert "doesn't say which snapshot format it is" in message
    assert "reads format 1.x" in message


@pytest.mark.parametrize("version", ["0.9", "2.0"])
def test_a_different_major_is_refused_naming_both_formats(version: str):
    message = refusal(snapshot_data(spindrift=version))

    assert f"is format {version}" in message
    assert "reads format 1.x" in message


def test_a_deeply_nested_json_file_is_refused_as_not_valid_json():
    depth = 50_000  # far past the depth the decoder can recurse to
    assert "isn't valid JSON" in refusal(b"[" * depth + b"]" * depth)


@pytest.mark.parametrize("name", ["", "   "], ids=["blank", "whitespace-only"])
def test_a_blank_game_name_is_refused(name: str):
    assert "a game needs a name" in refusal(snapshot_data(games=[game(name=name)]))


def test_a_game_name_with_surrounding_spaces_is_stripped():
    snapshot = parse(json.dumps(snapshot_data(games=[game(name="  Hades  ")])))

    assert snapshot.games[0].name == "Hades"


def test_a_status_spindrift_does_not_have_is_refused():
    message = refusal(snapshot_data(games=[game(status="beaten")]))

    assert "beaten is not a status Spindrift has" in message


def test_a_platform_spindrift_does_not_have_is_refused():
    message = refusal(snapshot_data(games=[game(platforms=["Dreamcast"])]))

    assert "Dreamcast is not a platform Spindrift has" in message


def test_an_intent_on_a_platform_spindrift_does_not_have_is_refused():
    message = refusal(snapshot_data(games=[game(platforms=["Dreamcast"], intended="Dreamcast")]))

    assert "Dreamcast is not a platform Spindrift has" in message


def test_an_intent_on_a_platform_the_game_is_not_available_on_is_refused():
    message = refusal(
        snapshot_data(games=[game(name="Hades", platforms=["Steam"], intended="Switch")])
    )

    assert "Hades is meant to be played on Switch, which isn't one of its platforms" in message


@pytest.mark.parametrize(
    "games, where, wanted",
    [
        ([game(name=7)], "games › 1 › name", "string"),
        ([game(platforms="Steam")], "games › 1 › platforms", "list"),
        ([game(status=3)], "games › 1 › status", "string"),
        ({"Hades": []}, "games", "list"),
    ],
    ids=[
        "name-as-a-number",
        "platforms-as-a-string",
        "status-as-a-number",
        "games-as-an-object",
    ],
)
def test_a_wrong_type_is_refused_rather_than_coerced(games: object, where: str, wanted: str):
    message = refusal(snapshot_data(games=games))

    assert f"{where}: Input should be a valid {wanted}" in message


@pytest.mark.parametrize("key", ["name", "status", "platforms", "intended"])
def test_a_game_missing_a_required_key_is_refused(key: str):
    spoiled = {field: value for field, value in game().items() if field != key}

    assert f"games › 1 › {key}: Field required" in refusal(snapshot_data(games=[spoiled]))


def test_a_search_url_without_the_placeholder_says_where_the_games_name_goes():
    message = refusal(
        snapshot_data(search_urls=[{"url": "https://example.com/search", "active": True}])
    )

    assert "needs {} in it, where the game's name goes" in message


def test_a_search_url_that_is_not_http_or_https_is_refused():
    message = refusal(
        snapshot_data(search_urls=[{"url": "javascript:search('{}')", "active": True}])
    )

    assert "needs to start with http:// or https://" in message


def test_an_active_search_url_written_as_a_word_is_refused_rather_than_becoming_true():
    message = refusal(
        snapshot_data(search_urls=[{"url": "https://example.com/{}", "active": "no"}])
    )

    assert "search_urls › 1 › active: Input should be a valid boolean" in message


def test_a_search_url_with_surrounding_whitespace_is_stripped():
    data = snapshot_data(search_urls=[{"url": "  https://example.com/{}  ", "active": True}])

    assert parse(json.dumps(data)).search_urls[0].url == "https://example.com/{}"


def test_a_problem_in_the_second_game_is_reported_as_position_two():
    message = refusal(snapshot_data(games=[game(), game(status="beaten")]))

    assert "games › 2 › status: beaten is not a status Spindrift has" in message


def test_one_problem_reports_no_further_problems():
    assert "more problem" not in refusal(snapshot_data(games=[game(status="beaten")]))


def test_a_lone_problem_is_rendered_whole_with_nothing_standing_in_for_the_rest():
    message = refusal(snapshot_data(games=[game(status="beaten")]))

    assert message == (
        "That snapshot can't be imported — games › 1 › status: beaten is not a status"
        f" Spindrift has. {UNCHANGED}"
    )


# `search_url_problem` writes whole sentences, because a typed URL is shown its problem on
# its own, whereas a snapshot's problem is a clause inside a longer sentence.
@pytest.mark.parametrize(
    "url, problem",
    [
        ("https://example.com/search", "That URL needs {} in it, where the game's name goes"),
        ("javascript:search('{}')", "That URL needs to start with http:// or https://"),
    ],
    ids=["no-placeholder", "not-http"],
)
def test_a_problem_that_already_ends_in_a_full_stop_is_not_given_a_second_one(
    url: str, problem: str
):
    message = refusal(snapshot_data(search_urls=[{"url": url, "active": True}]))

    assert message == (
        f"That snapshot can't be imported — search_urls › 1 › url: {problem}. {UNCHANGED}"
    )


def test_two_problems_report_one_more_problem():
    message = refusal(snapshot_data(games=[game(status="beaten"), game(platforms=["Dreamcast"])]))

    assert "(and 1 more problem)" in message


def test_three_problems_report_two_more_problems():
    message = refusal(
        snapshot_data(games=[game(status="beaten"), game(platforms=["Dreamcast"]), game(name=" ")])
    )

    assert "(and 2 more problems)" in message


@pytest.mark.parametrize(
    "data",
    [
        b"this was never a snapshot",
        snapshot_data(spindrift="one"),
        snapshot_data(spindrift="2.0"),
        snapshot_data(games=[game(status="beaten")]),
        snapshot_data(search_urls=[{"url": "https://example.com/", "active": True}]),
    ],
    ids=["not-json", "no-format", "a-different-major", "a-bad-status", "a-bad-search-url"],
)
def test_a_refusal_ends_by_saying_the_data_is_unchanged(data: dict[str, object] | bytes):
    assert refusal(data).endswith(UNCHANGED)
