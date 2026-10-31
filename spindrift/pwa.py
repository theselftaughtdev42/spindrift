"""What a browser needs before it will offer Spindrift as an installable app.

Installable only: the service worker caches nothing, so every page still comes from the
server. A cached page could show a catalogue that has since changed, or outlive the sign-in
the proxy in front is checking.
"""

import json
from functools import cache
from pathlib import Path

TOKENS_PATH = Path(__file__).resolve().parent.parent / "design" / "tokens.json"

SERVICE_WORKER_PATH = Path(__file__).resolve().parent / "service_worker.js"


@cache
def theme_colour() -> str:
    """The display's background, for the browser chrome and the splash screen around it."""
    return str(json.loads(TOKENS_PATH.read_text())["color"]["bg"])


@cache
def service_worker() -> str:
    return SERVICE_WORKER_PATH.read_text()
