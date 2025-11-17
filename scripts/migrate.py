#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import psycopg2

# Add src to path for config access
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from src.config import get_config

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_migration_conn():
    """Get connection to the appropriate database based on environment."""
    cfg = get_config()
    
    # Check if we should use test database
    use_test = os.environ.get("USE_TEST_DB", "").lower() in ("1", "true", "yes")
    
    if use_test and "TEST_DB_HOST" in os.environ:
        # Use testcontainer connection info (from conftest.py)
        return psycopg2.connect(
            host=os.environ["TEST_DB_HOST"],
            port=int(os.environ["TEST_DB_PORT"]),
            user=os.environ["TEST_DB_USER"],
            password=os.environ["TEST_DB_PASSWORD"],
            database=os.environ["TEST_DB_NAME"],
        )
    elif use_test:
        # Use test database from config (for manual test DB)
        test_cfg = getattr(cfg, 'test_database', None)
        if test_cfg:
            return psycopg2.connect(
                host=getattr(test_cfg, 'host', cfg.database.host),
                port=getattr(test_cfg, 'port', cfg.database.port),
                user=test_cfg.user,
                password=cfg.database.password,
                database=test_cfg.database,
            )
        else:
            # Fallback to production config with test DB name
            return psycopg2.connect(
                host=cfg.database.host,
                port=cfg.database.port,
                user=cfg.database.user,
                password=cfg.database.password,
                database="promptdev_test",
            )
    else:
        # Use production database configuration
        return psycopg2.connect(
            host=cfg.database.host,
            port=cfg.database.port,
            user=cfg.database.user,
            password=cfg.database.password,
            database=cfg.database.database,
        )


def run():
    migration_files = sorted(
        MIGRATIONS_DIR.glob("*.sql"),
        key=lambda p: int(p.name.split("_")[0])
    )

    conn = get_migration_conn()
    try:
        cur = conn.cursor()

        # Ensure schema_migrations table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY
            );
        """)
        conn.commit()

        # Get applied migrations
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

        # Apply unapplied migrations
        for mf in migration_files:
            version = mf.stem.split("_")[0]
            if version in applied:
                continue  # already applied

            with mf.open("r") as f:
                sql = f.read()

            try:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,)
                )
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise RuntimeError(f"Migration failed: {mf.name}") from e

    finally:
        conn.close()


if __name__ == "__main__":
    run()
