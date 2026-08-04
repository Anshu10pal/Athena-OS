from pathlib import Path

from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    SECRET_KEY: str = "dev-secret-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days (feedback phase)
    DATABASE_URL: str = "sqlite:///./athena.db"
    QDRANT_PATH: str = "./qdrant_data"

    # Every logged-in user currently has full write access to the content library --
    # there's no role model yet. This flag is the seam: flip it off (and implement
    # real role checks in app.core.security.require_write_access) once there's more
    # than one user who shouldn't have admin rights over the library.
    SINGLE_USER_MODE: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # avoids the UTF-16 .env trap on Windows


settings = Settings()
