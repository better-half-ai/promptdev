import sys
import os
from pathlib import Path
import pytest
from testcontainers.postgres import PostgresContainer

# Add the project's src directory to Python path
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def postgres_container():
    """Start ephemeral Postgres container for tests."""
    with PostgresContainer("postgres:16", username="test_user", password="test_pass", dbname="test_db") as postgres:
        # Set environment variables for test database connection
        os.environ["TEST_DB_HOST"] = postgres.get_container_host_ip()
        os.environ["TEST_DB_PORT"] = str(postgres.get_exposed_port(5432))
        os.environ["TEST_DB_USER"] = postgres.username
        os.environ["TEST_DB_PASSWORD"] = postgres.password
        os.environ["TEST_DB_NAME"] = postgres.dbname
        os.environ["USE_TEST_DB"] = "1"
        
        yield postgres
        
        # Cleanup environment variables
        for key in ["TEST_DB_HOST", "TEST_DB_PORT", "TEST_DB_USER", "TEST_DB_PASSWORD", "TEST_DB_NAME"]:
            os.environ.pop(key, None)
