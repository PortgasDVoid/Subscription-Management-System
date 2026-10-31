"""Engine + transaction scope. Swap this module for the team's session module if there is one.

``scope()`` yields a Connection inside its own transaction (commit on success, rollback on error);
``run_billing`` and ``run_lifecycle`` take ``scope`` so every subscription gets its own short transaction.
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine

DEFAULT_URL = "postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_db"

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ.get("DATABASE_URL", DEFAULT_URL), pool_pre_ping=True, future=True)
    return _engine


@contextmanager
def scope():
    with get_engine().begin() as conn:
        yield conn
