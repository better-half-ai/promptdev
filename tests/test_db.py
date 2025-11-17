import os
import sys
import secrets
import psycopg2
import pytest
from pathlib import Path
from dotenv import load_dotenv

# =====================================================================
# PROJECT ROOT RESOLUTION
# =====================================================================

def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Project root not found")

ROOT = find_project_root()

# Make src/ importable
sys.path.insert(0, str(ROOT / "src"))

# =====================================================================
# IMPORT MIGRATIONS
# =====================================================================

from scripts.migrate import run as run_migrations


# =====================================================================
# DB CONNECTION HELPERS
# =====================================================================

def conn_test():
    """Connect to test database (uses testcontainer if available)."""
    if "TEST_DB_HOST" in os.environ:
        # Use testcontainer
        return psycopg2.connect(
            host=os.environ["TEST_DB_HOST"],
            port=int(os.environ["TEST_DB_PORT"]),
            user=os.environ["TEST_DB_USER"],
            password=os.environ["TEST_DB_PASSWORD"],
            database=os.environ["TEST_DB_NAME"],
        )
    else:
        # Fallback (shouldn't happen with testcontainers)
        raise RuntimeError("No test database connection info available")


# =====================================================================
# APPLY MIGRATIONS TO TEST DB
# =====================================================================

@pytest.fixture(scope="session", autouse=True)
def apply_migrations(postgres_container):
    """Apply migrations to test database."""
    run_migrations()
    yield


# =====================================================================
# CREATE RANDOMIZED TEST TABLES (SAFE, ISOLATED)
# =====================================================================

