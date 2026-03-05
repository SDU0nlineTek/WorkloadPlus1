"""认证依赖工具"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserDeptLink


async def get_current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    """获取当前登录用户"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
        )

    user = session.get(User, user_id)
    if not user:
        # 清除无效session
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    return user


async def get_current_user_optional(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    """获取当前用户（可选，未登录返回None）"""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return session.get(User, user_id)


def check_dept_admin(user: User, dept_id: int, session: Session) -> bool:
    """检查用户是否为指定部门管理员"""
    link = session.exec(
        select(UserDeptLink).where(
            UserDeptLink.user_id == user.id,
            UserDeptLink.dept_id == dept_id,
            UserDeptLink.is_admin == True,
        )
    ).first()
    return link is not None


def get_user_departments(user: User, session: Session) -> list[dict]:
    """获取用户所属部门列表"""
    links = session.exec(
        select(UserDeptLink).where(UserDeptLink.user_id == user.id)
    ).all()

    departments = []
    for link in links:
        dept = link.department
        departments.append(
            {
                "id": dept.id,
                "name": dept.name,
                "is_admin": link.is_admin,
            }
        )

    return departments


# 类型别名
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
