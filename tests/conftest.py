import sys
import os
from pathlib import Path
import pytest
import psycopg2
import asyncio
from testcontainers.postgres import PostgresContainer
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# Load .env file for API keys
load_dotenv(ROOT / ".env")

LLM_BACKENDS = {
    "local": "http://127.0.0.1:8080",
    "venice": os.environ.get("VENICE_API_URL", "https://api.venice.ai/api/v1"),
}


def pytest_addoption(parser):
    parser.addoption("--llm", action="store", help="LLM backend: 'local' or 'venice' (REQUIRED)")


@pytest.fixture(scope="session")
def llm_backend(request):
    backend = request.config.getoption("--llm")
    if not backend:
        pytest.exit("ERROR: --llm is required. Use --llm=local or --llm=venice", returncode=1)
    if backend not in LLM_BACKENDS:
        pytest.exit(f"ERROR: Invalid --llm value '{backend}'. Use 'local' or 'venice'", returncode=1)
    os.environ["LLM_BACKEND"] = backend
    return backend


@pytest.fixture(scope="session")
def llm_url(llm_backend):
    return LLM_BACKENDS[llm_backend]


@pytest.fixture(scope="session")
def mistral_available(llm_backend, llm_url):
    from src.llm_client import health_check, ClientConfig, LLMBackend
    
    if llm_backend == "venice":
        config = ClientConfig(
            base_url=llm_url,
            backend=LLMBackend.VENICE,
            api_key=os.environ.get("VENICE_API_KEY", ""),
            model=os.environ.get("VENICE_MODEL", "mistral-31-24b")
        )
    else:
        config = ClientConfig(base_url=llm_url, backend=LLMBackend.LOCAL)
    
    try:
        return asyncio.run(health_check(config))
    except:
        return False


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16", username="test_user", password="test_pass", dbname="test_db") as postgres:
        os.environ["TEST_DB_HOST"] = postgres.get_container_host_ip()
        os.environ["TEST_DB_PORT"] = str(postgres.get_exposed_port(5432))
        os.environ["TEST_DB_USER"] = postgres.username
        os.environ["TEST_DB_PASSWORD"] = postgres.password
        os.environ["TEST_DB_NAME"] = postgres.dbname
        os.environ["USE_TEST_DB"] = "1"
        os.environ["DB_TARGET"] = "local"  # Tests use local config pointing to testcontainer
        yield postgres
        for key in ["TEST_DB_HOST", "TEST_DB_PORT", "TEST_DB_USER", "TEST_DB_PASSWORD", "TEST_DB_NAME", "USE_TEST_DB", "DB_TARGET"]:
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
    for migration in sorted(migrations_dir.glob("*.sql")):
        with migration.open("r") as f:
            with conn.cursor() as cur:
                cur.execute(f.read())
        conn.commit()
    conn.close()
    yield


@pytest.fixture
def db_module(postgres_container, test_db, llm_url):
    import db.db as db_module
    import src.config
    from src.config import Config, MistralConfig, TestMistralConfig, DatabaseConfig, DatabaseTargetConfig, SecurityConfig

    db_module._pool = None

    # Create test DB config - both local and remote point to testcontainer
    test_db_config = DatabaseTargetConfig(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
        max_connections=10
    )

    test_config = Config(
        mode="test",
        mistral=MistralConfig(url=llm_url),
        test_mistral=TestMistralConfig(url=llm_url),
        database=DatabaseConfig(
            local=test_db_config,
            remote=test_db_config  # Both point to testcontainer for tests
        ),
        test_database=None,
        security=SecurityConfig()
    )

    src.config._config = test_config

    preserve_tables = {'guardrail_configs'}
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                if table not in preserve_tables:
                    cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        conn.close()

    yield db_module

    if db_module._pool:
        db_module._pool = None
    src.config._config = None


@pytest.fixture
def db_conn(db_module):
    conn = db_module.get_conn()
    yield conn
    db_module.put_conn(conn)
