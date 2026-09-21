"""Whose catalogue a request reads and writes.

A catalogue belongs to a cataloguer, keyed on the uid the proxy vouches for (ADR-0003). A
deployment with no proxy has no cataloguer, and its one catalogue belongs to the default
owner: the row the migration that brought in ownership handed everything already there to.
The first cataloguer to sign in adopts it, so putting a proxy in front of a deployment keeps
the catalogue it had rather than leaving it to nobody.
"""

import sqlite3

DEFAULT_OWNER = 1


def owner_of(connection: sqlite3.Connection, uid: str) -> int:
    """The owner a cataloguer's uid names, made on first sight.

    Read first, because a cataloguer is new once and every request after that only looks.
    Both writes are safe to race: adopting only happens while nobody has, and a second
    request for the same new uid finds the insert already made.
    """
    # Unmutated: skipping the read only makes every request take the write path.
    row = connection.execute(  # pragma: no mutate
        "SELECT id FROM cataloguers WHERE uid = ?",  # pragma: no mutate
        (uid,),
    ).fetchone()
    if row is None:
        with connection:
            connection.execute(
                "UPDATE cataloguers SET uid = ? WHERE id = ? AND uid IS NULL",  # pragma: no mutate
                (uid, DEFAULT_OWNER),
            )
            connection.execute(
                "INSERT OR IGNORE INTO cataloguers (uid) VALUES (?)",  # pragma: no mutate
                (uid,),
            )
        row = connection.execute(
            "SELECT id FROM cataloguers WHERE uid = ?",  # pragma: no mutate
            (uid,),
        ).fetchone()
    return int(row["id"])  # pragma: no mutate
