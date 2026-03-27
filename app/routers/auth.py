"""认证路由"""

from datetime import datetime
from random import random
from urllib.parse import urlsplit
from uuid import UUID, uuid7

import httpx
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from httpx import Client, HTTPError
from sqlmodel import select

from app.core import SessionDep, settings
from app.models import User, UserDeptLink
from app.routers.deps import UserSession, templates
from app.utils.uniform_login_des import strEnc

router = APIRouter(tags=["认证"])


# 临时存储登录会话
login_sessions: dict[str, httpx.Cookies] = {}


def _safe_redirect_target(redirect: str | None, default: str = "/record") -> str:
    """只允许站内路径，避免开放重定向。"""
    if not redirect:
        return default
    parsed = urlsplit(redirect)
    if parsed.scheme or parsed.netloc:
        return default
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return default
    return redirect


def clear_expired_sessions():
    now = datetime.now().timestamp()
    for u in [u for u in login_sessions if now > UUID(u).time + 120 * 1000]:
        login_sessions.pop(u)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request, session: SessionDep, redirect: str | None = Query(None)
):
    """登录页面"""
    redirect_target = _safe_redirect_target(redirect)

    # 如果已登录，跳转到首页
    if request.session.get("user_id"):
        return RedirectResponse(url=redirect_target, status_code=302)

    context = {
        "request": request,
        "debug_mode": settings.debug,
        "redirect_target": redirect_target,
    }

    # Debug 模式下加载所有用户供快速登录
    if settings.debug:
        context["all_users"] = [
            {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "is_admin": session.exec(
                    select(UserDeptLink.is_admin).where(UserDeptLink.user_id == user.id)
                ).first()
                or False,
            }
            for user in session.exec(select(User)).all()
        ]

    return templates.TemplateResponse(request, "login.jinja2", context)


@router.post("/auth/code")
async def get_image_code():
    """获取图形验证码"""
    clear_expired_sessions()
    try:
        upstream = httpx.get(f"https://pass.sdu.edu.cn/cas/code?{random()}")
    except HTTPError:
        raise HTTPException(503, "统一认证服务不可用")
    login_sessions[(ls := uuid7().hex)] = upstream.cookies
    response = Response(upstream.content, media_type="image/gif")
    response.set_cookie("login_session", ls, max_age=120, httponly=True)
    return response


@router.post("/auth/sms", status_code=201)
async def send_sms_code(
    request: Request,
    mobile: str = Form(..., min_length=11, max_length=11, pattern=r"^\d+$"),
    code: str = Form(..., min_length=4, max_length=4, pattern=r"^\d+$"),
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
    session: SessionDep,
    mobile: str = Form(..., min_length=11, max_length=11, pattern=r"^\d+$"),
    sms_code: str = Form(..., min_length=6, max_length=6, pattern=r"^\d+$"),
    redirect: str | None = Form(None),
):
    """执行登录"""
    redirect_target = _safe_redirect_target(redirect)
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
    try:  # 获取用户信息
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
    # 设置session
    request.session["user_id"] = str(user.id)
    request.session["user_name"] = user.name
    request.session["is_admin"] = user.admin_dept_list() != []
    # 返回重定向响应
    response = RedirectResponse(url=redirect_target, status_code=302)
    return response


@router.get("/logout")
async def logout(request: Request):
    """登出"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/switch-dept")
async def switch_department(
    s: UserSession,
    dept_id: UUID = Query(...),
    next: str | None = Query(None),
):
    """切换当前部门上下文（侧边栏使用）。"""
    if not any(link.dept_id == dept_id for link in s.user.dept_links):
        raise HTTPException(400, "部门不存在或无访问权限")

    s.request.session["current_dept_id"] = str(dept_id)
    s.request.session["current_dept_is_admin"] = s.user.is_dept_admin(s.db, dept_id)

    target = _safe_redirect_target(next)
    return RedirectResponse(url=target, status_code=302)


if settings.debug:

    @router.post("/auth/debug-login/{user_id}")
    async def debug_login(
        request: Request,
        user_id: UUID,
        session: SessionDep,
    ):
        """Debug 模式快速登录（仅开发环境可用）"""
        if not settings.debug:
            raise HTTPException(403, "此功能仅在 debug 模式下可用")

        user = session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")

        # 设置 session
        request.session["user_id"] = str(user.id)
        request.session["user_name"] = user.name
        request.session["is_admin"] = user.admin_dept_list() != []

        return {"message": "登录成功", "user": user.name}
