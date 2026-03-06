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


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话"""
    with Session(engine) as session:
        yield session


# FastAPI 依赖注入
SessionDep = Annotated[Session, Depends(get_session)]
