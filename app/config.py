from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
import os


class Settings(BaseModel):
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    upload_root: Path = Path(os.getenv("UPLOAD_ROOT", "./uploads"))
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    app_base_url: str = os.getenv("APP_BASE_URL", "").strip()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "changeme-admin")
    lck_password: str = os.getenv("LCK_PASSWORD", "changeme-lck")
    cse_password: str = os.getenv("CSE_PASSWORD", "changeme-cse")
    session_cookie_secure: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    max_file_size_bytes: int = int(os.getenv("MAX_FILE_SIZE_BYTES", str(2 * 1024 * 1024 * 1024)))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vault.sqlite3"

    @property
    def thumbnail_root(self) -> Path:
        return self.data_dir / "thumbnails"


@lru_cache
def get_settings() -> Settings:
    return Settings()
