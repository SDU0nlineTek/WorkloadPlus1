"""工作记录模型"""

from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel


class WorkRecord(SQLModel, table=True):
    """工作记录表"""

    __tablename__ = "work_record"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    dept_id: int = Field(foreign_key="department.id", index=True)  # 冗余字段，方便查询
    project_id: int = Field(foreign_key="project.id", index=True)

    description: str = Field(max_length=1000)
    duration_minutes: int  # 存分钟数
    related_content: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.now, index=True)

    # 关联
    user: "User" = Relationship(back_populates="work_records")
    department: "Department" = Relationship(back_populates="work_records")
    project: "Project" = Relationship(back_populates="work_records")


# 避免循环导入
from app.models.department import Department  # noqa: E402, F401
from app.models.project import Project  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
