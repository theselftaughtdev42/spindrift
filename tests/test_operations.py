"""What a deployment reports about itself: health, version, revalidated pages, and the
settings page a refused operation hands back."""

import tomllib
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from spindrift import create_app


def released_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def test_the_health_check_is_green_when_the_catalogue_is_reachable(client: FlaskClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_the_health_check_goes_red_when_the_catalogue_stops_being_readable(
    client: FlaskClient, catalogue_path: Path
):
    # After creation, so the failure can only come from the check's own read.
    catalogue_path.write_bytes(b"this is not a catalogue")

    assert client.get("/health").status_code != 200


def test_the_version_endpoint_reports_the_running_build_as_plain_text(client: FlaskClient):
    response = client.get("/version")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.get_data(as_text=True) == released_version()


def test_the_version_baked_into_an_image_wins_over_the_source_tree(
    monkeypatch: pytest.MonkeyPatch, catalogue_path: Path
):
    monkeypatch.setenv("SPINDRIFT_VERSION", "1.2.3-baked")

    client = create_app(catalogue_path).test_client()

    assert client.get("/version").get_data(as_text=True) == "1.2.3-baked"


def test_the_footer_shows_the_version_the_deployment_is_running(
    monkeypatch: pytest.MonkeyPatch, catalogue_path: Path
):
    monkeypatch.setenv("SPINDRIFT_VERSION", "1.2.3-baked")

    client = create_app(catalogue_path).test_client()

    assert "1.2.3-baked" in client.get("/").get_data(as_text=True)


def test_the_catalogue_page_is_revalidated_rather_than_served_from_cache(client: FlaskClient):
    assert client.get("/").headers["Cache-Control"] == "no-cache"


def test_the_settings_page_is_revalidated_rather_than_served_from_cache(client: FlaskClient):
    assert client.get("/settings").headers["Cache-Control"] == "no-cache"


def test_an_exported_snapshot_is_not_asked_to_revalidate(client: FlaskClient):
    response = client.get("/settings/export")

    assert "no-cache" not in response.headers.get("Cache-Control", "")


def test_a_refused_operation_hands_back_a_settings_page_still_holding_its_search_urls(
    client: FlaskClient,
):
    # Not the host the empty field suggests, which would be in the page either way.
    client.post("/settings/urls", data={"url": "https://protondb.com/search?q={}"})

    response = client.post("/settings/reset", data={})

    body = response.get_data(as_text=True)
    assert "Nothing was deleted." in body
    assert "https://protondb.com/search?q={}" in body


def test_without_javascript_a_refused_search_url_comes_back_with_the_message_and_the_draft(
    client: FlaskClient,
):
    # No HX-Request header, so the whole page has to carry what the group alone would.
    response = client.post("/settings/urls", data={"url": "https://example.com/search"})

    body = response.get_data(as_text=True)
    assert "That URL needs {} in it" in body
    assert 'value="https://example.com/search"' in body
