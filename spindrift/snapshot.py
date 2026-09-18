"""The shape of a snapshot, and whether a file is one this deployment can import.

Organised around games rather than tables, so the file holds no database ids. The models ask
the write paths' own rules rather than copying them, and add the two checks the database
cannot make: that an intent names one of its own game's platforms, and that a name is more
than whitespace. Uniqueness is left to the indexes, which fail inside the import's
transaction like any other constraint.

Unknown fields are ignored, so a snapshot from a newer minor version still parses; per
ADR-0001 anything added in a later minor is optional with a default, so an older one does.
"""

import json
import re

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from spindrift.platforms import PLATFORMS
from spindrift.search_urls import search_url_problem
from spindrift.statuses import STATUSES

# The snapshot format this build writes, and whose major it reads. See ADR-0001.
FORMAT_VERSION = "1.0"
FORMAT_MAJOR = int(FORMAT_VERSION.split(".")[0])

UNCHANGED = "Your data is unchanged."


class SnapshotError(Exception):
    """A file refused as a snapshot. The message is what the cataloguer is shown."""


def known_platform(platform):
    if platform not in PLATFORMS:
        raise ValueError(f"{platform} is not a platform Spindrift has")
    return platform


class Game(BaseModel):
    name: str
    status: str | None
    platforms: list[str]
    intended: str | None

    # Stripped as well as checked, so a stray space imports as the name that was meant.
    @field_validator("name")
    @classmethod
    def name_not_blank(cls, name):
        name = name.strip()
        if not name:
            raise ValueError("a game needs a name")
        return name

    @field_validator("status")
    @classmethod
    def known_status(cls, status):
        if status is not None and status not in STATUSES:
            raise ValueError(f"{status} is not a status Spindrift has")
        return status

    @field_validator("platforms")
    @classmethod
    def known_platforms(cls, platforms):
        for platform in platforms:
            known_platform(platform)
        return platforms

    @field_validator("intended")
    @classmethod
    def known_intent(cls, intended):
        return intended if intended is None else known_platform(intended)

    # Impossible by construction in the schema, where the intent is a flag on an
    # availability row. A snapshot spells the two out separately, so it is checked here.
    @model_validator(mode="after")
    def intent_is_available(self):
        if self.intended is not None and self.intended not in self.platforms:
            raise ValueError(
                f"{self.name} is meant to be played on {self.intended},"
                " which isn't one of its platforms"
            )
        return self


class SearchUrl(BaseModel):
    url: str
    active: bool

    @field_validator("url")
    @classmethod
    def follows_rule(cls, url):
        url = url.strip()
        problem = search_url_problem(url)
        if problem:
            raise ValueError(problem)
        return url


class Snapshot(BaseModel):
    spindrift: str
    games: list[Game]
    search_urls: list[SearchUrl]


def parse(data):
    """The snapshot in `data`, fully validated — or a `SnapshotError` saying why not.

    Nothing here touches the database: the whole file is validated before a row is deleted.
    The version is read first, because it decides which rules the rest is read by. Strict
    rather than coercing, or a hand-written `"active": "no"` would quietly become true.
    """
    # `RecursionError`: deeply nested brackets exhaust the decoder's stack rather than
    # failing to parse, and are no more a snapshot for it.
    try:
        document = json.loads(data)
    except (ValueError, RecursionError):
        raise SnapshotError(f"That file isn't a snapshot — it isn't valid JSON. {UNCHANGED}")

    version = document.get("spindrift") if isinstance(document, dict) else None
    match = (
        re.fullmatch(r"([0-9]+)\.([0-9]+)", version) if isinstance(version, str) else None
    )
    if match is None:
        raise SnapshotError(
            "That file doesn't say which snapshot format it is, so it can't be imported."
            f" This Spindrift reads format {FORMAT_MAJOR}.x. {UNCHANGED}"
        )
    if int(match[1]) != FORMAT_MAJOR:
        raise SnapshotError(
            f"That snapshot is format {version}, but this Spindrift reads format"
            f" {FORMAT_MAJOR}.x. {UNCHANGED}"
        )

    try:
        return Snapshot.model_validate(document, strict=True)
    except ValidationError as error:
        raise SnapshotError(describe(error)) from None


def describe(error):
    """The first thing wrong with a snapshot, located from one the way a reader counts."""
    problems = error.errors()
    first = problems[0]
    where = " › ".join(
        str(part + 1) if isinstance(part, int) else str(part) for part in first["loc"]
    )
    # The stop goes because the sentence carries on: the search URL rule's messages are
    # whole sentences, written for the settings page's own banner.
    message = first["msg"].removeprefix("Value error, ").rstrip(".")
    more = len(problems) - 1
    extra = f" (and {more} more problem{'s' if more > 1 else ''})" if more else ""
    return f"That snapshot can't be imported — {where}: {message}{extra}. {UNCHANGED}"
