from spindrift.platforms import PLATFORMS
from spindrift.snapshot import FORMAT_VERSION, Game, SearchUrl, Snapshot


def export(connection):
    """A snapshot of the deployment, as JSON text in a fixed order, so exports are stable."""
    games = connection.execute(
        "SELECT id, name, status FROM games ORDER BY name COLLATE NOCASE"
    ).fetchall()
    availability = set()
    intents = {}
    for row in connection.execute(
        "SELECT game_id, platform, intended FROM game_platforms"
    ):
        # Left out: this deployment would refuse to import them back.
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
    """Replace the deployment's entire state with a validated snapshot, all or nothing."""
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
    with connection:
        clear(connection)


def clear(connection):
    # Availabilities go with their games through the foreign key's cascade.
    connection.execute("DELETE FROM search_urls")
    connection.execute("DELETE FROM games")
