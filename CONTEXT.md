# Spindrift

A catalogue of games and the ways they can be played, run on a home network and shared by
every device on it.

## Language

### The catalogue

**Catalogue**:
The whole collection of games one Spindrift deployment keeps.
_Avoid_: library, collection, list

**Game**:
One entry in the catalogue, identified by its name, which no other game shares regardless of
capitalisation.
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

### Configuration

**Search URL**:
A saved web address the catalogue's search control can send a game's name to.
_Avoid_: search engine, search link

**Active search URL**:
The one search URL the search control currently points at. With none active, there is no
search control.
_Avoid_: default, selected URL

### Moving between deployments

**Deployment**:
One running instance of Spindrift with its own catalogue and configuration.
_Avoid_: install, server, instance

**Snapshot**:
The entire persisted state of a deployment — every game with its availabilities, intent and
status, and every search URL with which one is active — captured as a single file.
_Avoid_: backup, dump, export file

**Export**:
Taking a snapshot of a deployment.

**Import**:
Replacing a deployment's entire state with the contents of a snapshot. Nothing already there
survives; an import never merges.
_Avoid_: restore, merge, load

**Reset**:
Deleting a deployment's entire state, leaving an empty catalogue with no search URLs.
_Avoid_: wipe, clear, factory reset
