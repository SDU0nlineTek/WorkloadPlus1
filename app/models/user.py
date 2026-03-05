"""用户模型"""

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """用户表"""

    id: int | None = Field(default=None, primary_key=True)
    phone: str = Field(index=True, unique=True, max_length=11)
    name: str = Field(max_length=50)
    sduid: str = Field(max_length=20, index=True)  # 学号

    # 关联
    dept_links: list["UserDeptLink"] = Relationship(back_populates="user")
    work_records: list["WorkRecord"] = Relationship(back_populates="user")
    settlement_claims: list["SettlementClaim"] = Relationship(back_populates="user")


# 避免循环导入
from app.models.department import UserDeptLink  # noqa: E402, F401
from app.models.settlement import SettlementClaim  # noqa: E402, F401
from app.models.work_record import WorkRecord  # noqa: E402, F401
