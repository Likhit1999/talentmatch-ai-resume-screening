import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base
from database import connection

@pytest.fixture(scope="session", autouse=True)
def setup_test_database(tmp_path_factory):
    """Use an isolated SQLite test database for pytest so talentmatch.db is never touched."""
    test_dir = tmp_path_factory.mktemp("db")
    test_db_path = test_dir / "test_talentmatch.db"
    test_db_url = f"sqlite:///{test_db_path}"

    os.environ["DATABASE_URL"] = test_db_url

    # Reset cached engine and session factory in connection module
    connection._ENGINE = None
    connection._SESSION_FACTORY = None

    connection.init_db(connection.get_engine(test_db_url))

    yield

    # Teardown: reset connection caches
    connection._ENGINE = None
    connection._SESSION_FACTORY = None

