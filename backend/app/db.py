"""DB接続。

仮定 A-05: マイグレーションは導入せず、起動時に create_all でスキーマを作る。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DATABASE_URL = os.environ.get("TIMETABLE_DATABASE_URL", "sqlite:///./timetable.db")

engine = create_engine(
    DATABASE_URL,
    # SQLite は既定で作成スレッド以外からの利用を禁じるが、求解ジョブを別スレッドで
    # 走らせるため解除する（仮定 A-06）
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def reset_db() -> None:
    """スキーマを作り直す。E2E のように毎回まっさらな状態で始めたいときに使う。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
