"""What a deployment reports about itself: health, version, and revalidated pages."""

import tomllib
from pathlib import Path

from spindrift import create_app


def released_version():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def test_the_health_check_is_green_when_the_catalogue_is_reachable(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_the_health_check_goes_red_when_the_catalogue_stops_being_readable(client, catalogue_path):
    # After creation, so the failure can only come from the check's own read.
    catalogue_path.write_bytes(b"this is not a catalogue")

    assert client.get("/health").status_code != 200


def test_the_version_endpoint_reports_the_running_build_as_plain_text(client):
    response = client.get("/version")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.get_data(as_text=True) == released_version()


def test_the_version_baked_into_an_image_wins_over_the_source_tree(monkeypatch, catalogue_path):
    monkeypatch.setenv("SPINDRIFT_VERSION", "1.2.3-baked")

    client = create_app(catalogue_path).test_client()

    assert client.get("/version").get_data(as_text=True) == "1.2.3-baked"


def test_the_footer_shows_the_version_the_deployment_is_running(monkeypatch, catalogue_path):
    monkeypatch.setenv("SPINDRIFT_VERSION", "1.2.3-baked")

    client = create_app(catalogue_path).test_client()

    assert "1.2.3-baked" in client.get("/").get_data(as_text=True)


def test_the_catalogue_page_is_revalidated_rather_than_served_from_cache(client):
    assert client.get("/").headers["Cache-Control"] == "no-cache"


def test_the_settings_page_is_revalidated_rather_than_served_from_cache(client):
    assert client.get("/settings").headers["Cache-Control"] == "no-cache"


def test_an_exported_snapshot_is_not_asked_to_revalidate(client):
    response = client.get("/settings/export")

    assert "no-cache" not in response.headers.get("Cache-Control", "")
