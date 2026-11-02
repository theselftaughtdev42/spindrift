import os
from pathlib import Path

from spindrift import create_app
from spindrift.db import DatabasePath
from spindrift.identity import resolve_proxy_auth

default_db_path = Path(__file__).resolve().parent.parent / "catalogue.sqlite3"
DATABASE_PATH: DatabasePath = os.environ.get("SPINDRIFT_DB", default_db_path)

app = create_app(DATABASE_PATH, resolve_proxy_auth())
