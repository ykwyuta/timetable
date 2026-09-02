from __future__ import annotations

import os
import tempfile

import pytest

# テストは常に使い捨てのSQLiteを使う。app.db をimportする前に設定する必要がある
_tmpdir = tempfile.mkdtemp(prefix="timetable-tests-")
os.environ.setdefault("TIMETABLE_DATABASE_URL", f"sqlite:///{_tmpdir}/test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c
