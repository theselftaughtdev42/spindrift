# Spindrift

A catalogue of games and the ways they can be played, run on a home network and shared by
every device on it.

## Language

### The catalogue

**Catalogue**:
The whole collection of games one cataloguer keeps, with the search URLs they search them
with. A deployment keeps one for each of its cataloguers, and a deployment with no proxy
keeps exactly one.
_Avoid_: library, collection, list

**Game**:
One entry in a catalogue, identified by its name, which no other game in the same catalogue
shares regardless of capitalisation. Two cataloguers can each have a game of the same name.
_Avoid_: title, entry

**Platform**:
One of a fixed set of places a game can be played, such as Steam or Switch.
_Avoid_: system, store, console

**Availability**:
The fact that a game is playable on a particular platform. A game with no availabilities is
not playable anywhere.
_Avoid_: ownership, copy

**Intent**:
The one availability a game is meant to be played through. A game without one is
**undecided**; a game with one is **decided**.
_Avoid_: choice, preference, selected platform

**Status**:
What became of a game: playing, finished, 100% or abandoned. A game with no status is one
nothing has been recorded about, which is not the same as not started.
_Avoid_: progress, state, outcome

### Who is using it

**Cataloguer**:
The person a request is from, as the proxy in front says — never as the request itself
claims. A deployment with no proxy has no cataloguer at all, and works exactly as it always
has. A cataloguer is identified by the account's own id, which survives a rename; their
name is only ever displayed and logged.
_Avoid_: user, account, player, profile

A cataloguer owns a catalogue and sees nothing of anyone else's. Every game, availability,
intent, status and search URL is one cataloguer's. The catalogue a deployment had before a
proxy went in front of it is adopted by the first cataloguer to sign in.

### Configuration

**Search URL**:
A saved web address a catalogue's search control can send a game's name to. Each catalogue
has its own.
_Avoid_: search engine, search link

**Active search URL**:
The one search URL a catalogue's search control currently points at. With none active,
there is no search control.
_Avoid_: default, selected URL

### Moving between deployments

**Deployment**:
One running instance of Spindrift, keeping a catalogue for each of its cataloguers — or,
with no proxy in front, just the one.
_Avoid_: install, server, instance

**Snapshot**:
One catalogue — every game with its availabilities, intent and status, and every search URL
with which one is active — captured as a single file. A snapshot says nothing of whose
catalogue it was.
_Avoid_: backup, dump, export file

**Export**:
Taking a snapshot of the cataloguer's own catalogue.

**Import**:
Replacing the cataloguer's catalogue with the contents of a snapshot, which becomes theirs
whoever's it was. Nothing already in that catalogue survives; an import never merges, and
never touches anyone else's.
_Avoid_: restore, merge, load

**Reset**:
Deleting everything in the cataloguer's catalogue, leaving it empty with no search URLs.
Nobody else's is touched.
_Avoid_: wipe, clear, factory reset
