"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from app.core import create_db_and_tables, settings
from app.routers import admin_router, auth_router, dashboard_router, record_router
from app.routers.deps import templates


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期管理"""
    # 启动时: 确保数据库表存在
    import app.models  # noqa: F401

    create_db_and_tables()
    yield
    # 关闭时: 清理资源


app = FastAPI(
    title=settings.app_name,
    description="极简工作填报系统",
    version="0.1.0",
    lifespan=lifespan,
    middleware=[
        Middleware(
            SessionMiddleware,
            secret_key=settings.secret_key,
            session_cookie=settings.session_cookie,
            max_age=settings.session_max_age,
        )
    ],
)


@app.exception_handler(AssertionError)
async def assertion_error_handler(request: Request, e: AssertionError):
    if str(e).startswith("login:"):
        if request.method == "GET":
            target = request.url.path
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return RedirectResponse(
                url=f"/login?redirect={quote(target, safe='')}", status_code=302
            )
        if str(e) != "login":
            raise HTTPException(401, str(e)[6:])
    elif str(e).startswith("not_admin"):
        return templates.TemplateResponse(
            request, "admin/no_permission.html", {"request": request}
        )
    elif str(e).startswith("not_found:"):
        raise HTTPException(404, str(e)[10:])
    else:
        raise e


# 静态文件
app.mount("/static", StaticFiles(directory=settings.base_dir / "static"), name="static")

# 模板引擎


@app.get("/")
async def root():
    """首页重定向"""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/login")


app.include_router(auth_router)
app.include_router(record_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
