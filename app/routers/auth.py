"""认证路由"""

from random import random
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from httpx import Client, HTTPError
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models import Department, User, UserDeptLink
from app.uniform_login_des import strEnc

router = APIRouter(tags=["认证"])
settings = get_settings()
templates = Jinja2Templates(directory=settings.base_dir / "templates")

# 临时存储登录会话
login_sessions: dict[str, httpx.Cookies] = {}


def clear_expired_sessions():
    """清理过期会话"""
    # 简单实现：保留最近100个会话
    if len(login_sessions) > 100:
        keys = list(login_sessions.keys())[:-50]
        for key in keys:
            login_sessions.pop(key, None)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)):
    """登录页面"""
    # 如果已登录，跳转到首页
    if request.session.get("user_id"):
        return RedirectResponse(url="/record", status_code=302)

    context = {"request": request, "debug_mode": settings.debug}

    # Debug 模式下加载所有用户供快速登录
    if settings.debug:
        users = session.exec(select(User)).all()
        all_users = []
        for user in users:
            # 检查是否是管理员
            is_admin = (
                session.exec(
                    select(UserDeptLink)
                    .where(UserDeptLink.user_id == user.id)
                    .where(UserDeptLink.is_admin == True)
                ).first()
                is not None
            )

            all_users.append(
                {
                    "id": user.id,
                    "name": user.name,
                    "phone": user.phone,
                    "is_admin": is_admin,
                }
            )
        context["all_users"] = all_users

    return templates.TemplateResponse("login.html", context)


@router.post("/auth/code")
async def get_image_code(request: Request):
    """获取图形验证码"""
    clear_expired_sessions()
    try:
        upstream = httpx.get(f"https://pass.sdu.edu.cn/cas/code?{random()}")
    except HTTPError:
        raise HTTPException(503, "统一认证服务不可用")

    ls = uuid4().hex
    login_sessions[ls] = upstream.cookies

    response = Response(upstream.content, media_type="image/gif")
    response.set_cookie("login_session", ls, max_age=300, httponly=True)
    return response


@router.post("/auth/sms", status_code=201)
async def send_sms_code(
    request: Request,
    mobile: str = Form(..., min_length=11, max_length=11),
    code: str = Form(..., min_length=4, max_length=4),
):
    """发送短信验证码"""
    clear_expired_sessions()
    ls = request.cookies.get("login_session")
    if not ls or ls not in login_sessions:
        raise HTTPException(400, "会话已过期，请刷新验证码")

    try:
        res = httpx.post(
            "https://pass.sdu.edu.cn/cas/loginByMorE",
            data={
                "method": "sendMobileCode",
                "sendConfirm": code,
                "mobile": mobile,
                "random": random(),
            },
            cookies=login_sessions[ls],
        )
    except HTTPError:
        raise HTTPException(503, "统一认证服务不可用")

    login_sessions[ls].update(res.cookies)

    if error := res.json().get("error"):
        raise HTTPException(400, error)
    if res.json().get("redirectUrl") != "login":
        raise HTTPException(400, "验证码错误")

    return {"message": "短信已发送"}


@router.post("/auth/login")
async def do_login(
    request: Request,
    session: Session = Depends(get_session),
    mobile: str = Form(..., min_length=11, max_length=11),
    sms_code: str = Form(..., min_length=6, max_length=6),
):
    """执行登录"""
    clear_expired_sessions()
    ls = request.cookies.get("login_session")
    if not ls or ls not in login_sessions:
        raise HTTPException(400, "会话已过期，请重新获取验证码")

    client = Client(cookies=login_sessions.pop(ls))

    try:
        res = client.post(
            "https://pass.sdu.edu.cn/cas/loginByMorE",
            data={
                "method": "login",
                "mobile": mobile,
                "mobileCode": sms_code,
                "random": random(),
                "service": "https://service.sdu.edu.cn/tp_up/view?m=up",
            },
        )
    except HTTPError:
        raise HTTPException(503, "统一认证服务不可用")

    if not (url := res.json().get("redirectUrl")):
        raise HTTPException(400, "验证码错误")

    # 获取用户信息
    try:
        client.get(url, follow_redirects=True)
        sduid = client.post(
            "https://service.sdu.edu.cn/tp_up/sys/uacm/profile/getUserType",
            json={},
            headers={"Content-Type": "application/json;charset=UTF-8"},
        ).json()[0]["ID_NUMBER"]

        info = client.post(
            "https://service.sdu.edu.cn/tp_up/sys/uacm/profile/getUserById",
            json={"BE_OPT_ID": strEnc(sduid, "tp", "des", "param")},
            headers={"Content-Type": "application/json;charset=UTF-8"},
        ).json()
    except Exception:
        raise HTTPException(503, "无法获取用户信息")

    name = info.get("USER_NAME", "")

    # 查找或创建用户
    user = session.exec(select(User).where(User.phone == mobile)).first()

    if user:
        # 更新用户信息
        user.sduid = sduid
        user.name = name
        session.add(user)
        session.commit()
    else:
        # 创建新用户
        user = User(phone=mobile, sduid=sduid, name=name)
        session.add(user)
        session.commit()
        session.refresh(user)

    # 检查用户是否是任何部门的管理员
    from app.models import UserDeptLink

    is_admin = (
        session.exec(
            select(UserDeptLink)
            .where(UserDeptLink.user_id == user.id)
            .where(UserDeptLink.is_admin == True)
        ).first()
        is not None
    )

    # 设置session
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name
    request.session["is_admin"] = is_admin

    # 返回重定向响应
    response = RedirectResponse(url="/record", status_code=302)
    return response


@router.get("/logout")
async def logout(request: Request):
    """登出"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, session: Session = Depends(get_session)):
    """个人资料页面"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    user = session.get(User, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    # 获取用户部门
    links = session.exec(
        select(UserDeptLink).where(UserDeptLink.user_id == user.id)
    ).all()

    departments = []
    for link in links:
        departments.append(
            {
                "name": link.department.name,
                "is_admin": link.is_admin,
            }
        )

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "departments": departments,
        },
    )


@router.post("/auth/debug-login/{user_id}")
async def debug_login(
    request: Request,
    user_id: int,
    session: Session = Depends(get_session),
):
    """Debug 模式快速登录（仅开发环境可用）"""
    if not settings.debug:
        raise HTTPException(403, "此功能仅在 debug 模式下可用")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")

    # 检查是否是管理员
    is_admin = (
        session.exec(
            select(UserDeptLink)
            .where(UserDeptLink.user_id == user.id)
            .where(UserDeptLink.is_admin == True)
        ).first()
        is not None
    )

    # 设置 session
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name
    request.session["is_admin"] = is_admin

    return {"message": "登录成功", "user": user.name}
