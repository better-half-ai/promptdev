"""
Telemetry module for metrics collection and aggregation.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass
import psycopg2.extras

from db.db import get_conn, put_conn

logger = logging.getLogger(__name__)


def _tid(tenant_id: Optional[int]) -> int:
    """Convert None tenant_id to 0 for SQL operations."""
    return tenant_id if tenant_id is not None else 0


@dataclass
class DashboardStats:
    """Aggregated statistics for dashboard display."""
    active_users_today: int
    active_users_hour: int
    total_messages_today: int
    messages_per_hour: float
    avg_response_time_ms: float
    error_rate_percent: float
    top_templates: list[dict]


def track_llm_request(
    user_id: str,
    response_time_ms: int,
    template_name: Optional[str] = None,
    request_tokens: Optional[int] = None,
    response_tokens: Optional[int] = None,
    error: Optional[str] = None,
    tenant_id: Optional[int] = None
) -> int:
    """Track an LLM request event."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            total_tokens = None
            if request_tokens is not None and response_tokens is not None:
                total_tokens = request_tokens + response_tokens
            
            cur.execute(
                """
                INSERT INTO llm_requests (
                    tenant_id, user_id, template_name, response_time_ms,
                    request_tokens, response_tokens, total_tokens, error
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (_tid(tenant_id), user_id, template_name, response_time_ms,
                 request_tokens, response_tokens, total_tokens, error)
            )
            request_id = cur.fetchone()[0]
            
            cur.execute(
                """
                INSERT INTO user_activity (tenant_id, user_id, total_messages, total_errors)
                VALUES (%s, %s, 1, %s)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                    last_seen = NOW(),
                    total_messages = user_activity.total_messages + 1,
                    total_errors = user_activity.total_errors + EXCLUDED.total_errors
                """,
                (_tid(tenant_id), user_id, 1 if error else 0)
            )
            
            conn.commit()
            return request_id
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to track LLM request: {e}")
        raise
    finally:
        put_conn(conn)


def aggregate_metrics(tenant_id: Optional[int] = None) -> None:
    """Aggregate metrics for current hour and day."""
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        with conn.cursor() as cur:
            # Hourly metrics
            cur.execute(
                """
                SELECT 
                    COUNT(*) as messages,
                    AVG(response_time_ms) FILTER (WHERE error IS NULL)::INTEGER as avg_response,
                    COUNT(*) FILTER (WHERE error IS NOT NULL)::FLOAT / NULLIF(COUNT(*), 0) * 100 as error_rate
                FROM llm_requests 
                WHERE tenant_id = %s AND created_at >= %s AND created_at < %s
                """,
                (_tid(tenant_id), hour_start, hour_start + timedelta(hours=1))
            )
            row = cur.fetchone()
            hourly_value = {
                "messages": row[0],
                "avg_response_time_ms": row[1] or 0,
                "error_rate_percent": row[2] or 0.0
            }
            
            cur.execute(
                """
                INSERT INTO metric_snapshots (tenant_id, metric_name, time_window, window_start, value)
                VALUES (%s, 'hourly_summary', 'hour', %s, %s)
                ON CONFLICT (tenant_id, metric_name, time_window, window_start) 
                DO UPDATE SET value = EXCLUDED.value, created_at = NOW()
                """,
                (_tid(tenant_id), hour_start, psycopg2.extras.Json(hourly_value))
            )
            
            # Daily metrics
            cur.execute(
                """
                SELECT 
                    COUNT(*) as messages,
                    COUNT(DISTINCT user_id) as active_users
                FROM llm_requests 
                WHERE tenant_id = %s AND created_at >= %s
                """,
                (_tid(tenant_id), day_start)
            )
            row = cur.fetchone()
            messages_today, active_users = row[0], row[1]
            
            cur.execute(
                """
                SELECT template_name, COUNT(*) as count
                FROM llm_requests
                WHERE tenant_id = %s AND created_at >= %s AND template_name IS NOT NULL
                GROUP BY template_name
                ORDER BY count DESC
                LIMIT 5
                """,
                (_tid(tenant_id), day_start)
            )
            top_templates = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]
            
            daily_value = {
                "messages": messages_today,
                "active_users": active_users,
                "top_templates": top_templates
            }
            
            cur.execute(
                """
                INSERT INTO metric_snapshots (tenant_id, metric_name, time_window, window_start, value)
                VALUES (%s, 'daily_summary', 'day', %s, %s)
                ON CONFLICT (tenant_id, metric_name, time_window, window_start)
                DO UPDATE SET value = EXCLUDED.value, created_at = NOW()
                """,
                (_tid(tenant_id), day_start, psycopg2.extras.Json(daily_value))
            )
            
            conn.commit()
            logger.info(f"Aggregated metrics for {hour_start}")
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to aggregate metrics: {e}")
        raise
    finally:
        put_conn(conn)


def get_dashboard_stats(tenant_id: Optional[int] = None) -> DashboardStats:
    """Get aggregated statistics for the operator dashboard."""
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        
        with conn.cursor() as cur:
            # Try cached daily metrics
            cur.execute(
                """
                SELECT value FROM metric_snapshots
                WHERE tenant_id = %s AND metric_name = 'daily_summary' 
                AND time_window = 'day'
                AND window_start = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_tid(tenant_id), day_start)
            )
            row = cur.fetchone()
            
            if row:
                daily = row[0]
                active_users_today = daily.get("active_users", 0)
                total_messages_today = daily.get("messages", 0)
                top_templates = daily.get("top_templates", [])
            else:
                # Fallback
                cur.execute(
                    "SELECT COUNT(DISTINCT user_id), COUNT(*) FROM llm_requests WHERE tenant_id = %s AND created_at >= %s",
                    (_tid(tenant_id), day_start)
                )
                row = cur.fetchone()
                active_users_today, total_messages_today = row[0], row[1]
                top_templates = []
            
            # Try cached hourly metrics
            cur.execute(
                """
                SELECT value FROM metric_snapshots
                WHERE tenant_id = %s AND metric_name = 'hourly_summary'
                AND time_window = 'hour'
                AND window_start = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_tid(tenant_id), hour_start)
            )
            row = cur.fetchone()
            
            if row:
                hourly = row[0]
                messages_hour = hourly.get("messages", 0)
                avg_response_time = hourly.get("avg_response_time_ms", 0.0)
                error_rate = hourly.get("error_rate_percent", 0.0)
            else:
                # Fallback
                cur.execute(
                    """
                    SELECT 
                        COUNT(*),
                        AVG(response_time_ms) FILTER (WHERE error IS NULL)::INTEGER,
                        COUNT(*) FILTER (WHERE error IS NOT NULL)::FLOAT / NULLIF(COUNT(*), 0) * 100
                    FROM llm_requests
                    WHERE tenant_id = %s AND created_at >= %s
                    """,
                    (_tid(tenant_id), hour_start)
                )
                row = cur.fetchone()
                messages_hour = row[0]
                avg_response_time = row[1] or 0.0
                error_rate = row[2] or 0.0
            
            # Active users last hour (always live)
            cur.execute(
                "SELECT COUNT(DISTINCT user_id) FROM llm_requests WHERE tenant_id = %s AND created_at >= %s",
                (_tid(tenant_id), hour_start)
            )
            active_users_hour = cur.fetchone()[0]
            
            return DashboardStats(
                active_users_today=active_users_today,
                active_users_hour=active_users_hour,
                total_messages_today=total_messages_today,
                messages_per_hour=float(messages_hour),
                avg_response_time_ms=float(avg_response_time),
                error_rate_percent=float(error_rate),
                top_templates=top_templates
            )
            
    finally:
        put_conn(conn)


def get_user_stats(user_id: str, tenant_id: Optional[int] = None) -> Optional[dict]:
    """Get statistics for a specific user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT first_seen, last_seen, total_messages, total_errors
                FROM user_activity
                WHERE tenant_id = %s AND user_id = %s
                """,
                (_tid(tenant_id), user_id)
            )
            row = cur.fetchone()
            
            if not row:
                return None
            
            first_seen, last_seen, total_messages, total_errors = row
            
            cur.execute(
                """
                SELECT AVG(response_time_ms)::INTEGER
                FROM llm_requests
                WHERE tenant_id = %s AND user_id = %s AND error IS NULL
                """,
                (_tid(tenant_id), user_id)
            )
            avg_response_time = cur.fetchone()[0] or 0
            
            error_rate = (total_errors / total_messages * 100) if total_messages > 0 else 0.0
            
            return {
                "user_id": user_id,
                "total_messages": total_messages,
                "first_seen": first_seen.isoformat(),
                "last_seen": last_seen.isoformat(),
                "avg_response_time_ms": avg_response_time,
                "error_count": total_errors,
                "error_rate_percent": error_rate
            }
            
    finally:
        put_conn(conn)
