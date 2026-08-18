# What happened to a game, as a closed ordered set — the counterpart to the intent, which
# records only what was planned. The order is the order the control offers them in, and it
# runs the way a game does: the state it is in while being played, then the three it can
# come to rest in.
#
# Absence is the fifth state and has no entry here, because it is not a value: a game with
# no status is one nothing has been recorded about, the same way a game with no
# availability is one that is not playable and a game with no intent is one not decided on.
# That is why nothing backfills these — the 116 games that predate this column are
# unrecorded, which is true, rather than "not started", which would be a guess.
#
# Stored value and displayed label are the same word, differing only in the capital a
# sentence would give it. There is no mapping to keep in step and no second vocabulary: what
# is read on screen is what the database holds. An earlier shortlist used "Done" and
# "Dropped"; "Done" went because it reads as a synonym of "100%" when scanning a column,
# and the column is wide enough that nothing here needs abbreviating.
STATUSES = ["playing", "finished", "100%", "abandoned"]
