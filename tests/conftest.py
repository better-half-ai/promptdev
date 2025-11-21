import sys
import os
from pathlib import Path
import pytest
import psycopg2
from testcontainers.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16", username="test_user", password="test_pass", dbname="test_db") as postgres:
        os.environ["TEST_DB_HOST"] = postgres.get_container_host_ip()
        os.environ["TEST_DB_PORT"] = str(postgres.get_exposed_port(5432))
        os.environ["TEST_DB_USER"] = postgres.username
        os.environ["TEST_DB_PASSWORD"] = postgres.password
        os.environ["TEST_DB_NAME"] = postgres.dbname
        os.environ["USE_TEST_DB"] = "1"
        yield postgres
        for key in ["TEST_DB_HOST", "TEST_DB_PORT", "TEST_DB_USER", "TEST_DB_PASSWORD", "TEST_DB_NAME", "USE_TEST_DB"]:
            os.environ.pop(key, None)


@pytest.fixture(scope="session")
def migrations_dir():
    return ROOT / "migrations"


@pytest.fixture(scope="session")
def test_db(postgres_container, migrations_dir):
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    for migration in ["001_init.sql", "002_prompts_schema.sql", "003_guardrails_schema.sql", "004_telemetry_schema.sql"]:
        migration_file = migrations_dir / migration
        if migration_file.exists():
            with migration_file.open("r") as f:
                with conn.cursor() as cur:
                    cur.execute(f.read())
            conn.commit()
    conn.close()
    yield


@pytest.fixture
def db_module(postgres_container, test_db):
    import db.db as db_module
    import src.config
    from src.config import Config, MistralConfig, DatabaseConfig, SecurityConfig
    
    # Reset pool
    db_module._pool = None
    
    # Create testcontainer config
    test_config = Config(
        mode="test",
        mistral=MistralConfig(url="http://localhost:8080"),
        database=DatabaseConfig(
            host=os.environ["TEST_DB_HOST"],
            port=int(os.environ["TEST_DB_PORT"]),
            user=os.environ["TEST_DB_USER"],
            password=os.environ["TEST_DB_PASSWORD"],
            database=os.environ["TEST_DB_NAME"],
            max_connections=10
        ),
        test_database=None,
        security=SecurityConfig()
    )
    
    # Patch get_config to return test config
    original_get_config = src.config.get_config
    src.config._config = test_config
    
    yield db_module
    
    # Cleanup
    if db_module._pool:
        conn = db_module.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE conversation_history CASCADE")
                cur.execute("TRUNCATE TABLE user_memory CASCADE")
                cur.execute("TRUNCATE TABLE user_state CASCADE")
                cur.execute("TRUNCATE TABLE system_prompt RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE prompt_version_history CASCADE")
                cur.execute("TRUNCATE TABLE llm_requests CASCADE")
                cur.execute("TRUNCATE TABLE user_activity CASCADE")
                cur.execute("TRUNCATE TABLE metric_snapshots CASCADE")
            conn.commit()
        finally:
            db_module.put_conn(conn)
        db_module._pool = None
    
    # Restore original config
    src.config._config = None


@pytest.fixture
def db_conn(db_module):
    conn = db_module.get_conn()
    yield conn
    db_module.put_conn(conn)
