"""Identity as a label: who the proxy says this is, shown and logged and nothing more.

Nothing in the catalogue belongs to anyone yet, so every test here is about what the app
reads, what it refuses to read, and what it puts on the page.
"""

import logging
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from werkzeug.datastructures import Headers

from spindrift import create_app
from spindrift.identity import Cataloguer, ProxyAuth, identify, resolve_proxy_auth
from tests.conftest import AUTHENTIK, HTMX, HUB


def headers(**overrides: str | None) -> dict[str, str]:
    """What the outpost sends, with a header replaced or, given `None`, left off."""
    sent = dict(AUTHENTIK)
    for header, value in overrides.items():
        header = header.replace("_", "-")
        if value is None:
            sent.pop(header, None)
        else:
            sent[header] = value
    return sent


# Reading the environment


def test_no_proxy_auth_without_the_environment_saying_so(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SPINDRIFT_PROXY_AUTH", raising=False)
    assert resolve_proxy_auth() is None


@pytest.mark.parametrize("setting", ["1", "true", "TRUE", "yes", "on", " on "])
def test_the_environment_can_say_a_proxy_is_there(monkeypatch: pytest.MonkeyPatch, setting: str):
    monkeypatch.setenv("SPINDRIFT_PROXY_AUTH", setting)
    monkeypatch.delenv("SPINDRIFT_AUTH_HUB", raising=False)
    assert resolve_proxy_auth() == ProxyAuth(hub_url=None)


@pytest.mark.parametrize("setting", ["", "0", "false", "no", "off", "maybe"])
def test_anything_else_is_no_proxy_at_all(monkeypatch: pytest.MonkeyPatch, setting: str):
    """Ambiguity has to read as off: a misread here believes headers nobody checked."""
    monkeypatch.setenv("SPINDRIFT_PROXY_AUTH", setting)
    assert resolve_proxy_auth() is None


def test_the_hub_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPINDRIFT_PROXY_AUTH", "1")
    monkeypatch.setenv("SPINDRIFT_AUTH_HUB", HUB)
    assert resolve_proxy_auth() == ProxyAuth(hub_url=HUB)


def test_a_blank_hub_is_no_hub(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPINDRIFT_PROXY_AUTH", "1")
    monkeypatch.setenv("SPINDRIFT_AUTH_HUB", "   ")
    assert resolve_proxy_auth() == ProxyAuth(hub_url=None)


# Reading the headers


def test_the_uid_identifies_and_the_name_is_for_showing():
    assert identify(Headers(AUTHENTIK)) == Cataloguer(uid="6f1c1e2a", name="Tim MacKay")


@pytest.mark.parametrize(
    ("dropped", "expected"),
    [
        (["X-authentik-name"], "tim"),
        (["X-authentik-name", "X-authentik-username"], "tim@example.com"),
        (
            ["X-authentik-name", "X-authentik-username", "X-authentik-email"],
            "6f1c1e2a",
        ),
    ],
)
def test_the_name_falls_back_through_what_the_outpost_maps(dropped: list[str], expected: str):
    """A deployment may map only some of the labels; the uid is always there to stand in."""
    sent = {header: value for header, value in AUTHENTIK.items() if header not in dropped}
    identified = identify(Headers(sent))
    assert identified is not None
    assert identified.name == expected


def test_a_blank_name_is_not_a_name():
    identified = identify(Headers(headers(X_authentik_name="   ")))
    assert identified is not None
    assert identified.name == "tim"


def test_nobody_without_a_uid():
    assert identify(Headers(headers(X_authentik_uid=None))) is None


def test_a_blank_uid_is_nobody():
    assert identify(Headers(headers(X_authentik_uid="  "))) is None


# A deployment with no proxy in front


def test_headers_are_ignored_where_no_proxy_was_promised(client: FlaskClient):
    """The whole security model: an unasked-for header is somebody's claim, not a fact."""
    response = client.get("/", headers=AUTHENTIK)
    assert response.status_code == 200
    assert "Tim MacKay" not in response.get_data(as_text=True)


def test_the_catalogue_still_works_with_nobody_signed_in(client: FlaskClient):
    assert client.post("/games", data={"name": "Hades"}).status_code == 200
    assert "Hades" in client.get("/").get_data(as_text=True)


def test_no_session_script_where_no_session_can_lapse(client: FlaskClient):
    assert "session.js" not in client.get("/").get_data(as_text=True)


# A deployment behind a proxy


def test_the_name_is_shown(guarded_client: FlaskClient):
    body = guarded_client.get("/", headers=AUTHENTIK).get_data(as_text=True)
    assert "Tim MacKay" in body
    assert 'class="whoami"' in body


def test_the_name_links_to_the_hub(guarded_client: FlaskClient):
    body = guarded_client.get("/", headers=AUTHENTIK).get_data(as_text=True)
    assert f'<a class="whoami" href="{HUB}">' in body


def test_without_a_hub_the_name_is_only_a_name(catalogue_path: Path):
    app = create_app(catalogue_path, ProxyAuth(hub_url=None))
    body = app.test_client().get("/", headers=AUTHENTIK).get_data(as_text=True)
    assert '<span class="whoami">' in body
    assert '<a class="whoami"' not in body


def test_the_session_script_is_served_behind_a_proxy(guarded_client: FlaskClient):
    assert "session.js" in guarded_client.get("/", headers=AUTHENTIK).get_data(as_text=True)


def test_the_catalogue_works_the_same_behind_a_proxy(guarded_client: FlaskClient):
    added = guarded_client.post("/games", data={"name": "Hades"}, headers=AUTHENTIK)
    assert added.status_code == 200
    assert "Hades" in guarded_client.get("/", headers=AUTHENTIK).get_data(as_text=True)


# Requests that never passed the proxy


def test_a_request_that_skipped_the_proxy_is_refused(guarded_client: FlaskClient):
    response = guarded_client.get("/")
    assert response.status_code == 401
    assert "didn’t come through it" in response.get_data(as_text=True)


def test_the_refusal_points_at_the_hub(guarded_client: FlaskClient):
    assert HUB in guarded_client.get("/").get_data(as_text=True)


def test_a_change_without_a_proxy_changes_nothing(guarded_client: FlaskClient):
    assert guarded_client.post("/games", data={"name": "Hades"}).status_code == 401
    assert "Hades" not in guarded_client.get("/", headers=AUTHENTIK).get_data(as_text=True)


def test_htmx_is_sent_to_navigate_rather_than_swap(guarded_client: FlaskClient):
    """A sign-in page swapped into a table row would be the last thing the page did."""
    response = guarded_client.post("/games", data={"name": "Hades"}, headers=HTMX)
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/"
    assert response.get_data(as_text=True) == ""


@pytest.mark.parametrize(("path", "expected"), [("/health", "ok"), ("/version", None)])
def test_the_polled_checks_answer_without_identity(
    guarded_client: FlaskClient, path: str, expected: str | None
):
    """The image's own HEALTHCHECK reaches these on localhost, going round the proxy."""
    response = guarded_client.get(path)
    assert response.status_code == 200
    if expected is not None:
        assert response.get_data(as_text=True) == expected


def test_static_files_answer_without_identity(guarded_client: FlaskClient):
    """nginx serves these in deployment; the app answering them differently would surprise."""
    assert guarded_client.get("/static/theme.css").status_code == 200


# What gets logged


def test_a_change_is_logged_with_a_name_against_it(
    guarded_client: FlaskClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger="spindrift"):
        guarded_client.post("/games", data={"name": "Hades"}, headers=AUTHENTIK)
    logged = [record.getMessage() for record in caplog.records]
    assert "POST /games by Tim MacKay (6f1c1e2a)" in logged


def test_reading_the_catalogue_is_not_logged(
    guarded_client: FlaskClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger="spindrift"):
        guarded_client.get("/", headers=AUTHENTIK)
    assert [record for record in caplog.records if "GET" in record.getMessage()] == []


def test_nothing_is_logged_where_there_is_nobody_to_log(
    client: FlaskClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger="spindrift"):
        client.post("/games", data={"name": "Hades"}, headers=AUTHENTIK)
    assert [record for record in caplog.records if "Hades" in str(record.args)] == []
    assert [record for record in caplog.records if "POST" in record.getMessage()] == []


def test_a_deployment_behind_a_proxy_says_so_when_it_starts(
    catalogue_path: Path, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger="spindrift"):
        create_app(catalogue_path, ProxyAuth(hub_url=HUB))
    assert "Identity comes from the proxy in front" in [
        record.getMessage() for record in caplog.records
    ]


def test_an_app_with_no_proxy_is_silent_about_it(
    catalogue_path: Path, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO, logger="spindrift"):
        create_app(catalogue_path)
    assert caplog.records == []
