"""Test bootstrap: dedicated Parking TEST database only (never production).

At session start the test database schema is dropped and rebuilt through
`alembic upgrade head`, which proves the migration itself.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text

from parking.config import test_database_url

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

_TRUNCATE = (
    "TRUNCATE TABLE parking_event, parking_audit_log, parking_session, parking_shift, "
    "parking_tariff_rule, parking_tariff_plan, parking_lane, parking_gate, parking_operator, "
    "parking_site, parking_vehicle, parking_tenant RESTART IDENTITY CASCADE"
)


def _alembic_cfg(url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def test_url() -> str:
    url = test_database_url()
    assert "_test" in url, "refusing destructive test bootstrap against a non-test database"
    return url


@pytest.fixture(scope="session")
def engine(test_url):
    engine = create_engine(test_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_cfg(test_url), "head")
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    yield
    with engine.begin() as conn:
        conn.execute(text(_TRUNCATE))


@pytest.fixture
def session_factory(engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()
