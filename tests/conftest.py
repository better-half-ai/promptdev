"""
Pytest configuration and fixtures for PromptDev tests.

Provides:
- Testcontainer PostgreSQL database
- Automatic migration running
- Per-test database cleanup
- Authenticated test clients
"""

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
sys.path.insert(0, str(ROOT))

# Load .env file for API keys
load_dotenv(ROOT / ".env")


# ============================================================
# Test Constants
# ============================================================

TEST_ADMIN_EMAIL = "testadmin@test.local"
TEST_ADMIN_PASSWORD = "testpassword123"
TEST_ADMIN2_EMAIL = "secondadmin@test.local"
TEST_ADMIN2_PASSWORD = "testpassword456"
TEST_SUPER_EMAIL = "super@test.local"
TEST_SUPER_PASSWORD = "supersecret123"

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
    """Start a PostgreSQL testcontainer for the test session."""
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
    """Run all migrations once per test session."""
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    
    # Run all migrations in order
    migration_files = sorted(migrations_dir.glob("*.sql"))
    print(f"\n=== Running {len(migration_files)} migrations ===")
    for migration in migration_files:
        print(f"  Running: {migration.name}")
        with migration.open("r") as f:
            sql = f.read()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"  ERROR in {migration.name}: {e}")
                raise
    
    # Verify schema
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'system_prompt' AND column_name = 'tenant_id'
        """)
        if not cur.fetchone():
            cur.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'system_prompt' ORDER BY ordinal_position
            """)
            cols = [r[0] for r in cur.fetchall()]
            raise RuntimeError(f"Schema error: tenant_id missing. Columns: {cols}")
    
    conn.close()
    print("=== Migrations complete ===\n")
    yield


@pytest.fixture
def db_module(postgres_container, test_db, llm_url):
    """Database module with clean state per test."""
    import db.db as db_module
    import src.config
    from src.config import Config, MistralConfig, TestMistralConfig, DatabaseConfig, SecurityConfig

    # Reset connection pool
    db_module._pool = None

    # Create test config pointing to testcontainer
    test_config = Config(
        mode="test",
        mistral=MistralConfig(url=llm_url),
        test_mistral=TestMistralConfig(url=llm_url),
        database=DatabaseConfig(
            host=os.environ["TEST_DB_HOST"],
            port=int(os.environ["TEST_DB_PORT"]),
            user=os.environ["TEST_DB_USER"],
            password=os.environ["TEST_DB_PASSWORD"],
            database=os.environ["TEST_DB_NAME"],
            max_connections=10
        ),
        security=SecurityConfig()
    )

    # Inject config singleton
    src.config._config = test_config

    # Clean all tables before each test
    preserve_tables = {'schema_migrations', 'guardrail_configs'}
    
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

    # Cleanup
    if db_module._pool:
        db_module._pool = None
    src.config._config = None


@pytest.fixture
def db_conn(db_module):
    """Database connection for direct SQL access in tests."""
    conn = db_module.get_conn()
    yield conn
    db_module.put_conn(conn)


@pytest.fixture
def test_admin(db_module):
    """Create a test admin and return Admin object."""
    from src.auth import create_admin, Admin
    
    admin_id = create_admin(TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD)
    return Admin(id=admin_id, email=TEST_ADMIN_EMAIL, tenant_id=admin_id, is_super=False)


@pytest.fixture
def test_admin_token(test_admin):
    """Create session token for test admin."""
    from src.auth import create_session_token
    
    return create_session_token(
        admin_id=test_admin.id,
        email=test_admin.email,
        is_super=False
    )


@pytest.fixture
def auth_client(db_module, test_admin, test_admin_token):
    """Authenticated test client for admin routes."""
    from fastapi.testclient import TestClient
    from src.main import app
    from src.auth import SESSION_COOKIE_NAME
    
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, test_admin_token)
    
    return client


@pytest.fixture
def super_admin_client(db_module):
    """Super admin authenticated test client."""
    from fastapi.testclient import TestClient
    from src.main import app
    from src.auth import create_session_token, SESSION_COOKIE_NAME
    
    token = create_session_token(
        admin_id=None,
        email=TEST_SUPER_EMAIL,
        is_super=True
    )
    
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    
    return client


@pytest.fixture
def second_admin(db_module):
    """Create a second admin for tenant isolation tests."""
    from src.auth import create_admin, Admin
    
    admin_id = create_admin(TEST_ADMIN2_EMAIL, TEST_ADMIN2_PASSWORD)
    return Admin(id=admin_id, email=TEST_ADMIN2_EMAIL, tenant_id=admin_id, is_super=False)


@pytest.fixture
def second_admin_client(db_module, second_admin):
    """Test client for second admin."""
    from fastapi.testclient import TestClient
    from src.main import app
    from src.auth import create_session_token, SESSION_COOKIE_NAME
    
    token = create_session_token(
        admin_id=second_admin.id,
        email=second_admin.email,
        is_super=False
    )
    
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    
    return client
