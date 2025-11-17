from src.db import get_conn, put_conn

def list_tables():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        return [row[0] for row in cur.fetchall()]
    finally:
        put_conn(conn)


def count_rows(table):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table};")
        return cur.fetchone()[0]
    finally:
        put_conn(conn)


def dump_system_prompt_versions():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT version, created_at FROM prompt_version_history ORDER BY version DESC;")
        return cur.fetchall()
    finally:
        put_conn(conn)


def dump_memory_for(user_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM user_memory WHERE user_id = %s;", (user_id,))
        return cur.fetchall()
    finally:
        put_conn(conn)


def dump_history_for(user_id, limit=20):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT role, content, created_at
            FROM conversation_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s;
        """, (user_id, limit))
        return cur.fetchall()
    finally:
        put_conn(conn)
