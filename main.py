import os

BIND = "0.0.0.0:8000"

APP = "spindrift.wsgi:app"


def main():
    print("Spindrift on http://localhost:8000 (and this machine's LAN address)", flush=True)
    os.execvp("gunicorn", ["gunicorn", APP, "--bind", BIND])


if __name__ == "__main__":
    main()
