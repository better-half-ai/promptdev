"""
Configuration management for PromptDev.
"""

import os
import tomllib
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv


def find_project_root() -> Path:
    """Find project root by looking for pyproject.toml."""
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Project root not found")


PROJECT_ROOT = find_project_root()


class MistralConfig(BaseModel):
    url: str


class TestMistralConfig(BaseModel):
    url: str


class VeniceConfig(BaseModel):
    url: str
    model: str


class DatabaseConfig(BaseModel):
    host: str
    port: int
    user: str
    password: Optional[str] = None
    database: str
    max_connections: int = 10


class SecurityConfig(BaseModel):
    paseto_public_key: Optional[str] = None


class Config(BaseModel):
    mode: str
    mistral: MistralConfig
    database: DatabaseConfig
    remote_database: DatabaseConfig
    test_mistral: Optional[TestMistralConfig] = None
    venice: VeniceConfig
    security: SecurityConfig = SecurityConfig()


def _load_config_from(path: Path) -> Config:
    """Load configuration from TOML file."""
    if not path.exists():
        raise RuntimeError(f"Config file not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    cfg = Config(**data)

    # Load secrets from environment
    load_dotenv(PROJECT_ROOT / ".env")
    
    # Local DB password
    pwd = os.environ.get("PROMPTDEV_USER_PASS")
    if pwd:
        cfg.database.password = pwd
    
    # Remote DB password
    supabase_pwd = os.environ.get("SUPABASE_PASSWORD")
    if supabase_pwd:
        cfg.remote_database.password = supabase_pwd
    
    # Handle DB_TARGET for CLI tools running outside Docker
    db_target = os.environ.get("DB_TARGET")
    if db_target == "local":
        # CLI running on host - use localhost instead of docker hostname
        cfg.database.host = "localhost"
    elif db_target == "remote":
        # Use remote database config
        cfg.database = DatabaseConfig(
            host=cfg.remote_database.host,
            port=cfg.remote_database.port,
            user=cfg.remote_database.user,
            password=cfg.remote_database.password,
            database=cfg.remote_database.database,
            max_connections=cfg.remote_database.max_connections,
        )

    return cfg


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from default or specified path."""
    if path is None:
        path = PROJECT_ROOT / "config.toml"
    return _load_config_from(path)


_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration singleton."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_active_db_config() -> DatabaseConfig:
    """Return the active database configuration."""
    return get_config().database
