"""数据模型模块（合并版）"""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid7

from fastapi import HTTPException
from sqlmodel import Field, Relationship, Session, SQLModel, select


class Table(SQLModel):
    """所有表的基类，包含公共字段"""

    id: UUID = Field(default_factory=uuid7, primary_key=True, index=True)


class UserDeptLink(Table, table=True):
    """用户-部门关联表，包含角色信息"""

    __tablename__: ClassVar[str] = "user_dept_link"

    user_id: UUID = Field(foreign_key="user.id", primary_key=True)
    dept_id: UUID = Field(foreign_key="department.id", primary_key=True)
    is_admin: bool = Field(default=False)

    user: User = Relationship(
        back_populates="dept_links",
        sa_relationship_kwargs={"overlaps": "departments,users"},
    )
    department: Department = Relationship(
        back_populates="user_links",
        sa_relationship_kwargs={"overlaps": "departments,users"},
    )


class User(Table, table=True):
    """用户表"""

    phone: str = Field(index=True, unique=True, max_length=11)
    name: str = Field()
    sduid: str = Field(min_length=9, max_length=12, index=True)

    dept_links: list[UserDeptLink] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"overlaps": "departments,users"},
    )
    work_records: list[WorkRecord] = Relationship(back_populates="user")
    settlement_claims: list[SettlementClaim] = Relationship(back_populates="user")

    departments: list[Department] = Relationship(
        back_populates="users",
        link_model=UserDeptLink,
        sa_relationship_kwargs={"overlaps": "dept_links,user,department,user_links"},
    )

    def dept_list(self) -> list[dict]:
        """获取用户所属部门列表"""
        return [
            {
                "id": link.dept_id,
                "name": link.department.name,
                "is_admin": link.is_admin,
            }
            for link in self.dept_links
        ]

    def admin_dept_list(self) -> list[dict]:
        """获取用户管理的部门列表"""
        return [d for d in self.dept_list() if d["is_admin"]]

    def is_dept_admin(self, db: Session, dept_id: UUID) -> bool:
        """检查用户是否为指定部门管理员"""
        return (
            db.exec(
                select(UserDeptLink.is_admin).where(
                    UserDeptLink.user_id == self.id, UserDeptLink.dept_id == dept_id
                )
            ).first()
            or False
        )

    def require_admin(self, db: Session, dept_id: UUID):
        """检查用户是否为指定部门管理员，若不是则抛出403异常"""
        if not self.is_dept_admin(db, dept_id):
            raise HTTPException(status_code=403, detail="需要部门管理员权限")


class Department(Table, table=True):
    """部门表"""

    name: str = Field(max_length=100, unique=True)

    user_links: list[UserDeptLink] = Relationship(
        back_populates="department",
        sa_relationship_kwargs={"overlaps": "departments,users"},
    )
    projects: list[Project] = Relationship(back_populates="department")
    work_records: list[WorkRecord] = Relationship(back_populates="department")
    settlement_periods: list[SettlementPeriod] = Relationship(
        back_populates="department"
    )
    users: list[User] = Relationship(
        back_populates="departments",
        link_model=UserDeptLink,
        sa_relationship_kwargs={"overlaps": "dept_links,user,department,user_links"},
    )


class Project(Table, table=True):
    """项目表"""

    dept_id: UUID = Field(foreign_key="department.id", index=True)
    name: str = Field(max_length=200)
    is_visible: bool = Field(default=True)
    last_active_at: datetime = Field(default_factory=datetime.now)

    department: Department = Relationship(back_populates="projects")
    work_records: list[WorkRecord] = Relationship(back_populates="project")
    settlement_summaries: list[SettlementProjectSummary] = Relationship(
        back_populates="project"
    )


class WorkRecord(Table, table=True):
    """工作记录表"""

    __tablename__: ClassVar[str] = "work_record"

    user_id: UUID = Field(foreign_key="user.id", index=True)
    dept_id: UUID = Field(foreign_key="department.id", index=True)
    project_id: UUID = Field(foreign_key="project.id", index=True)

    description: str = Field(max_length=1000)
    duration_minutes: int
    related_content: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    claim_id: UUID | None = Field(
        default=None, foreign_key="settlement_claim.id", index=True
    )

    user: User = Relationship(back_populates="work_records")
    department: Department = Relationship(back_populates="work_records")
    project: Project = Relationship(back_populates="work_records")


class SettlementPeriod(Table, table=True):
    """报酬整理周期"""

    __tablename__: ClassVar[str] = "settlement_period"

    dept_id: UUID = Field(foreign_key="department.id", index=True)
    title: str = Field(max_length=100)
    start_date: datetime
    end_date: datetime
    is_open: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.now)

    department: Department = Relationship(back_populates="settlement_periods")
    claims: list[SettlementClaim] = Relationship(back_populates="period")
    project_summaries: list[SettlementProjectSummary] = Relationship(
        back_populates="period"
    )


class SettlementClaim(Table, table=True):
    """用户申报记录"""

    __tablename__: ClassVar[str] = "settlement_claim"

    period_id: UUID = Field(foreign_key="settlement_period.id", index=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)

    paid_minutes: int = Field(default=0)
    volunteer_minutes: int = Field(default=0)
    total_minutes: int = Field(default=0)
    submitted_at: datetime = Field(default_factory=datetime.now)

    period: SettlementPeriod = Relationship(back_populates="claims")
    user: User = Relationship(back_populates="settlement_claims")

    @property
    def paid_hours(self) -> float:
        """按小时读取工资时长"""
        return self.paid_minutes / 60

    @property
    def volunteer_hours(self) -> float:
        """按小时读取志愿时长"""
        return self.volunteer_minutes / 60

    @property
    def total_hours(self) -> float:
        """按小时读取申报总时长"""
        return self.total_minutes / 60


class SettlementProjectSummary(Table, table=True):
    """结算周期内项目状态与总结"""

    __tablename__: ClassVar[str] = "settlement_project_summary"

    period_id: UUID = Field(foreign_key="settlement_period.id", index=True)
    project_id: UUID = Field(foreign_key="project.id", index=True)
    status: str = Field(max_length=20)
    summary: str = Field(max_length=2000)
    updated_at: datetime = Field(default_factory=datetime.now)

    period: SettlementPeriod = Relationship(back_populates="project_summaries")
    project: Project = Relationship(back_populates="settlement_summaries")
