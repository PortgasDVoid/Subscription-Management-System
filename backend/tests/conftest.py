"""Test database fixtures.

RECONSTRUCTED STAND-IN (the original conftest was not in the uploaded zips): it provides the
fixtures the uploaded tests use - ``engine``, ``conn``, ``scope`` and the ``q`` helper.

Set TEST_DATABASE_URL (a dedicated database; it is DROPPED and rebuilt from db/*.sql once per
session). Without it, every test that needs the database is skipped.
"""
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

DB_DIR = Path(__file__).resolve().parents[1] / "db"
SQL_FILES = ["01_schema.sql", "02_seed.sql", "03_subscription_stage_view.sql"]


def q(conn, sql, **params):
    return conn.execute(text(sql), params)


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping database tests")
    eng = create_engine(url, future=True)
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        for name in SQL_FILES:
            cur.execute((DB_DIR / name).read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()
    yield eng
    eng.dispose()


@pytest.fixture()
def conn(engine):
    """A connection inside one outer transaction that is rolled back after each test."""
    c = engine.connect()
    outer = c.begin()
    try:
        yield c
    finally:
        outer.rollback()
        c.close()


@pytest.fixture()
def scope(conn):
    """Stand-in for app.db.scope: every 'transaction' is a savepoint on the test connection."""
    @contextmanager
    def _scope():
        with conn.begin_nested():
            yield conn
    return _scope
