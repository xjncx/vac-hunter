from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    file = Path(path)
    if not file.exists():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8000/oauth/callback"
    user_agent: str = ""
    send_enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    database: str = "data/jobsearcher.db"
    admin_user: str = "admin"
    admin_password: str = ""
    public_url: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            client_id=os.getenv("HH_CLIENT_ID", ""),
            client_secret=os.getenv("HH_CLIENT_SECRET", ""),
            redirect_uri=os.getenv("HH_REDIRECT_URI", "http://localhost:8000/oauth/callback"),
            user_agent=os.getenv("HH_USER_AGENT", ""),
            send_enabled=os.getenv("HH_SEND_ENABLED", "false").lower() in {"1", "true", "yes"},
            host=os.getenv("APP_HOST", "127.0.0.1"),
            port=int(os.getenv("APP_PORT", "8000")),
            database=os.getenv("APP_DATABASE", "data/jobsearcher.db"),
            admin_user=os.getenv("ADMIN_USER", "admin"),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            public_url=os.getenv("PUBLIC_URL", ""),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )
