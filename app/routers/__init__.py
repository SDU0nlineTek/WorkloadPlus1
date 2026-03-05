"""路由模块"""

from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.record import router as record_router

__all__ = ["auth_router", "record_router", "dashboard_router", "admin_router"]
