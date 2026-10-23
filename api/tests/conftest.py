import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

API_DIR = Path(__file__).resolve().parents[1]
TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/casino_test"
)


@pytest.fixture(scope="session")
def engine():
    """A fresh database built ONLY from the Alembic migrations (so the tests cover them)."""
    url = make_url(TEST_URL)
    admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable for schema tests: {exc.__cause__ or exc}")
    finally:
        admin_engine.dispose()

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """Each test runs in a transaction that is rolled back, so tests never see each other's rows."""
    with engine.connect() as connection:
        trans = connection.begin()
        yield connection
        trans.rollback()
