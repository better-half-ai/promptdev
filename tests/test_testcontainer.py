"""
Validate testcontainer infrastructure from conftest.py.
Tests that all fixtures work correctly before using in other tests.
"""

import pytest
import os


def test_postgres_container_sets_env_vars(postgres_container):
    """Test postgres_container fixture sets environment variables."""
    assert os.environ.get("TEST_DB_HOST") is not None
    assert os.environ.get("TEST_DB_PORT") is not None
    assert os.environ.get("TEST_DB_USER") == "test_user"
    assert os.environ.get("TEST_DB_PASSWORD") == "test_pass"
    assert os.environ.get("TEST_DB_NAME") == "test_db"
    assert os.environ.get("USE_TEST_DB") == "1"


def test_migrations_ran_successfully(test_db, db_conn):
    """Test that migrations created all expected tables."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        expected = [
            "system_prompt",
            "prompt_version_history",
            "conversation_history",
            "user_memory",
            "user_state",
            "admins",
            "admin_audit_log",
            "guardrail_configs",
        ]
        
        for table in expected:
            assert table in tables, f"Missing table: {table}"
        
        # Verify tenant_id column exists on system_prompt
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'system_prompt' AND column_name = 'tenant_id'
        """)
        assert cur.fetchone() is not None, "Missing tenant_id column on system_prompt"


def test_db_module_provides_working_connection(db_module):
    """Test db_module fixture provides working connection pool."""
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 as test")
            assert cur.fetchone()[0] == 1
    finally:
        db_module.put_conn(conn)


def test_db_conn_auto_managed(db_conn):
    """Test db_conn fixture auto-manages connection lifecycle."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT 2 + 2 as sum")
        assert cur.fetchone()[0] == 4


def test_config_uses_testcontainer_settings(db_module):
    """Test that config.py correctly uses testcontainer settings."""
    from src.config import get_config, get_active_db_config
    
    config = get_config()
    db_config = get_active_db_config()
    
    assert db_config.host == os.environ["TEST_DB_HOST"]
    assert db_config.port == int(os.environ["TEST_DB_PORT"])
    assert db_config.user == os.environ["TEST_DB_USER"]
    assert db_config.database == os.environ["TEST_DB_NAME"]


def test_cleanup_isolates_tests(db_conn):
    """Test that cleanup between tests maintains isolation."""
    with db_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO system_prompt (name, content, current_version)
            VALUES ('isolation_test', 'test content', 1)
        """)
        db_conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM system_prompt WHERE name = 'isolation_test'")
        assert cur.fetchone()[0] == 1
