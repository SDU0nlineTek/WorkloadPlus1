"""报酬结算模型"""

from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel


class SettlementPeriod(SQLModel, table=True):
    """报酬整理周期"""

    __tablename__ = "settlement_period"

    id: int | None = Field(default=None, primary_key=True)
    dept_id: int = Field(foreign_key="department.id", index=True)
    title: str = Field(max_length=100)  # e.g. "10月工作量"
    start_date: datetime
    end_date: datetime
    is_open: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.now)

    # 关联
    department: "Department" = Relationship(back_populates="settlement_periods")
    claims: list["SettlementClaim"] = Relationship(back_populates="period")


class SettlementClaim(SQLModel, table=True):
    """用户申报记录"""

    __tablename__ = "settlement_claim"

    id: int | None = Field(default=None, primary_key=True)
    period_id: int = Field(foreign_key="settlement_period.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    paid_hours: float  # 工资时长
    volunteer_hours: float  # 志愿时长
    total_hours: float  # 本段总时长
    submitted_at: datetime = Field(default_factory=datetime.now)

    # 关联
    period: SettlementPeriod = Relationship(back_populates="claims")
    user: "User" = Relationship(back_populates="settlement_claims")


# 避免循环导入
from app.models.department import Department  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
