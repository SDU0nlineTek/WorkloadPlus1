"""数据库引擎和会话管理"""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
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


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话"""
    with Session(engine) as session:
        yield session


# FastAPI 依赖注入
SessionDep = Annotated[Session, Depends(get_session)]
