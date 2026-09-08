import os
import tomllib
from pathlib import Path


def resolve_version():
    """What build this is, worked out once at startup and then just remembered.

    The image bakes the release into `SPINDRIFT_VERSION` at build time — the `v*` tag that
    cut it, as `0.2.0` — so a running container can be asked what it is and a rollback
    confirmed from the outside. That is the whole point of the value: the app is pulled as
    a moving tag, and this is what still says which release you actually got once `latest`
    has moved on.

    Off a developer's machine there is no such build and no env var, so this falls back to
    the version declared in pyproject.toml, the source's own idea of where it sits between
    releases. That file ships in the image too, but the env var is read first because it is
    the precise answer where both exist: pyproject carries the *next* version all through
    the commits after a release is cut, and only the baked-in tag knows which of those a
    given image was built from.

    "unknown" is the last resort for neither being present. It should not happen in a build
    or a checkout, but a health-adjacent endpoint answering with a truthful "unknown" is a
    better failure than one that raises on a missing file.
    """
    baked = os.environ.get("SPINDRIFT_VERSION")
    if baked:
        return baked
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as file:
            return tomllib.load(file)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"
