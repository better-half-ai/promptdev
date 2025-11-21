"""
Tests for telemetry module.
"""

import pytest
from datetime import datetime, timedelta, timezone
from src.telemetry import (
    track_llm_request,
    aggregate_metrics,
    get_dashboard_stats,
    get_user_stats,
)


@pytest.fixture
def clean_telemetry(db_module):
    """Clean telemetry tables before each test."""
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM llm_requests")
            cur.execute("DELETE FROM user_activity")
            cur.execute("DELETE FROM metric_snapshots")
        conn.commit()
    finally:
        db_module.put_conn(conn)
    yield


def test_track_llm_request_basic(db_module, clean_telemetry):
    """Test basic LLM request tracking."""
    request_id = track_llm_request(
        user_id="user1",
        response_time_ms=250,
        template_name="default"
    )
    
    assert request_id > 0
    
    # Verify in database
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, response_time_ms, template_name FROM llm_requests WHERE id = %s", (request_id,))
            row = cur.fetchone()
            assert row[0] == "user1"
            assert row[1] == 250
            assert row[2] == "default"
    finally:
        db_module.put_conn(conn)


def test_track_llm_request_with_tokens(db_module, clean_telemetry):
    """Test tracking with token counts."""
    request_id = track_llm_request(
        user_id="user1",
        response_time_ms=300,
        request_tokens=100,
        response_tokens=50
    )
    
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT request_tokens, response_tokens, total_tokens FROM llm_requests WHERE id = %s",
                (request_id,)
            )
            row = cur.fetchone()
            assert row[0] == 100
            assert row[1] == 50
            assert row[2] == 150  # total
    finally:
        db_module.put_conn(conn)


def test_track_llm_request_with_error(db_module, clean_telemetry):
    """Test tracking failed requests."""
    request_id = track_llm_request(
        user_id="user1",
        response_time_ms=100,
        error="Connection timeout"
    )
    
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT error FROM llm_requests WHERE id = %s", (request_id,))
            error = cur.fetchone()[0]
            assert error == "Connection timeout"
    finally:
        db_module.put_conn(conn)


def test_user_activity_tracking(db_module, clean_telemetry):
    """Test that user_activity table is updated correctly."""
    # First request
    track_llm_request(user_id="user1", response_time_ms=200)
    
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT total_messages, total_errors FROM user_activity WHERE user_id = %s", ("user1",))
            row = cur.fetchone()
            assert row[0] == 1
            assert row[1] == 0
    finally:
        db_module.put_conn(conn)
    
    # Second request with error
    track_llm_request(user_id="user1", response_time_ms=100, error="Fail")
    
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT total_messages, total_errors FROM user_activity WHERE user_id = %s", ("user1",))
            row = cur.fetchone()
            assert row[0] == 2
            assert row[1] == 1
    finally:
        db_module.put_conn(conn)


def test_user_activity_multiple_users(db_module, clean_telemetry):
    """Test tracking multiple users."""
    track_llm_request(user_id="user1", response_time_ms=200)
    track_llm_request(user_id="user2", response_time_ms=300)
    track_llm_request(user_id="user1", response_time_ms=250)
    
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, total_messages FROM user_activity ORDER BY user_id")
            rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0] == ("user1", 2)
            assert rows[1] == ("user2", 1)
    finally:
        db_module.put_conn(conn)


def test_aggregate_metrics_hourly(db_module, clean_telemetry):
    """Test hourly metric aggregation."""
    # Create test data
    track_llm_request(user_id="user1", response_time_ms=200, template_name="default")
    track_llm_request(user_id="user2", response_time_ms=300, template_name="default")
    track_llm_request(user_id="user1", response_time_ms=100, error="Fail")
    
    # Aggregate
    aggregate_metrics()
    
    # Check hourly snapshot
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT value FROM metric_snapshots 
                WHERE metric_name = 'hourly_summary' AND time_window = 'hour'
                ORDER BY created_at DESC LIMIT 1
                """
            )
            row = cur.fetchone()
            assert row is not None
            
            value = row[0]
            assert value['messages'] == 3
            assert value['avg_response_time_ms'] == 250  # (200+300)/2, excluding error
            assert value['error_rate_percent'] == pytest.approx(33.33, rel=0.1)
    finally:
        db_module.put_conn(conn)


def test_aggregate_metrics_daily(db_module, clean_telemetry):
    """Test daily metric aggregation."""
    # Create test data
    track_llm_request(user_id="user1", response_time_ms=200, template_name="template_a")
    track_llm_request(user_id="user2", response_time_ms=300, template_name="template_b")
    track_llm_request(user_id="user1", response_time_ms=250, template_name="template_a")
    
    # Aggregate
    aggregate_metrics()
    
    # Check daily snapshot
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT value FROM metric_snapshots 
                WHERE metric_name = 'daily_summary' AND time_window = 'day'
                ORDER BY created_at DESC LIMIT 1
                """
            )
            row = cur.fetchone()
            assert row is not None
            
            value = row[0]
            assert value['messages'] == 3
            assert value['active_users'] == 2
            assert len(value['top_templates']) == 2
            assert value['top_templates'][0]['name'] == 'template_a'
            assert value['top_templates'][0]['count'] == 2
    finally:
        db_module.put_conn(conn)


