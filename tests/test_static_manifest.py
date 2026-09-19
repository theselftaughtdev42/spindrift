"""Digesting, clearing and loading the static manifest (stories 82, 83, 86).

It has its own seam because nothing reaches the manifest over HTTP: a build is real files
in a real directory, and only the names it writes ever show up in a page.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from spindrift.static_manifest import DIGEST_LENGTH, MANIFEST_PATH, build, clear, load

DIGEST = re.compile(rf"\.[0-9a-f]{{{DIGEST_LENGTH}}}(?=\.)")


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    static.mkdir()
    return static


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "static_manifest.json"


@pytest.fixture
def deployments_own_manifest() -> Iterator[Path]:
    """A manifest at the path the build defaults to, put back however the test leaves it.

    Empty, so a page built while it exists still quotes the plain names.
    """
    before = MANIFEST_PATH.read_text() if MANIFEST_PATH.exists() else None
    MANIFEST_PATH.write_text("{}\n")

    yield MANIFEST_PATH

    if before is None:
        MANIFEST_PATH.unlink(missing_ok=True)
    else:
        MANIFEST_PATH.write_text(before)


def expected_name(name: str, digested: str) -> re.Match[str] | None:
    source = Path(name)
    return re.fullmatch(
        rf"{re.escape(source.stem)}\.[0-9a-f]{{{DIGEST_LENGTH}}}{re.escape(source.suffix)}",
        digested,
    )


def test_a_build_digests_every_static_file_and_records_the_mapping(
    static_dir: Path, manifest_path: Path
):
    for name, contents in [("theme.css", b":root { color: red }"), ("htmx.min.js", b"htmx")]:
        (static_dir / name).write_bytes(contents)

    manifest = build(static_dir, manifest_path)

    assert sorted(manifest) == ["htmx.min.js", "theme.css"]
    for name, digested in manifest.items():
        assert expected_name(name, digested)
        assert (static_dir / digested).read_bytes() == (static_dir / name).read_bytes()


# The manifest lands in the source tree during an image build, so it is written to be read
# and diffed: one entry a line, in a settled order, ending in a newline.
def test_a_build_writes_the_manifest_one_indented_entry_to_a_line(
    static_dir: Path, manifest_path: Path
):
    for name, contents in [("theme.css", b":root { color: red }"), ("htmx.min.js", b"htmx")]:
        (static_dir / name).write_bytes(contents)

    manifest = build(static_dir, manifest_path)

    assert manifest_path.read_text() == (
        "{\n"
        f'  "htmx.min.js": "{manifest["htmx.min.js"]}",\n'
        f'  "theme.css": "{manifest["theme.css"]}"\n'
        "}\n"
    )


def test_a_build_told_where_to_put_its_manifest_leaves_the_deployments_own_alone(
    static_dir: Path, manifest_path: Path, deployments_own_manifest: Path
):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")

    build(static_dir, manifest_path)

    assert deployments_own_manifest.exists()


def test_a_stylesheet_whose_contents_change_gets_a_different_digested_name(
    static_dir: Path, manifest_path: Path
):
    theme = static_dir / "theme.css"
    theme.write_bytes(b":root { color: red }")
    before = build(static_dir, manifest_path)["theme.css"]

    theme.write_bytes(b":root { color: blue }")

    assert build(static_dir, manifest_path)["theme.css"] != before


def test_a_script_whose_contents_are_unchanged_keeps_its_digested_name(
    static_dir: Path, manifest_path: Path
):
    (static_dir / "htmx.min.js").write_bytes(b"htmx")
    before = build(static_dir, manifest_path)["htmx.min.js"]

    assert build(static_dir, manifest_path)["htmx.min.js"] == before


def test_a_build_leaves_the_originals_where_flask_serves_them(
    static_dir: Path, manifest_path: Path
):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")

    build(static_dir, manifest_path)

    assert (static_dir / "theme.css").read_bytes() == b":root { color: red }"


def test_a_second_build_never_digests_its_own_output(static_dir: Path, manifest_path: Path):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")
    (static_dir / "htmx.min.js").write_bytes(b"htmx")
    first = build(static_dir, manifest_path)

    second = build(static_dir, manifest_path)

    assert second == first
    assert not [again.name for again in static_dir.iterdir() if len(DIGEST.findall(again.name)) > 1]


def test_clearing_removes_what_a_build_wrote_and_leaves_the_originals(
    static_dir: Path, manifest_path: Path
):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")
    (static_dir / "htmx.min.js").write_bytes(b"htmx")
    build(static_dir, manifest_path)

    clear(static_dir, manifest_path)

    assert sorted(left.name for left in static_dir.iterdir()) == ["htmx.min.js", "theme.css"]


def test_clearing_removes_the_manifest_file(static_dir: Path, manifest_path: Path):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")
    build(static_dir, manifest_path)

    clear(static_dir, manifest_path)

    assert not manifest_path.exists()


def test_clearing_when_nothing_was_built_is_harmless(static_dir: Path, manifest_path: Path):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")

    clear(static_dir, manifest_path)

    assert [left.name for left in static_dir.iterdir()] == ["theme.css"]


def test_a_subdirectory_is_skipped_rather_than_digested(static_dir: Path, manifest_path: Path):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")
    (static_dir / "icons").mkdir()
    (static_dir / "icons" / "spindrift-mark.svg").write_bytes(b"<svg/>")

    manifest = build(static_dir, manifest_path)

    assert list(manifest) == ["theme.css"]


def test_load_returns_the_mapping_a_build_wrote(static_dir: Path, manifest_path: Path):
    (static_dir / "theme.css").write_bytes(b":root { color: red }")

    built = build(static_dir, manifest_path)

    assert load(manifest_path) == built


def test_load_returns_an_empty_mapping_when_no_build_has_run(manifest_path: Path):
    assert load(manifest_path) == {}


def test_load_returns_an_empty_mapping_when_the_manifest_is_not_json(manifest_path: Path):
    manifest_path.write_text("this is not a manifest\n")

    assert load(manifest_path) == {}


def test_a_deployment_running_from_source_quotes_the_plain_static_names(client: FlaskClient):
    body = client.get("/").get_data(as_text=True)

    for name in ("theme.css", "spindrift.css", "htmx.min.js"):
        assert f"/static/{name}" in body
