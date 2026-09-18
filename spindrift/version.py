import os
import tomllib
from pathlib import Path


def resolve_version():
    """What build this is, worked out once at startup.

    The image bakes the release tag into `SPINDRIFT_VERSION`. pyproject is only a fallback
    and is read second, because it carries the *next* version all through the commits after
    a release is cut. "unknown" beats raising on a missing file.
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