@pytest.fixture(scope="session")
def tables(postgres_container):
    """
    Creates copies of ALL PromptDev tables with random names so tests
    never touch production tables.
    """

    suffix = secrets.token_hex(8)

    t_system  = f"test_system_prompt_{suffix}"
    t_versions = f"test_prompt_history_{suffix}"
    t_memory  = f"test_user_memory_{suffix}"
    t_history = f"test_conversation_history_{suffix}"
    t_state   = f"test_user_state_{suffix}"

    cx = conn_test()
    cur = cx.cursor()

    # system_prompt
    cur.execute(f"""
        CREATE TABLE {t_system} (
            id SERIAL PRIMARY KEY,
            version INTEGER NOT NULL UNIQUE,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # prompt_version_history
    cur.execute(f"""
        CREATE TABLE {t_versions} (
            id SERIAL PRIMARY KEY,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # user_memory
    cur.execute(f"""
        CREATE TABLE {t_memory} (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # conversation_history
    cur.execute(f"""
        CREATE TABLE {t_history} (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # user_state
    cur.execute(f"""
        CREATE TABLE {t_state} (
            user_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    cx.commit()
    cur.close()
    cx.close()

    yield {
        "system":  t_system,
        "versions": t_versions,
        "memory":  t_memory,
        "history": t_history,
        "state":   t_state,
    }

    # TEARDOWN
    cx = conn_test()
    cur = cx.cursor()

    for t in [t_system, t_versions, t_memory, t_history, t_state]:
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")

    cx.commit()
    cur.close()
    cx.close()


# =====================================================================
# CLEAN TABLES BEFORE EACH TEST
# =====================================================================

@pytest.fixture(autouse=True)
def clean_tables(tables):
    cx = conn_test()
    cur = cx.cursor()

    for t in tables.values():
        cur.execute(f"TRUNCATE {t} CASCADE;")

    cx.commit()
    cur.close()
    cx.close()
    yield


# =====================================================================
# FULL TEST SUITE
# =====================================================================

# -------------------------------
# Connectivity
# -------------------------------

def test_can_connect_test_db():
    cx = conn_test()
    cur = cx.cursor()
    cur.execute("SELECT 1;")
    assert cur.fetchone()[0] == 1
    cur.close()
    cx.close()


# -------------------------------
# Migrations
# -------------------------------

def test_schema_migrations_applied():
    cx = conn_test()
    cur = cx.cursor()
    cur.execute("SELECT version FROM schema_migrations;")
    versions = {v for (v,) in cur.fetchall()}
    # Version is stored as TEXT "001", not INTEGER 1
    assert "001" in versions
    cur.close()
    cx.close()


# -------------------------------
# Schema existence
# -------------------------------

def test_required_tables_exist():
    cx = conn_test()
    cur = cx.cursor()
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public';
    """)
    tables = {t for (t,) in cur.fetchall()}

    assert "system_prompt" in tables
    assert "prompt_version_history" in tables
    assert "user_memory" in tables
    assert "conversation_history" in tables
    assert "user_state" in tables

    cur.close()
    cx.close()


# -------------------------------
# System prompt tests
# -------------------------------

def test_system_prompt_roundtrip(tables):
    tn = tables["system"]
    cx = conn_test()
    cur = cx.cursor()

    cur.execute(f"""
        INSERT INTO {tn} (version, content)
        VALUES (1, 'alpha');
    """)
    cx.commit()

    cur.execute(f"SELECT content FROM {tn} WHERE version=1;")
    assert cur.fetchone()[0] == "alpha"

    cur.close()
    cx.close()


def test_system_prompt_version_history(tables):
    tn = tables["versions"]
    cx = conn_test()
    cur = cx.cursor()

    cur.execute(f"""
        INSERT INTO {tn} (version, content)
        VALUES (1, 'alpha');
    """)
    cx.commit()

    cur.execute(f"SELECT content FROM {tn} WHERE version=1;")
    assert cur.fetchone()[0] == "alpha"

    cur.close()
    cx.close()


# -------------------------------
# User memory tests
# -------------------------------

def test_user_memory_insert_update_delete(tables):
    tn = tables["memory"]
    cx = conn_test()
    cur = cx.cursor()

    # insert
    cur.execute(
        f"INSERT INTO {tn} (user_id, key, value) "
        f"VALUES ('u1','pref','{{\"a\":1}}');"
    )
    cx.commit()

    # read
    cur.execute(
        f"SELECT value FROM {tn} WHERE user_id='u1' AND key='pref';"
    )
    assert cur.fetchone()[0]["a"] == 1

    # update
    cur.execute(
        f"UPDATE {tn} SET value='{{\"a\":2}}' WHERE user_id='u1' AND key='pref';"
    )
    cx.commit()

    cur.execute(
        f"SELECT value FROM {tn} WHERE user_id='u1' AND key='pref';"
    )
    assert cur.fetchone()[0]["a"] == 2

    # delete
    cur.execute(
        f"DELETE FROM {tn} WHERE user_id='u1' AND key='pref';"
    )
    cx.commit()

    cur.execute(
        f"SELECT COUNT(*) FROM {tn} WHERE user_id='u1';"
    )
    assert cur.fetchone()[0] == 0

    cur.close()
    cx.close()


# -------------------------------
# Conversation history tests
# -------------------------------

def test_conversation_history_roundtrip(tables):
    tn = tables["history"]
    cx = conn_test()
    cur = cx.cursor()

    cur.execute(
        f"INSERT INTO {tn} (user_id, role, content) "
        f"VALUES ('u2','user','hello');"
    )
    cx.commit()

    cur.execute(f"SELECT content FROM {tn} WHERE user_id='u2';")
    assert cur.fetchone()[0] == "hello"

    cur.close()
    cx.close()


# -------------------------------
# User state tests
# -------------------------------

def test_user_state_roundtrip(tables):
    tn = tables["state"]
    cx = conn_test()
    cur = cx.cursor()

    cur.execute(
        f"INSERT INTO {tn} (user_id, mode) "
        f"VALUES ('u3','active');"
    )
    cx.commit()

    cur.execute(f"SELECT mode FROM {tn} WHERE user_id='u3';")
    assert cur.fetchone()[0] == "active"

    cur.close()
    cx.close()
