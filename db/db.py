import psycopg2
import psycopg2.pool

from src.config import get_config

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def init_pool():
    global _pool
    if _pool is None:
        cfg = get_config()

        _pool = psycopg2.pool.SimpleConnectionPool(
            1,
            cfg.database.max_connections,
            host=cfg.database.host,
            port=cfg.database.port,
            user=cfg.database.user,
            password=cfg.database.password,
            database=cfg.database.database,
        )
    return _pool


def get_conn():
    init_pool()
    return _pool.getconn()


def put_conn(conn):
    if _pool:
        _pool.putconn(conn)


def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
