"""What makes Spindrift installable: a manifest, icons and a service worker that caches nothing."""

import json
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from spindrift import create_app
from spindrift.pwa import TOKENS_PATH
from spindrift.static_manifest import MANIFEST_PATH

TOKENS = json.loads(TOKENS_PATH.read_text())


def manifest(client: FlaskClient) -> dict[str, Any]:
    """The manifest as the browser reads it. `Any`, because JSON is only shaped by the test."""
    document: dict[str, Any] = json.loads(client.get("/manifest.webmanifest").get_data())
    return document


def test_every_page_links_the_manifest_with_credentials(client: FlaskClient):
    body = client.get("/").get_data(as_text=True)

    assert (
        '<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials" />' in body
    )


def test_the_manifest_is_served_as_one(client: FlaskClient):
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.content_type == "application/manifest+json"


def test_the_manifest_opens_the_catalogue_standalone(client: FlaskClient):
    installed = manifest(client)

    assert installed["name"] == "Spindrift"
    assert installed["start_url"] == "/"
    assert installed["scope"] == "/"
    assert installed["display"] == "standalone"


def test_the_manifest_and_page_take_their_colour_from_the_tokens(client: FlaskClient):
    installed = manifest(client)

    assert installed["theme_color"] == TOKENS["color"]["bg"]
    assert installed["background_color"] == TOKENS["color"]["bg"]
    body = client.get("/").get_data(as_text=True)
    assert f'<meta name="theme-color" content="{TOKENS["color"]["bg"]}" />' in body


def test_every_icon_the_manifest_names_is_there(client: FlaskClient):
    icons = manifest(client)["icons"]
    assert isinstance(icons, list)

    assert {(icon["sizes"], icon["purpose"]) for icon in icons} == {
        ("192x192", "any"),
        ("512x512", "any"),
        ("512x512", "maskable"),
    }
    for icon in icons:
        response = client.get(icon["src"])
        assert response.status_code == 200
        assert response.content_type == "image/png"


def test_the_apple_touch_icon_is_there(client: FlaskClient):
    body = client.get("/").get_data(as_text=True)

    assert 'rel="apple-touch-icon" href="/static/apple-touch-icon.png"' in body
    assert client.get("/static/apple-touch-icon.png").status_code == 200


def test_the_service_worker_is_served_from_the_root_and_always_revalidated(client: FlaskClient):
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.content_type == "text/javascript; charset=utf-8"
    assert response.headers["Cache-Control"] == "no-cache"


def test_the_service_worker_answers_no_requests(client: FlaskClient):
    """No fetch handler: every request still reaches the server, and through it the proxy."""
    assert "fetch" not in client.get("/sw.js").get_data(as_text=True)


def test_every_page_registers_the_service_worker(client: FlaskClient):
    body = client.get("/").get_data(as_text=True)

    assert 'src="/static/pwa.js"' in body
    assert 'data-service-worker="/sw.js"' in body


def test_the_manifest_and_service_worker_answer_without_identity(guarded_client: FlaskClient):
    assert guarded_client.get("/manifest.webmanifest").status_code == 200
    assert guarded_client.get("/sw.js").status_code == 200


def test_the_manifest_names_digested_icons_once_a_build_has_run(catalogue_path: Path):
    """nginx serves /static/ with long caching, so the icons need content names like the rest."""
    before = MANIFEST_PATH.read_text() if MANIFEST_PATH.exists() else None
    MANIFEST_PATH.write_text(json.dumps({"icon-192.png": "icon-192.0123456789ab.png"}))
    try:
        icons = manifest(create_app(catalogue_path).test_client())["icons"]
    finally:
        if before is None:
            MANIFEST_PATH.unlink(missing_ok=True)
        else:
            MANIFEST_PATH.write_text(before)

    assert isinstance(icons, list)
    assert icons[0]["src"] == "/static/icon-192.0123456789ab.png"
