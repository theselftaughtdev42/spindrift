# A way a game can be played — not a device owned and not a storefront licence.
# "Emulator" belongs here in exactly the same sense as "Steam".
#
# Hardcoded rather than a table: there is no management UI, and adding a platform is a
# source edit plus a restart. The order is display order. The granularity is deliberately
# uneven — Xbox is one coarse entry because its backward compatibility means the
# generation rarely changes the decision; PlayStation is split because it does.
PLATFORMS = ["Steam", "Xbox", "PS1", "PS2", "PS3", "PS4", "Switch", "Emulator"]
