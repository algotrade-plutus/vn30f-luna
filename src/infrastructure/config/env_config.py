"""Infrastructure: Environment Configuration Loader.
Reads .env securely without leaking secrets.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(env_path: Path | None = None) -> dict[str, str]:
    """Parse .env file into os.environ if not already present."""
    if env_path is None:
        # Search parent directories for .env
        cur = Path(__file__).resolve().parent
        for _ in range(5):
            candidate = cur / ".env"
            if candidate.is_file():
                env_path = candidate
                break
            cur = cur.parent

    env_vars: dict[str, str] = {}
    if env_path and env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            env_vars[key] = val
            if key not in os.environ:
                os.environ[key] = val
    return env_vars


class DatabaseConfig:
    """PostgreSQL configuration values."""
    def __init__(self) -> None:
        load_env()
        self.host: str = os.getenv("ALGOTRADE_DB_HOST", "api.algotrade.vn")
        self.port: int = int(os.getenv("ALGOTRADE_DB_PORT", "5432"))
        self.database: str = os.getenv("ALGOTRADE_DB_NAME", "algotradeDB")
        self.user: str = os.getenv("ALGOTRADE_DB_USER", "intern_read_only")
        self.password: str = os.getenv("ALGOTRADE_DB_PASSWORD", "")
