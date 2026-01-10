import os
import tomllib
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv


# ------------------------------------------------------------
# Project root finder
# ------------------------------------------------------------
def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Project root not found")

PROJECT_ROOT = find_project_root()


# ------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------
class MistralConfig(BaseModel):
    url: str


class VeniceConfig(BaseModel):
    url: str
    api_key: str | None = None


class TestMistralConfig(BaseModel):
    url: str


class DatabaseTargetConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str | None = None
    database: str
    max_connections: int


class DatabaseConfig(BaseModel):
    local: DatabaseTargetConfig
    remote: DatabaseTargetConfig


class TestDatabaseConfig(BaseModel):
    user: str
    database: str


class SecurityConfig(BaseModel):
    paseto_public_key: str | None = None


class Config(BaseModel):
    mode: str
    mistral: MistralConfig
    database: DatabaseConfig
    test_database: TestDatabaseConfig | None = None
    test_mistral: TestMistralConfig | None = None
    security: SecurityConfig


# ------------------------------------------------------------
# Internal loader
# ------------------------------------------------------------
def _load_config_from(path: Path) -> Config:
    if not path.exists():
        raise RuntimeError(f"Config file not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    cfg = Config(**data)

    # Load secrets
    load_dotenv(PROJECT_ROOT / ".env")
    
    # Local database password
    local_pwd = os.environ.get("PROMPTDEV_USER_PASS")
    if not local_pwd:
        raise RuntimeError("PROMPTDEV_USER_PASS missing in environment")
    cfg.database.local.password = local_pwd

    # Remote database password
    remote_pwd = os.environ.get("SUPABASE_PASSWORD")
    if remote_pwd:
        cfg.database.remote.password = remote_pwd

    return cfg


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------
def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = PROJECT_ROOT / "config.toml"
    return _load_config_from(path)


# ------------------------------------------------------------
# Lazy singleton
# ------------------------------------------------------------
_config: Config | None = None

def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_active_db_config() -> DatabaseTargetConfig:
    """Returns the active database config based on DB_TARGET env var."""
    cfg = get_config()
    
    db_target = os.environ.get("DB_TARGET")
    if not db_target:
        raise RuntimeError("DB_TARGET env var is required (local or remote)")
    
    if db_target == "local":
        return cfg.database.local
    elif db_target == "remote":
        if not cfg.database.remote.password:
            raise RuntimeError("SUPABASE_PASSWORD missing in environment")
        return cfg.database.remote
    else:
        raise RuntimeError(f"Invalid DB_TARGET: {db_target}. Use 'local' or 'remote'")
