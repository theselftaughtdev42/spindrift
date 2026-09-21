# Identity comes from the proxy, and only where a deployment says one is there

Spindrift authenticates nobody. A proxy in front does it and passes its verdict in headers,
which the app reads only where `SPINDRIFT_PROXY_AUTH` says a proxy is there. A cataloguer is
keyed on the account's own id; every other header is a label, shown and logged and stored
nowhere. Nothing in the catalogue belongs to a cataloguer.

## Consequences

- With `SPINDRIFT_PROXY_AUTH` set, the loopback bind in the run contract stops being tidiness
  and becomes a security boundary: anything that can reach port 8000 directly can set those
  headers itself. A request arriving without them is refused `401` rather than served.
- `/health` and `/version` are exempt, because the image's `HEALTHCHECK` polls `/health` on
  localhost and never passes the proxy.
- The uid is the key, so a rename does not orphan anything — which matters not at all today,
  and matters entirely the moment a cataloguer owns a catalogue.
- A lapsed session is the proxy's answer, not the app's. htmx would swap a sign-in page into
  a table row, so a reply from another origin is turned into a whole navigation instead.
- Nothing is stored about a cataloguer, so there is no schema change, no snapshot change, and
  no migration. Snapshots written before identity existed and after it are the same files.
- Ownership is a separate decision. Giving a catalogue an owner is a breaking change to the
  database and to the snapshot format, and ADR-0001 says a snapshot format major is refused
  rather than upgraded — so that change has to settle how a pre-ownership snapshot imports
  before it is made.
