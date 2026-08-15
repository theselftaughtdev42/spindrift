# A way a game can be played — not a device owned and not a storefront licence.
# "Emulator" belongs here in exactly the same sense as "Steam".
#
# Hardcoded rather than a table: there is no management UI, and adding a platform is a
# source edit plus a restart. The order is display order. The granularity is deliberately
# uneven — PlayStation is split by generation because the generation changes the decision.
#
# Xbox is the exception to that, and deliberately so. "Xbox" is the coarse
# backward-compatible entry it has always been: playable on the Xbox by whatever
# generation's disc or licence, backward compatibility included. It is not the 2001
# console, and every game already ticked under it still means what it meant when it was
# ticked. "Xbox 360" and "Xbox One" are narrower and purely additive, for the titles worth
# calling out as a generation's own. So the three overlap by design, and a game can sit
# under the coarse entry and a named generation at once.
#
# The alternative — renaming the stored "Xbox" rows to the generation they mostly are —
# was considered and rejected: it would rewrite what rows already in the database claim.
PLATFORMS = [
    "Steam",
    "Xbox",
    "Xbox 360",
    "Xbox One",
    "PS1",
    "PS2",
    "PS3",
    "PS4",
    "Switch",
    "Emulator",
]
