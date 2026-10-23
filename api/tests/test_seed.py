import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from scripts.seed import Config as SeedConfig
from scripts.seed import digest, generate, load, psycopg_url

API_DIR = os.path.dirname(os.path.dirname(__file__))
TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/casino_test"
)


@pytest.fixture
def isolated_seed_database():
    base_url = make_url(TEST_URL)
    database_name = f"casino_seed_test_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable for seed tests: {exc.__cause__ or exc}")
    finally:
        admin_engine.dispose()

    database_url = base_url.set(database=database_name)
    cfg = Config(os.path.join(API_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(API_DIR, "alembic"))
    cfg.set_main_option(
        "sqlalchemy.url",
        database_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    try:
        command.upgrade(cfg, "head")
        yield database_url.render_as_string(hide_password=False)
    finally:
        cleanup_engine = create_engine(
            base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        try:
            with cleanup_engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        finally:
            cleanup_engine.dispose()


def test_seed_is_reproducible_and_database_invariants_hold(isolated_seed_database):
    config = SeedConfig(
        seed=42,
        as_of=datetime(2026, 10, 23, tzinfo=UTC),
        days=60,
        players=40,
        admin_password="isolated-test-password",
    )
    first = generate(config)
    second = generate(config)
    assert digest(first) == digest(second)

    load(first, isolated_seed_database, reset=False)
    with psycopg.connect(psycopg_url(isolated_seed_database)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM players")
            assert cur.fetchone()[0] == config.players
            cur.execute("SELECT DISTINCT alert_type FROM risk_alerts")
            assert {row[0] for row in cur.fetchall()} == {
                "rapid_deposits",
                "structured_withdrawals",
                "shared_device",
                "loss_chasing",
                "unusual_bet_size",
            }
