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
# Secrets are NOT expected in TOML
# ------------------------------------------------------------
class MistralConfig(BaseModel):
    url: str


class VeniceConfig(BaseModel):
    url: str
    api_key: str | None = None  # injected from .env


class TestMistralConfig(BaseModel):
    url: str


class DatabaseConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str | None = None     # injected from .env
    database: str
    max_connections: int


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
# Internal loader (production + tests)
# Inject password from .env ONLY
# ------------------------------------------------------------
def _load_config_from(path: Path) -> Config:
    if not path.exists():
        raise RuntimeError(f"Config file not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    cfg = Config(**data)

    # Load secrets
    load_dotenv(PROJECT_ROOT / ".env")
    pwd = os.environ.get("PROMPTDEV_USER_PASS")
    if not pwd:
        raise RuntimeError("PROMPTDEV_USER_PASS missing in environment")

    # Inject secret into proper model location
    cfg.database.password = pwd

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