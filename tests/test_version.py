"""What build a deployment says it is, and what it says when it cannot tell.

The number is only ever read by someone deciding whether a deployment has the fix they
came for, so `unknown` is an answer rather than a failure: a build that cannot name itself
still has to serve pages.
"""

from pathlib import Path

import pytest

from spindrift import version as version_module
from spindrift.version import resolve_version


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty tree shaped like an installed Spindrift, and the directory pyproject goes in.

    The fallback looks for pyproject beside the package it is itself in, so moving the module
    is the only way to hand it one that is not this repository's own.
    """
    monkeypatch.delenv("SPINDRIFT_VERSION", raising=False)
    monkeypatch.setattr(version_module, "__file__", str(tmp_path / "spindrift" / "version.py"))
    return tmp_path


def test_a_baked_in_version_is_what_the_build_reports(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPINDRIFT_VERSION", "1.2.3")

    assert resolve_version() == "1.2.3"


def test_without_one_baked_in_the_build_falls_back_to_pyproject(installation: Path):
    (installation / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')

    assert resolve_version() == "9.9.9"


def test_a_build_with_no_pyproject_beside_it_is_unknown(installation: Path):
    assert not (installation / "pyproject.toml").exists()

    assert resolve_version() == "unknown"


def test_a_pyproject_that_is_not_toml_is_unknown(installation: Path):
    (installation / "pyproject.toml").write_text("this is not toml{\n")

    assert resolve_version() == "unknown"


def test_a_pyproject_that_names_no_version_is_unknown(installation: Path):
    (installation / "pyproject.toml").write_text('[project]\nname = "spindrift"\n')

    assert resolve_version() == "unknown"


def test_a_version_that_is_not_text_is_unknown(installation: Path):
    """TOML admits numbers where this wants a string, and `0.5` read as a number is not the
    version anyone wrote."""
    (installation / "pyproject.toml").write_text("[project]\nversion = 0.5\n")

    assert resolve_version() == "unknown"
