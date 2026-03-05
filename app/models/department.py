"""部门模型和用户-部门关联"""

from sqlmodel import Field, Relationship, SQLModel


class Department(SQLModel, table=True):
    """部门表"""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    active_project_window_months: int = Field(default=3)  # 活跃项目判定周期

    # 关联
    user_links: list["UserDeptLink"] = Relationship(back_populates="department")
    projects: list["Project"] = Relationship(back_populates="department")
    work_records: list["WorkRecord"] = Relationship(back_populates="department")
    settlement_periods: list["SettlementPeriod"] = Relationship(
        back_populates="department"
    )


class UserDeptLink(SQLModel, table=True):
    """用户-部门关联表，包含角色信息"""

    __tablename__ = "user_dept_link"

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    dept_id: int = Field(foreign_key="department.id", primary_key=True)
    is_admin: bool = Field(default=False)

    # 关联
    user: "User" = Relationship(back_populates="dept_links")
    department: Department = Relationship(back_populates="user_links")


# 避免循环导入
from app.models.project import Project  # noqa: E402, F401
from app.models.settlement import SettlementPeriod  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
from app.models.work_record import WorkRecord  # noqa: E402, F401