def test_get_dashboard_stats_with_cache(db_module, clean_telemetry):
    """Test dashboard stats retrieval from cache."""
    # Create data and aggregate
    track_llm_request(user_id="user1", response_time_ms=200, template_name="default")
    track_llm_request(user_id="user2", response_time_ms=300, template_name="default")
    aggregate_metrics()
    
    # Get stats
    stats = get_dashboard_stats()
    
    assert stats.total_messages_today == 2
    assert stats.active_users_today == 2
    assert stats.active_users_hour == 2
    assert stats.messages_per_hour == 2.0
    assert stats.avg_response_time_ms == 250.0
    assert stats.error_rate_percent == 0.0


def test_get_dashboard_stats_fallback_no_cache(db_module, clean_telemetry):
    """Test dashboard stats with no cached metrics (fallback)."""
    # Create data but don't aggregate
    track_llm_request(user_id="user1", response_time_ms=200)
    track_llm_request(user_id="user2", response_time_ms=300)
    
    # Get stats (should use fallback queries)
    stats = get_dashboard_stats()
    
    assert stats.total_messages_today == 2
    assert stats.active_users_today == 2
    assert stats.active_users_hour == 2
    assert stats.messages_per_hour == 2.0


def test_get_dashboard_stats_empty(db_module, clean_telemetry):
    """Test dashboard stats with no data."""
    stats = get_dashboard_stats()
    
    assert stats.total_messages_today == 0
    assert stats.active_users_today == 0
    assert stats.active_users_hour == 0
    assert stats.messages_per_hour == 0.0
    assert stats.avg_response_time_ms == 0.0
    assert stats.error_rate_percent == 0.0
    assert stats.top_templates == []


def test_get_user_stats(db_module, clean_telemetry):
    """Test getting stats for a specific user."""
    # Create data
    track_llm_request(user_id="user1", response_time_ms=200)
    track_llm_request(user_id="user1", response_time_ms=300)
    track_llm_request(user_id="user1", response_time_ms=100, error="Fail")
    
    # Get stats
    stats = get_user_stats("user1")
    
    assert stats is not None
    assert stats['user_id'] == "user1"
    assert stats['total_messages'] == 3
    assert stats['error_count'] == 1
    assert stats['error_rate_percent'] == pytest.approx(33.33, rel=0.1)
    assert stats['avg_response_time_ms'] == 250  # (200+300)/2, excluding error


def test_get_user_stats_nonexistent(db_module, clean_telemetry):
    """Test getting stats for user that doesn't exist."""
    stats = get_user_stats("nonexistent")
    assert stats is None


def test_aggregate_metrics_idempotent(db_module, clean_telemetry):
    """Test that aggregating multiple times doesn't corrupt data."""
    track_llm_request(user_id="user1", response_time_ms=200)
    
    # Aggregate twice
    aggregate_metrics()
    aggregate_metrics()
    
    # Should still have correct data
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM metric_snapshots WHERE metric_name = 'hourly_summary'")
            count = cur.fetchone()[0]
            assert count == 1  # Only one record for this hour
    finally:
        db_module.put_conn(conn)


def test_top_templates_ordering(db_module, clean_telemetry):
    """Test that top templates are ordered by usage."""
    # Create requests with different templates
    for _ in range(5):
        track_llm_request(user_id="user1", response_time_ms=200, template_name="popular")
    for _ in range(3):
        track_llm_request(user_id="user1", response_time_ms=200, template_name="medium")
    track_llm_request(user_id="user1", response_time_ms=200, template_name="rare")
    
    aggregate_metrics()
    stats = get_dashboard_stats()
    
    assert len(stats.top_templates) == 3
    assert stats.top_templates[0]['name'] == "popular"
    assert stats.top_templates[0]['count'] == 5
    assert stats.top_templates[1]['name'] == "medium"
    assert stats.top_templates[1]['count'] == 3
    assert stats.top_templates[2]['name'] == "rare"
    assert stats.top_templates[2]['count'] == 1


def test_error_rate_calculation(db_module, clean_telemetry):
    """Test error rate percentage calculation."""
    # 2 success, 1 error = 33.33% error rate
    track_llm_request(user_id="user1", response_time_ms=200)
    track_llm_request(user_id="user1", response_time_ms=300)
    track_llm_request(user_id="user1", response_time_ms=100, error="Fail")
    
    aggregate_metrics()
    stats = get_dashboard_stats()
    
    assert stats.error_rate_percent == pytest.approx(33.33, rel=0.1)


def test_response_time_excludes_errors(db_module, clean_telemetry):
    """Test that average response time excludes failed requests."""
    track_llm_request(user_id="user1", response_time_ms=200)
    track_llm_request(user_id="user1", response_time_ms=400)
    track_llm_request(user_id="user1", response_time_ms=9999, error="Timeout")
    
    aggregate_metrics()
    stats = get_dashboard_stats()
    
    # Should average 200 and 400, not include 9999
    assert stats.avg_response_time_ms == 300.0
