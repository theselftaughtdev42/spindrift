# A way a game can be played — not a device owned and not a storefront licence.
# "Emulator" belongs here in exactly the same sense as "Steam".
#
# Hardcoded rather than a table: there is no management UI, and adding a platform is a
# source edit plus a restart. The order is display order. The granularity is deliberately
# uneven — PlayStation is split by generation because the generation changes the decision.
#
# "Xbox" is the coarse backward-compatible entry it has always been, and every game
# already ticked under it means exactly what it meant before: playable on the Xbox by
# whatever generation's disc or licence, backward compatibility included. "Xbox One" is
# narrower and additive — the titles worth calling out as that generation's. Renaming the
# older column would have rewritten the meaning of rows already stored, so it keeps its
# name and the new one sits beside it.
PLATFORMS = [
    "Steam",
    "Xbox",
    "Xbox One",
    "PS1",
    "PS2",
    "PS3",
    "PS4",
    "Switch",
    "Emulator",
]
