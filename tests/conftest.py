import pytest

from spindrift import create_app


@pytest.fixture
def database_path(tmp_path):
    """An isolated database file for one test."""
    return tmp_path / "catalogue.sqlite3"


@pytest.fixture
def client(database_path):
    """A test client for an app constructed against an isolated database."""
    app = create_app(database_path)
    return app.test_client()
