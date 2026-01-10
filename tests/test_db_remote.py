"""
Test remote (Supabase) database connection.

Run:
    DB_TARGET=remote pytest tests/test_db_remote.py -v
"""
import os
import pytest
import psycopg2


@pytest.fixture(autouse=True)
def require_remote_target():
    """Skip if DB_TARGET is not 'remote'."""
    if os.environ.get("DB_TARGET") != "remote":
        pytest.skip("DB_TARGET=remote required")


class TestRemoteConnection:
    """Test Supabase connection."""

    def test_direct_connection(self):
        """Direct psycopg2 connection to Supabase."""
        from dotenv import load_dotenv
        from src.config import PROJECT_ROOT
        
        load_dotenv(PROJECT_ROOT / ".env")
        password = os.environ.get("SUPABASE_PASSWORD")
        
        if not password:
            pytest.fail("SUPABASE_PASSWORD not set")

        conn = psycopg2.connect(
            host="aws-1-us-east-2.pooler.supabase.com",
            port=5432,
            user="postgres.hykoamfsyttvteipvsbw",
            password=password,
            database="postgres",
        )
        
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            assert cur.fetchone() == (1,)
        finally:
            conn.close()

    def test_connection_via_config(self):
        """Connection via get_active_db_config."""
        from src.config import get_active_db_config
        
        db_cfg = get_active_db_config()
        
        assert "supabase" in db_cfg.host
        assert db_cfg.password is not None

        conn = psycopg2.connect(
            host=db_cfg.host,
            port=db_cfg.port,
            user=db_cfg.user,
            password=db_cfg.password,
            database=db_cfg.database,
        )
        
        try:
            cur = conn.cursor()
            cur.execute("SELECT current_database(), current_user;")
            db, user = cur.fetchone()
            assert db == "postgres"
        finally:
            conn.close()

    def test_connection_via_pool(self):
        """Connection via db pool."""
        from db.db import get_conn, put_conn, close_pool
        
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            assert "PostgreSQL" in version
            put_conn(conn)
        finally:
            close_pool()
