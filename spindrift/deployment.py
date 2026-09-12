"""Moving a deployment's entire state in and out: export, import and reset.

Each works on the whole of it — every game and every search URL — and never on part. None
of them touches the schema: no migration runs and `user_version` is left where it was, so
the running app and the database it migrated stay in step.

Concurrency is SQLite's own locking and nothing more. A device writing at the same moment
either waits briefly for the lock or loses its change because the game it changed was
replaced, which is accepted for a deployment on a home network.
"""

from spindrift.platforms import PLATFORMS
from spindrift.snapshot import FORMAT_VERSION, Game, SearchUrl, Snapshot


def export(connection):
    """A snapshot of the deployment, as the JSON text of the file.

    Everything is in a fixed order — games by name ignoring case, each game's platforms in
    the catalogue's column order, search URLs in the order they were saved — so two exports
    of the same state are identical byte for byte. An absent status or intent is written as
    `null` rather than left out, so the file says "undecided" rather than saying nothing.

    Availabilities on a platform no longer in `PLATFORMS` are left out. A platform taken off
    the list leaves its rows behind in the database, where the catalogue already draws
    nothing for them; exporting them would make a snapshot this very deployment refuses to
    import. An intent on one of those platforms is left out with it, so that game exports
    as undecided.
    """
    games = connection.execute(
        "SELECT id, name, status FROM games ORDER BY name COLLATE NOCASE"
    ).fetchall()
    availability = set()
    intents = {}
    for row in connection.execute(
        "SELECT game_id, platform, intended FROM game_platforms"
    ):
        if row["platform"] not in PLATFORMS:
            continue
        availability.add((row["game_id"], row["platform"]))
        if row["intended"]:
            intents[row["game_id"]] = row["platform"]
    search_urls = connection.execute(
        "SELECT url, active FROM search_urls ORDER BY id"
    ).fetchall()

    snapshot = Snapshot(
        spindrift=FORMAT_VERSION,
        games=[
            Game(
                name=game["name"],
                status=game["status"],
                platforms=[
                    platform
                    for platform in PLATFORMS
                    if (game["id"], platform) in availability
                ],
                intended=intents.get(game["id"]),
            )
            for game in games
        ],
        search_urls=[
            SearchUrl(url=row["url"], active=bool(row["active"])) for row in search_urls
        ],
    )
    return snapshot.model_dump_json(indent=2) + "\n"


def replace(connection, snapshot):
    """Replace the deployment's entire state with a validated snapshot, all or nothing.

    One transaction holds the deletions and every insert, so a constraint the snapshot
    breaks part-way through — a duplicate name, a second active URL — rolls the deletions
    back with it and leaves the deployment exactly as it was. The `sqlite3.IntegrityError`
    is re-raised for the caller to report.

    Games and search URLs go in file order. The intent is written as the flag on its own
    availability row, the only place the schema has for it.
    """
    with connection:
        clear(connection)
        for game in snapshot.games:
            cursor = connection.execute(
                "INSERT INTO games (name, status) VALUES (?, ?)",
                (game.name, game.status),
            )
            connection.executemany(
                "INSERT INTO game_platforms (game_id, platform, intended)"
                " VALUES (?, ?, ?)",
                [
                    (cursor.lastrowid, platform, platform == game.intended)
                    for platform in game.platforms
                ],
            )
        connection.executemany(
            "INSERT INTO search_urls (url, active) VALUES (?, ?)",
            [(search_url.url, search_url.active) for search_url in snapshot.search_urls],
        )


def reset(connection):
    """Delete every game and every search URL at once, leaving an empty deployment."""
    with connection:
        clear(connection)


def clear(connection):
    # Availabilities go with their games through the foreign key's cascade — including any
    # still sitting on a platform that has since been taken off the list.
    connection.execute("DELETE FROM search_urls")
    connection.execute("DELETE FROM games")
