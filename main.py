from pathlib import Path

from waitress import serve

from spindrift import create_app

# Beside the source, gitignored. Not in a system data directory: this app is expected to
# be run from its checkout.
DATABASE_PATH = Path(__file__).parent / "catalogue.sqlite3"

# 0.0.0.0 so other devices on the home network can reach it. Port 8000 rather than
# Flask's 5000, which macOS AirPlay Receiver occupies
HOST = "0.0.0.0"
PORT = 8000


def main():
    print(f"Spindrift on http://localhost:{PORT} (and this machine's LAN address)")
    serve(create_app(DATABASE_PATH), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
