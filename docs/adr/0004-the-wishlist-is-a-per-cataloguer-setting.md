# The wishlist is a per-cataloguer setting, and its marks live on the availability

Some cataloguers want to record which games are on a store's wishlist, so the store emails
them about sales. Most don't, so the feature is off unless the cataloguer turns it on. The
switch is a column on `cataloguers`, set from the settings page, not a deployment-wide
environment variable: a deployment is shared by everyone behind its proxy (ADR-0003), and one
cataloguer's taste shouldn't change what everyone else sees.

A mark is a `wishlisted` column on `game_platforms`, because a wishlist belongs to a store,
and a store is a platform. Hades wishlisted on Steam says nothing about Switch. The by-platform
page shows the mark for each game's intended platform, which is the one being tracked for a
sale.

## Consequences

- Turning the wishlist off only hides it. Every mark is kept and shows again when it is
  turned back on.
- Changing a game's intent keeps the old platform's mark. It shows again if the intent goes
  back.
- Removing an availability removes its mark with it. A game can't be on a wishlist where it
  isn't playable.
- While the wishlist is off, the route that toggles a mark answers 404, as if it didn't exist.
- Snapshots move to format 1.1: each game gains `wishlisted` (a list of platforms) and the
  snapshot gains `wishlist` (whether it's on). Both have defaults, so a 1.0 snapshot imports
  with nothing marked and the wishlist off (ADR-0001). Reset turns the wishlist off.
