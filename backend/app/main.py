"""FastAPI アプリケーション。"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .db import init_db

app = FastAPI(
    title="時間割自動編成API",
    description=(
        "日本の小学校・中学校・高等学校の週時間割を整数計画法で自動提案し、"
        "人が微調整できるようにするAPI。"
    ),
    version="1.0.0",
)

# 仮定 A-23: 開発とE2Eの利便のため CORS を全許可にしている。
# 公開運用する場合は TIMETABLE_CORS_ORIGINS で明示的に絞ること。
_origins = os.environ.get("TIMETABLE_CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins == "*" else [o.strip() for o in _origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
