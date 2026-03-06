"""应用配置管理"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    debug: bool
    app_name: str = "工作量+1"
    database_url: str
    secret_key: str
    session_cookie: str
    session_max_age: int
    # 基础路径（app 目录）
    base_dir: Path = Path(__file__).resolve().parent.parent

    model_config = SettingsConfigDict(
        env_file=base_dir.parent / ".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore
