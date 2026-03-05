"""项目模型"""

from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel


class Project(SQLModel, table=True):
    """项目表"""

    id: int | None = Field(default=None, primary_key=True)
    dept_id: int = Field(foreign_key="department.id", index=True)
    name: str = Field(max_length=200)
    last_active_at: datetime = Field(default_factory=datetime.now)

    # 关联
    department: "Department" = Relationship(back_populates="projects")
    work_records: list["WorkRecord"] = Relationship(back_populates="project")


# 避免循环导入
from app.models.department import Department  # noqa: E402, F401
from app.models.work_record import WorkRecord  # noqa: E402, F401
