"""Content-addressed names for the static files, and the manifest that maps to them.

nginx serves /static/ off disk in front of the app, so the name written into the HTML is the
only cache-busting lever there is: every file is copied to one carrying a digest of its own
contents, and nginx can then be told to keep them for a year. A digest rather than the
release version, so a file that has not changed is not refetched on every deploy.

Copies rather than renames — the originals are what a developer edits and what Flask serves
where there is no build. The deploy adds these to the host without deleting what is already
there, so a page from either side of a release asks for a name still sitting on disk.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

# Beside the package rather than inside `static/`, which nginx is handed whole.
MANIFEST_PATH = Path(__file__).resolve().parent / "static_manifest.json"

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Twelve hex characters of SHA-256: collision-proof enough, short enough to read in a URL.
DIGEST_LENGTH = 12

# What `build` writes, so a second run can tell its own output from the sources.
GENERATED = re.compile(rf"\.[0-9a-f]{{{DIGEST_LENGTH}}}\.[^.]+$")


def digest_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_LENGTH]


def digested_name(name, digest):
    """`theme.css` and a digest become `theme.<digest>.css`, suffix last so the type reads."""
    path = Path(name)
    return f"{path.stem}.{digest}{path.suffix}"


def clear(static_dir=STATIC_DIR, manifest_path=MANIFEST_PATH):
    """Remove everything a build wrote: the digested copies and the manifest naming them.

    `build` runs this first, so a re-run cannot digest a digest. `make local` runs it alone:
    a manifest left in the source tree pins every page to the names some earlier build
    digested, and an edited stylesheet is then served as it was, refresh or no refresh.
    """
    for stale in static_dir.iterdir():
        if stale.is_file() and GENERATED.search(stale.name):
            stale.unlink()
    manifest_path.unlink(missing_ok=True)


def build(static_dir=STATIC_DIR, manifest_path=MANIFEST_PATH):
    """Write a digested copy of every static file, and the manifest naming them.

    Run from the Dockerfile, against the files already copied into the image.
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

    Empty is the ordinary state on a developer's machine: `url_for` falls through to the
    plain names, which Flask serves itself with `no-cache`.
    """
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return {}


# Run as a script rather than `-m spindrift.static_manifest`, which would import the package
# and with it Flask. This is stdlib only, so the image can build the manifest on the base
# interpreter. `--clear` is a flag rather than a second script because both halves have to
# agree on the pattern naming a generated file.
if __name__ == "__main__":
    if "--clear" in sys.argv[1:]:
        clear()
    else:
        for name, digested in build().items():
            print(f"{name} -> {digested}")
