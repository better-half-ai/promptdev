import psycopg2
import psycopg2.pool

from src.config import get_active_db_config

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def init_pool():
    global _pool
    if _pool is None:
        db_cfg = get_active_db_config()

        _pool = psycopg2.pool.SimpleConnectionPool(
            1,
            db_cfg.max_connections,
            host=db_cfg.host,
            port=db_cfg.port,
            user=db_cfg.user,
            password=db_cfg.password,
            database=db_cfg.database,
        )
    return _pool


def get_conn():
    init_pool()
    return _pool.getconn()


def put_conn(conn):
    if _pool:
        _pool.putconn(conn)


def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
