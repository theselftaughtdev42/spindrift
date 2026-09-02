import os
from pathlib import Path

from waitress import serve

from spindrift import create_app

# Beside the source, gitignored. Not in a system data directory: this app is expected to
# be run from its checkout. In the container the database lives on a mounted volume
# instead, so SPINDRIFT_DB overrides this — the image sets it to /data/catalogue.sqlite3.
# Unset (the local `uv run main.py` case) keeps the beside-source default unchanged.
DATABASE_PATH = os.environ.get(
    "SPINDRIFT_DB", Path(__file__).parent / "catalogue.sqlite3"
)

# 0.0.0.0 so other devices on the home network can reach it. Port 8000 rather than
# Flask's 5000, which macOS AirPlay Receiver occupies
HOST = "0.0.0.0"
PORT = 8000


def main():
    print(f"Spindrift on http://localhost:{PORT} (and this machine's LAN address)")
    serve(create_app(DATABASE_PATH), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
