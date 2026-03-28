"""认证依赖工具"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.core import SessionDep, settings
from app.models import Department, SettlementPeriod, User

templates = Jinja2Templates(directory=settings.base_dir / "templates")


def _sync_user_dept_context(request: Request, db: Session, user: User) -> None:
    """Keep current department context in session for global sidebar switcher."""
    dept_options = user.dept_list()
    request.session["dept_options"] = [
        {
            "id": str(dept["id"]),
            "name": dept["name"],
            "is_admin": dept["is_admin"],
        }
        for dept in dept_options
    ]

    selected_raw = request.session.get("current_dept_id")
    selected_dept_id = None
    if selected_raw:
        try:
            selected_dept_id = UUID(selected_raw)
        except TypeError, ValueError:
            selected_dept_id = None

    valid_dept_ids = {dept["id"] for dept in dept_options}
    if selected_dept_id not in valid_dept_ids:
        selected_dept_id = dept_options[0]["id"] if dept_options else None

    if selected_dept_id:
        request.session["current_dept_id"] = str(selected_dept_id)
    else:
        request.session.pop("current_dept_id", None)

    selected_is_admin = bool(
        selected_dept_id and user.is_dept_admin(db, selected_dept_id)
    )
    request.session["current_dept_is_admin"] = selected_is_admin
    request.session["is_admin"] = len(user.admin_dept_list()) > 0


@dataclass
class RequestDep:
    request: Request
    db: Session


@dataclass
class UseridSessionDep(RequestDep):
    user_id: UUID


@dataclass
class UserSessionDep(RequestDep):
    user: User


@dataclass
class AdminSessionDep(RequestDep):
    user: User
    dept: Department


@dataclass
class DeptAdminSessionDep(RequestDep):
    user: User
    dept: Department


@dataclass
class PeriodUserSessionDep(RequestDep):
    user: User
    dept: Department
    period: SettlementPeriod


@dataclass
class PeriodAdminSessionDep(PeriodUserSessionDep):
    pass


async def get_session_user_id(request: Request, db: SessionDep) -> UseridSessionDep:
    user_id = request.session.get("user_id")
    assert user_id, "login:未登录"
    try:
        return UseridSessionDep(request=request, db=db, user_id=UUID(user_id))
    except TypeError, ValueError:
        assert False, "login:会话无效"


UseridSession = Annotated[UseridSessionDep, Depends(get_session_user_id)]


async def get_user_session(s: UseridSession) -> UserSessionDep:
    """获取当前用户（必需，未登录抛出异常）"""
    user = s.db.get(User, s.user_id)
    assert user, "login:用户不存在"
    _sync_user_dept_context(s.request, s.db, user)
    return UserSessionDep(request=s.request, db=s.db, user=user)


UserSession = Annotated[UserSessionDep, Depends(get_user_session)]


async def get_member_session(s: UserSession) -> UserSessionDep:
    """获取当前用户（必需），如果用户没有加入任何部门则抛出异常"""
    assert s.request.session.get("dept_options", []), "no_department"
    return s


MemberSession = Annotated[UserSessionDep, Depends(get_member_session)]


async def get_admin_session(s: UserSession) -> AdminSessionDep:
    """获取当前管理员和部门"""
    assert s.request.session.get("current_dept_is_admin"), "not_admin"
    dept = s.db.exec(
        select(Department).where(
            Department.id == UUID(s.request.session["current_dept_id"])
        )
    ).one()
    return AdminSessionDep(request=s.request, db=s.db, user=s.user, dept=dept)


AdminSession = Annotated[AdminSessionDep, Depends(get_admin_session)]


async def get_period_user_session(
    s: UserSession, period_id: UUID
) -> PeriodUserSessionDep:
    """获取当前用户及其部门和结算周期（必需，未登录或无访问权限抛出异常）"""
    period = s.db.get(SettlementPeriod, period_id)
    assert period, "not_found:结算周期不存在"
    assert period.dept_id == UUID(s.request.session["current_dept_id"]), (
        "not_found:结算周期不存在或无访问权限"
    )
    return PeriodUserSessionDep(
        request=s.request, db=s.db, user=s.user, dept=period.department, period=period
    )


PeriodUserSession = Annotated[PeriodUserSessionDep, Depends(get_period_user_session)]


async def get_period_admin_session(s: PeriodUserSession) -> PeriodAdminSessionDep:
    """获取当前用户及其管理员部门（必需，未登录或无管理员部门抛出异常）"""
    assert s.request.session.get("current_dept_is_admin"), "not_admin"
    return PeriodAdminSessionDep(
        request=s.request, db=s.db, user=s.user, dept=s.dept, period=s.period
    )


PeriodAdminSession = Annotated[PeriodAdminSessionDep, Depends(get_period_admin_session)]
