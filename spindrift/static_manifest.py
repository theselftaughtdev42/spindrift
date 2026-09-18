"""Content-addressed names for the static files, and the manifest that maps to them.

nginx serves /static/ off disk in front of the app, so the name written into the HTML is the
only cache-busting lever there is. A digest rather than the release version, so a file that
has not changed is not refetched on every deploy. Copies rather than renames, because the
originals are what a developer edits and what Flask serves where there is no build.
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

    `build` runs this first, so a re-run cannot digest a digest. `make local` runs it alone,
    because a manifest left in the source tree pins every page to an earlier build's names.
    """
    for stale in static_dir.iterdir():
        if stale.is_file() and GENERATED.search(stale.name):
            stale.unlink()
    manifest_path.unlink(missing_ok=True)


def build(static_dir=STATIC_DIR, manifest_path=MANIFEST_PATH):
    """Write a digested copy of every static file, and the manifest naming them."""
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
    """The manifest if a build wrote one, and an empty mapping if not, which is the ordinary
    state where there is no build: `url_for` then falls through to the plain names.
    """
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return {}


# Run as a script rather than `-m spindrift.static_manifest`, which would import the package
# and with it Flask. This is stdlib only, so the image can build the manifest on the base
# interpreter.
if __name__ == "__main__":
    if "--clear" in sys.argv[1:]:
        clear()
    else:
        for name, digested in build().items():
            print(f"{name} -> {digested}")
