"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import create_db_and_tables

settings = get_settings()

# 确保目录存在
(settings.base_dir / "static").mkdir(exist_ok=True)
(settings.base_dir / "templates").mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
)

# Session 中间件
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# 静态文件
app.mount("/static", StaticFiles(directory=settings.base_dir / "static"), name="static")

# 模板引擎
templates = Jinja2Templates(directory=settings.base_dir / "templates")


@app.get("/")
async def root():
    """首页重定向"""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/login")


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "app": settings.app_name}


# 路由将在后续阶段导入
from app.routers import admin_router, auth_router, dashboard_router, record_router

app.include_router(auth_router)
app.include_router(record_router)
app.include_router(dashboard_router)
app.include_router(admin_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
