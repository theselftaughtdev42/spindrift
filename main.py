import os
from typing import NoReturn

HOST = "0.0.0.0"
PORT = "8000"

APP = "spindrift.asgi:app"


def main() -> NoReturn:
    print("Spindrift on http://localhost:8000 (and this machine's LAN address)", flush=True)
    os.execvp("uvicorn", ["uvicorn", APP, "--host", HOST, "--port", PORT])


if __name__ == "__main__":
    main()
