"""认证依赖工具"""

from dataclasses import dataclass
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlmodel import Session, select

from app.database import get_session
from app.models import Department, User, UserDeptLink


@dataclass
class RequestDep:
    request: Request
    db: Session


@dataclass
class UseridSessionOptionalDep(RequestDep):
    user_id: Optional[UUID]


@dataclass
class UseridSessionDep(RequestDep):
    user_id: UUID


@dataclass
class UserSessionDep(RequestDep):
    user: User


@dataclass
class UserSessionOptionalDep(RequestDep):
    user: Optional[User]


@dataclass
class AdminSessionDep(RequestDep):
    user: User
    dept: Department


@dataclass
class DeptAdminSessionDep(RequestDep):
    user: User
    dept: Department


async def get_session_user_id(
    request: Request, db: Session = Depends(get_session)
) -> UseridSessionDep:
    user_id = request.session.get("user_id")
    assert user_id, "login:未登录"
    try:
        return UseridSessionDep(request=request, db=db, user_id=UUID(user_id))
    except TypeError, ValueError:
        assert False, "login:会话无效"


UseridSession = Annotated[UseridSessionDep, Depends(get_session_user_id)]


async def get_session_user_id_optional(
    request: Request, db: Session = Depends(get_session)
) -> UseridSessionOptionalDep:
    """获取当前用户ID（可选，未登录返回None）"""
    user_id_raw = request.session.get("user_id")
    if not user_id_raw:
        return UseridSessionOptionalDep(request=request, db=db, user_id=None)
    try:
        return UseridSessionOptionalDep(
            request=request, db=db, user_id=UUID(user_id_raw)
        )
    except TypeError, ValueError:
        return UseridSessionOptionalDep(request=request, db=db, user_id=None)


UseridSessionOptional = Annotated[
    UseridSessionOptionalDep, Depends(get_session_user_id_optional)
]


async def get_user_session(s: UseridSession) -> UserSessionDep:
    """获取当前用户（必需，未登录抛出异常）"""
    user = s.db.get(User, s.user_id)
    assert user, "login:用户不存在"
    return UserSessionDep(request=s.request, db=s.db, user=user)


UserSession = Annotated[UserSessionDep, Depends(get_user_session)]


async def get_user_session_optional(s: UseridSessionOptional) -> UserSessionOptionalDep:
    """获取当前用户（可选，未登录返回None）"""
    user = s.db.get(User, s.user_id) if s.user_id else None
    return UserSessionOptionalDep(request=s.request, db=s.db, user=user)


UserSessionOptional = Annotated[
    UserSessionOptionalDep, Depends(get_user_session_optional)
]


async def get_admin_session(
    s: UserSession, dept_id: Optional[UUID] = Query(None)
) -> AdminSessionDep:
    """获取当前用户及其第一个管理员部门（必需，未登录或无管理员部门抛出异常）"""
    admin_depts = s.user.admin_dept_list()
    if len(admin_depts) == 0:
        assert False, "not_admin"
    if not dept_id:
        dept_id = admin_depts[0]["id"]  # 默认选择第一个部门
    if not any(d["id"] == dept_id for d in admin_depts):  # 验证权限
        dept_id = admin_depts[0]["id"]
    dept = s.db.exec(select(Department).where(Department.id == dept_id)).one()
    return AdminSessionDep(request=s.request, db=s.db, user=s.user, dept=dept)


AdminSession = Annotated[AdminSessionDep, Depends(get_admin_session)]


async def get_dept_admin_session(s: UserSession, dept_id: UUID) -> DeptAdminSessionDep:
    """获取当前用户及其管理员部门（必需，未登录或无管理员部门抛出异常）"""
    link = s.db.exec(
        select(UserDeptLink)
        .where(UserDeptLink.dept_id == dept_id)
        .where(UserDeptLink.user_id == s.user.id)
        .where(UserDeptLink.is_admin)
    ).first()
    assert link, "not_admin"
    return DeptAdminSessionDep(
        request=s.request, db=s.db, user=s.user, dept=link.department
    )


DeptAdminSession = Annotated[DeptAdminSessionDep, Depends(get_dept_admin_session)]
