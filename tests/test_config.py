import tomllib
from pathlib import Path

import pytest

from src.config import Config, MistralConfig, DatabaseConfig, SecurityConfig


def _write_config(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(content, encoding="utf-8")
    return cfg


def _load_config_from(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Config(**data)


def test_valid_standalone_config(tmp_path: Path):
    content = """
mode = "standalone"

[mistral]
url = "http://mistral:8080"

[database]
host = "localhost"
port = 5432
user = "ybh_user"
password = "ybh_dev_pass"
database = "ybh_promptdev"
max_connections = 10

[remote_database]
host = "remote.example.com"
port = 5432
user = "remote_user"
password = "remote_pass"
database = "remote_db"
max_connections = 10

[venice]
url = "https://api.venice.ai/api/v1"
model = "mistral-31-24b"

[security]
paseto_public_key = ""
"""
    cfg_path = _write_config(tmp_path, content)
    cfg = _load_config_from(cfg_path)

    assert cfg.mode == "standalone"
    assert isinstance(cfg.mistral, MistralConfig)
    assert cfg.mistral.url == "http://mistral:8080"

    assert isinstance(cfg.database, DatabaseConfig)
    assert cfg.database.host == "localhost"
    assert cfg.database.port == 5432
    assert cfg.database.user == "ybh_user"
    assert cfg.database.password == "ybh_dev_pass"
    assert cfg.database.database == "ybh_promptdev"
    assert cfg.database.max_connections == 10

    assert isinstance(cfg.security, SecurityConfig)
    assert cfg.security.paseto_public_key == ""


def test_valid_gateway_config(tmp_path: Path):
    content = """
mode = "gateway"

[mistral]
url = "http://mistral:8080"

[database]
host = "localhost"
port = 5432
user = "ybh_user"
password = "ybh_dev_pass"
database = "ybh_promptdev"
max_connections = 10

[remote_database]
host = "remote.example.com"
port = 5432
user = "remote_user"
password = "remote_pass"
database = "remote_db"
max_connections = 10

[venice]
url = "https://api.venice.ai/api/v1"
model = "mistral-31-24b"

[security]
paseto_public_key = "v4.public.DUMMY"
"""
    cfg_path = _write_config(tmp_path, content)
    cfg = _load_config_from(cfg_path)

    assert cfg.mode == "gateway"
    assert cfg.security.paseto_public_key.startswith("v4.public.")


def test_missing_sections_fail(tmp_path: Path):
    content = """
mode = "standalone"
"""
    cfg_path = _write_config(tmp_path, content)

    with pytest.raises(Exception):
        _load_config_from(cfg_path)


def test_invalid_toml_raises(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text(
        """
mode = "standalone"
[mistral
url = "oops"
""",
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        with bad.open("rb") as f:
            tomllib.load(f)


def test_type_validation_for_database(tmp_path: Path):
    content = """
mode = "standalone"

[mistral]
url = "http://mistral:8080"

[database]
host = "localhost"
port = "not-an-int"
user = "ybh_user"
password = "ybh_dev_pass"
database = "ybh_promptdev"
max_connections = 10

[security]
paseto_public_key = ""
"""
    cfg_path = _write_config(tmp_path, content)

    with pytest.raises(Exception):
        _load_config_from(cfg_path)
