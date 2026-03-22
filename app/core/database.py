"""数据库引擎和会话管理"""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.core import settings

# SQLite 需要 connect_args={"check_same_thread": False}
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)


def create_db_and_tables():
    """创建数据库和表"""
    SQLModel.metadata.create_all(engine)

    # Lightweight compatibility migration for existing databases.
    inspector = inspect(engine)
    if "project" not in inspector.get_table_names():
        return

    project_columns = {col["name"] for col in inspector.get_columns("project")}
    if "is_visible" not in project_columns:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE project "
                    "ADD COLUMN is_visible BOOLEAN NOT NULL DEFAULT 1"
                )
            )

    if "settlement_claim" not in inspector.get_table_names():
        return

    claim_columns = {col["name"] for col in inspector.get_columns("settlement_claim")}
    with engine.begin() as conn:
        if "paid_minutes" not in claim_columns:
            conn.execute(
                text(
                    "ALTER TABLE settlement_claim "
                    "ADD COLUMN paid_minutes INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "volunteer_minutes" not in claim_columns:
            conn.execute(
                text(
                    "ALTER TABLE settlement_claim "
                    "ADD COLUMN volunteer_minutes INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "total_minutes" not in claim_columns:
            conn.execute(
                text(
                    "ALTER TABLE settlement_claim "
                    "ADD COLUMN total_minutes INTEGER NOT NULL DEFAULT 0"
                )
            )

        # Backfill legacy hour fields to minute fields when migrating existing DBs.
        if {"paid_hours", "volunteer_hours", "total_hours"}.issubset(claim_columns):
            conn.execute(
                text(
                    "UPDATE settlement_claim "
                    "SET paid_minutes = CASE WHEN paid_minutes = 0 THEN CAST(ROUND(paid_hours * 60) AS INTEGER) ELSE paid_minutes END, "
                    "volunteer_minutes = CASE WHEN volunteer_minutes = 0 THEN CAST(ROUND(volunteer_hours * 60) AS INTEGER) ELSE volunteer_minutes END, "
                    "total_minutes = CASE WHEN total_minutes = 0 THEN CAST(ROUND(total_hours * 60) AS INTEGER) ELSE total_minutes END"
                )
            )


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话"""
    with Session(engine) as session:
        yield session


# FastAPI 依赖注入
SessionDep = Annotated[Session, Depends(get_session)]
