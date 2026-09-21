# A catalogue belongs to a cataloguer, and a snapshot doesn't say whose

Every game and every search URL has an owner, and each cataloguer on a deployment sees only
their own. Owners are rows in a `cataloguers` table keyed on the proxy's uid (ADR-0002). Row 1
is the default owner, and a deployment with no proxy uses it for everything, so there is no
nullable owner threaded through every query. The migration that brought in ownership handed
everything already there to row 1. The first cataloguer to sign in adopts that row by writing
their uid into it, so putting a proxy in front of a deployment keeps the catalogue it had.

The snapshot format does not change. A snapshot was always one catalogue, and it stays one,
with no owner written into the file. Whoever imports a snapshot decides whose it becomes. That
is also the only thing a snapshot written before ownership existed could mean, so those
snapshots still import. The alternative was to write the owner into the file and bump to
format 2.0. That would have needed the upgrade step ADR-0001 says does not exist, only to
throw the owner away again on import.

## Consequences

- The format stays at 1.0, and every snapshot ever written still imports, under the
  cataloguer importing it.
- Exporting is a per-cataloguer act: you get your own catalogue and nobody else's.
- Import and reset stay open to every cataloguer, because each one touches only the
  requester's catalogue. There is no deployment-wide reset.
- Game names are unique per owner, as are search URLs and the one active search URL. The
  one-intent index stays as it was: a game has one owner, so one intent per game is already
  one per owner.
- Owned rows name their owner explicitly, with no default. A query that forgot to say whose
  it was would otherwise give the row to whoever holds row 1.
- Ids are global. A route that names another cataloguer's game or search URL finds nothing,
  exactly as it would for one that was never there.
- Taking the proxy away again shows everyone the default owner's catalogue, which by then is
  the first cataloguer's. Everyone else's is kept, but can't be reached until the proxy goes
  back in front.
- Cataloguers are never deleted, and nothing but the uid is stored about them.
- Migrations now run with foreign keys off, so a table other tables refer to can be rebuilt
  without the drop cascading through them. Each migration is its own transaction, version
  included, so one that fails partway leaves the catalogue as the previous migration left it.
