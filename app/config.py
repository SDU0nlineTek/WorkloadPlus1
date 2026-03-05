"""应用配置管理"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    debug: bool = True
    # 应用名称
    app_name: str = "工作量+1"

    # 数据库配置
    database_url: str = "sqlite:///./workload.db"

    # Session 密钥 (生产环境务必修改)
    secret_key: str = "change-me-in-production-2024"

    # 项目活跃判定周期（月）
    active_project_window_months: int = 3

    # 基础路径
    base_dir: Path = Path(__file__).parent

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = Settings()
