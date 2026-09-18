import os
import tomllib
from pathlib import Path


def resolve_version():
    """What build this is. pyproject is only a fallback: it carries the *next* version."""
    baked = os.environ.get("SPINDRIFT_VERSION")
    if baked:
        return baked
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as file:
            return tomllib.load(file)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"
