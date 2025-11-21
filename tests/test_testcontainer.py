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
            "user_state"
        ]
        
        for table in expected:
            assert table in tables, f"Missing table: {table}"


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
    # Connection automatically returned to pool


def test_connection_pool_reuses_connections(db_module):
    """Test that connection pool reuses connections."""
    conn1 = db_module.get_conn()
    conn1_id = id(conn1)
    db_module.put_conn(conn1)
    
    conn2 = db_module.get_conn()
    conn2_id = id(conn2)
    db_module.put_conn(conn2)
    
    assert conn1_id == conn2_id, "Connection pool should reuse connections"


def test_cleanup_isolates_tests(db_conn):
    """Test that cleanup between tests maintains isolation."""
    # Insert test data
    with db_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO system_prompt (name, content, current_version)
            VALUES ('isolation_test', 'test content', 1)
        """)
        db_conn.commit()
        
        # Verify inserted
        cur.execute("SELECT COUNT(*) FROM system_prompt WHERE name = 'isolation_test'")
        assert cur.fetchone()[0] == 1
    
    # db_module fixture will truncate after this test


def test_config_uses_testcontainer_settings(db_module):
    """Test that config.py correctly uses testcontainer settings."""
    from src.config import get_config
    
    config = get_config()
    
    # Should use test_database section with dynamic port from testcontainer
    assert config.database.host == "localhost"
    assert config.database.port == int(os.environ["TEST_DB_PORT"])
    assert config.database.user == "test_user"
    assert config.database.database == "test_db"


def test_multiple_connections_work_independently(db_module):
    """Test that multiple connections can be acquired and used independently."""
    conn1 = db_module.get_conn()
    conn2 = db_module.get_conn()
    
    try:
        with conn1.cursor() as cur:
            cur.execute("SELECT 'conn1' as id")
            assert cur.fetchone()[0] == 'conn1'
        
        with conn2.cursor() as cur:
            cur.execute("SELECT 'conn2' as id")
            assert cur.fetchone()[0] == 'conn2'
    finally:
        db_module.put_conn(conn1)
        db_module.put_conn(conn2)