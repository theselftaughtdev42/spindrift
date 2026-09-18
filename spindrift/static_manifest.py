"""Content-addressed names for the static files, and the manifest that maps to them.

nginx serves /static/ straight off disk in the deployment that matters, so the app cannot
reach those responses to say how long they may be kept. The only lever it holds is the
name it writes into the HTML, and this is what makes that name worth something: every file
is copied to one carrying a digest of its own contents, so an address and the bytes behind
it are fixed to each other for good. nginx can then be told to keep them for a year without
anyone having to trust that a future release will remember to rename something.

Copies rather than renames. The originals are what a developer edits and what Flask serves
on a machine with no build behind it; the digested names are an artefact of the image, and
`build` is the only thing that writes them.

A digest rather than the release version, which was the first shape this took. Stamping the
version onto every file renames all of them at every release, so `htmx.min.js` — untouched
since it was vendored — would be fetched again on every deploy to prove it had not changed.
The digest renames only what actually differs, which is the whole point of the exercise.

The deploy copies these onto the host *without* deleting what is already there, and that
additivity is the other half of the guarantee. The static files and the container can never
change in the same instant; with digested names the gap stops mattering, because a page
from either side of it asks for a name that is still sitting on disk.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

# Beside the package rather than inside `static/`: nginx is handed the static directory and
# has no use for this, while the app needs it and is never served from there. Keeping it out
# means the deploy copies only files that are actually meant to be fetched.
MANIFEST_PATH = Path(__file__).resolve().parent / "static_manifest.json"

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Twelve hex characters of SHA-256. Long enough that a collision is not a thing to think
# about, short enough to stay readable in a URL.
DIGEST_LENGTH = 12

# What `build` writes, so it can tell its own output from the sources on a second run and
# leave the directory the same whether it runs once or ten times.
GENERATED = re.compile(rf"\.[0-9a-f]{{{DIGEST_LENGTH}}}\.[^.]+$")


def digest_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_LENGTH]


def digested_name(name, digest):
    """`theme.css` and a digest become `theme.<digest>.css`.

    The suffix is kept last so the name still says what the file is — nginx and the browser
    both decide the content type from it, and a digest tacked onto the end would make every
    asset an unknown type.
    """
    path = Path(name)
    return f"{path.stem}.{digest}{path.suffix}"


def clear(static_dir=STATIC_DIR, manifest_path=MANIFEST_PATH):
    """Remove everything a build wrote: the digested copies and the manifest naming them.

    `build` runs this first, which is what stops a re-run digesting a digest. `make local`
    runs it on its own, for a different reason: the manifest is the app's only way of
    finding its static files, and it names whatever some earlier build happened to digest.
    One left in the source tree pins every page to those names, so an edited stylesheet is
    served as it was whenever that build ran and no amount of refreshing helps — the
    failure looks like a change that did not take rather than like a stale file.

    Clearing puts a developer's tree back in the state `load` calls ordinary: no manifest,
    plain names, and Flask serving them itself with `no-cache`.
    """
    for stale in static_dir.iterdir():
        if stale.is_file() and GENERATED.search(stale.name):
            stale.unlink()
    manifest_path.unlink(missing_ok=True)


def build(static_dir=STATIC_DIR, manifest_path=MANIFEST_PATH):
    """Write a digested copy of every static file, and the manifest naming them.

    Run from the Dockerfile, against the files already copied into the image. Anything left
    from an earlier run is cleared first so that re-running cannot digest a digest.
    """
    clear(static_dir, manifest_path)

    manifest = {}
    for source in sorted(static_dir.iterdir()):
        if not source.is_file():
            continue
        name = digested_name(source.name, digest_of(source))
        (static_dir / name).write_bytes(source.read_bytes())
        manifest[source.name] = name

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def load(manifest_path=MANIFEST_PATH):
    """The manifest if a build wrote one, and an empty mapping if not.

    Empty is the ordinary state on a developer's machine, where there is no build and no
    proxy: `url_for` then falls through to the plain names, which Flask serves itself with
    `no-cache`, so an edited stylesheet still shows up on a refresh. The fallback is the
    development mode rather than a thing to be configured into.
    """
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return {}


# Run as a script rather than imported as `-m spindrift.static_manifest`, which would pull
# in the package's `__init__` and with it Flask. Nothing here needs the venv, and keeping it
# that way means the image can build the manifest on the base interpreter — and that `make
# local` can undo it without one either.
#
# `--clear` rather than a second script, because the pattern naming a generated file is the
# thing both halves have to agree on, and it is defined once above.
if __name__ == "__main__":
    if "--clear" in sys.argv[1:]:
        clear()
    else:
        for name, digested in build().items():
            print(f"{name} -> {digested}")
