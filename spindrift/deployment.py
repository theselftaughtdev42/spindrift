import sqlite3

from spindrift.platforms import PLATFORMS
from spindrift.snapshot import FORMAT_VERSION, Game, SearchUrl, Snapshot

# A snapshot says nothing of whose catalogue it was (ADR-0003). It is one catalogue, and who
# imports it decides whose it becomes — which is also all a pre-ownership snapshot could mean.


def export(connection: sqlite3.Connection, owner: int) -> str:
    """A snapshot of one catalogue, as JSON text in a fixed order, so exports are stable."""
    games = connection.execute(
        "SELECT id, name, status FROM games WHERE owner_id = ?"  # pragma: no mutate
        " ORDER BY name COLLATE NOCASE",  # pragma: no mutate
        (owner,),
    ).fetchall()
    availability, intents, wishlisted = availabilities(connection, owner)
    search_urls = connection.execute(
        "SELECT url, active FROM search_urls WHERE owner_id = ? ORDER BY id",  # pragma: no mutate
        (owner,),
    ).fetchall()

    snapshot = Snapshot(
        spindrift=FORMAT_VERSION,
        games=[
            Game(
                name=game["name"],  # pragma: no mutate
                status=game["status"],  # pragma: no mutate
                platforms=[
                    platform
                    for platform in PLATFORMS
                    if (game["id"], platform) in availability  # pragma: no mutate
                ],
                intended=intents.get(game["id"]),  # pragma: no mutate
                wishlisted=[
                    platform for platform in PLATFORMS if (game["id"], platform) in wishlisted
                ],
            )
            for game in games
        ],
        search_urls=[
            SearchUrl(url=row["url"], active=bool(row["active"]))  # pragma: no mutate
            for row in search_urls
        ],
        wishlist=wishlist_enabled(connection, owner),
    )
    return snapshot.model_dump_json(indent=2) + "\n"


def availabilities(
    connection: sqlite3.Connection, owner: int
) -> tuple[set[tuple[int, str]], dict[int, str], set[tuple[int, str]]]:
    """Where one catalogue's games are playable, intended and wishlisted, as the export reads it."""
    availability: set[tuple[int, str]] = set()
    intents: dict[int, str] = {}
    wishlisted: set[tuple[int, str]] = set()
    for row in connection.execute(
        "SELECT game_id, platform, intended, wishlisted FROM game_platforms"  # pragma: no mutate
        " JOIN games ON games.id = game_platforms.game_id"  # pragma: no mutate
        " WHERE games.owner_id = ?",  # pragma: no mutate
        (owner,),
    ):
        # Left out: this deployment would refuse to import them back.
        if row["platform"] not in PLATFORMS:  # pragma: no mutate
            continue
        availability.add((row["game_id"], row["platform"]))  # pragma: no mutate
        if row["intended"]:  # pragma: no mutate
            intents[row["game_id"]] = row["platform"]  # pragma: no mutate
        if row["wishlisted"]:
            wishlisted.add((row["game_id"], row["platform"]))
    return availability, intents, wishlisted


def replace(connection: sqlite3.Connection, owner: int, snapshot: Snapshot):
    """Replace one catalogue with a validated snapshot, all or nothing."""
    with connection:
        clear(connection, owner)
        for game in snapshot.games:
            cursor = connection.execute(
                "INSERT INTO games (owner_id, name, status) VALUES (?, ?, ?)",  # pragma: no mutate
                (owner, game.name, game.status),
            )
            connection.executemany(
                "INSERT INTO game_platforms"  # pragma: no mutate
                " (game_id, platform, intended, wishlisted)"  # pragma: no mutate
                " VALUES (?, ?, ?, ?)",  # pragma: no mutate
                [
                    (
                        cursor.lastrowid,
                        platform,
                        platform == game.intended,
                        platform in game.wishlisted,
                    )
                    for platform in game.platforms
                ],
            )
        connection.executemany(
            "INSERT INTO search_urls (owner_id, url, active) VALUES (?, ?, ?)",  # pragma: no mutate
            [(owner, search_url.url, search_url.active) for search_url in snapshot.search_urls],
        )
        set_wishlist(connection, owner, snapshot.wishlist)


def reset(connection: sqlite3.Connection, owner: int):
    with connection:
        clear(connection, owner)


def clear(connection: sqlite3.Connection, owner: int):
    """Empty one catalogue. Every other cataloguer's is left exactly as it was."""
    # Availabilities go with their games through the foreign key's cascade.
    connection.execute("DELETE FROM search_urls WHERE owner_id = ?", (owner,))  # pragma: no mutate
    connection.execute("DELETE FROM games WHERE owner_id = ?", (owner,))  # pragma: no mutate
    set_wishlist(connection, owner, False)


def wishlist_enabled(connection: sqlite3.Connection, owner: int) -> bool:
    """Whether this cataloguer has the wishlist turned on (ADR-0004)."""
    row = connection.execute("SELECT wishlist FROM cataloguers WHERE id = ?", (owner,)).fetchone()
    return bool(row and row["wishlist"])


def set_wishlist(connection: sqlite3.Connection, owner: int, enabled: bool):
    """Turn the wishlist on or off. The marks are kept either way. Commits nothing itself."""
    connection.execute("UPDATE cataloguers SET wishlist = ? WHERE id = ?", (enabled, owner))
