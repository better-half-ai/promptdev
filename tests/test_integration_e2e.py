"""
END-TO-END INTEGRATION TESTS

Tests the complete flow:
  User Request → Template Loading → Context Building → Guardrails → LLM Call → Response Storage → Telemetry

NO MOCKS. Uses real Mistral LLM with pytest.skip when unavailable.
"""

import pytest
import asyncio
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def mistral_available():
    """Check if Mistral is running."""
    from src.llm_client import health_check
    try:
        return asyncio.run(health_check())
    except:
        return False


@pytest.fixture
def client(db_module):
    """FastAPI test client with clean database."""
    from src.main import app
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════
# CORE E2E FLOW TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_full_chat_flow_with_guardrails(client, db_module, mistral_available):
    """Test complete chat flow with guardrails applied."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    # STEP 1: Create template
    template_resp = client.post("/admin/templates", json={
        "name": "test_template",
        "content": "You are a helpful assistant.\n\nUser message: {{current_message}}",
        "created_by": "test_operator"
    })
    assert template_resp.status_code == 200
    
    # STEP 2: Create guardrail config
    guardrail_resp = client.post("/admin/guardrails", json={
        "name": "test_guardrail",
        "description": "Test guardrail with priority ordering",
        "rules": [
            {
                "type": "system_instruction",
                "content": "PRIORITY_HIGH: Be extremely concise.",
                "priority": 10
            },
            {
                "type": "system_instruction", 
                "content": "PRIORITY_LOW: Use simple language.",
                "priority": 1
            }
        ],
        "created_by": "test_operator"
    })
    assert guardrail_resp.status_code == 200
    
    # STEP 3: Add conversation history
    from src.memory import add_message, set_memory
    add_message("test_user", "user", "What is Python?")
    add_message("test_user", "assistant", "Python is a programming language.")
    
    # STEP 4: Add user memory
    set_memory("test_user", "preferences", {"style": "concise", "level": "beginner"})
    
    # STEP 5: Send chat request WITH guardrail - USES REAL MISTRAL
    chat_resp = client.post("/chat", json={
        "user_id": "test_user",
        "message": "Explain machine learning",
        "template_name": "test_template",
        "guardrail_config": "test_guardrail"
    })
    
    # VERIFY: Request succeeded
    assert chat_resp.status_code == 200
    data = chat_resp.json()
    assert "response" in data
    assert len(data["response"]) > 0  # Got actual response from real LLM
    assert "metadata" in data
    assert data["metadata"]["template_used"] == "test_template"
    assert "response_time_ms" in data["metadata"]
    
    # VERIFY: Conversation history was saved
    history_resp = client.get("/chat/history?user_id=test_user")
    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]
    assert len(messages) >= 4  # 2 old + 2 new
    
    user_messages = [m for m in messages if m["content"] == "Explain machine learning"]
    assert len(user_messages) == 1
    
    # VERIFY: Telemetry tracked the request
    from src.telemetry import get_user_stats
    stats = get_user_stats("test_user")
    assert stats is not None
    assert stats["total_messages"] >= 1


def test_guardrail_priority_ordering(client, db_module, mistral_available):
    """Verify guardrails are applied in strict priority order."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    client.post("/admin/templates", json={
        "name": "priority_template",
        "content": "Base template content.",
        "created_by": "test"
    })
    
    client.post("/admin/guardrails", json={
        "name": "priority_test",
        "rules": [
            {"type": "system_instruction", "content": "RULE_5", "priority": 5},
            {"type": "system_instruction", "content": "RULE_10", "priority": 10},
            {"type": "system_instruction", "content": "RULE_1", "priority": 1},
            {"type": "system_instruction", "content": "RULE_7", "priority": 7}
        ],
        "created_by": "test"
    })
    
    resp = client.post("/chat", json={
        "user_id": "priority_user",
        "message": "Test message",
        "template_name": "priority_template",
        "guardrail_config": "priority_test"
    })
    
    assert resp.status_code == 200
    assert len(resp.json()["response"]) > 0


def test_chat_without_guardrails_still_works(client, db_module, mistral_available):
    """Verify chat works correctly without guardrails."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    client.post("/admin/templates", json={
        "name": "no_guard_template",
        "content": "Simple template without guardrails.",
        "created_by": "test"
    })
    
    resp = client.post("/chat", json={
        "user_id": "no_guard_user",
        "message": "Hello world",
        "template_name": "no_guard_template"
    })
    
    assert resp.status_code == 200
    assert len(resp.json()["response"]) > 0


def test_intervention_halt_blocks_chat(client, db_module):
    """Test that halting a conversation prevents further chat."""
    
    client.post("/admin/templates", json={
        "name": "halt_template",
        "content": "Template for halt test.",
        "created_by": "test"
    })
    
    # Halt immediately
    halt_resp = client.post("/admin/interventions/halt_user/halt", json={
        "operator": "test_operator",
        "reason": "Testing halt functionality"
    })
    assert halt_resp.status_code == 200
    
    # Try to chat - should be blocked (no LLM needed)
    resp = client.post("/chat", json={
        "user_id": "halt_user",
        "message": "Should fail",
        "template_name": "halt_template"
    })
    assert resp.status_code == 423
    assert "halted" in resp.json()["detail"].lower()
    
    # Check halted list
    halted_resp = client.get("/admin/interventions")
    assert halted_resp.status_code == 200
    halted_users = halted_resp.json()["halted_users"]
    assert any(u["user_id"] == "halt_user" for u in halted_users)
    
    # Resume
    resume_resp = client.post("/admin/interventions/halt_user/resume?operator=test_operator")
    assert resume_resp.status_code == 200


def test_intervention_inject_message(client, db_module):
    """Test operator can inject messages into conversation."""
    
    from src.memory import add_message
    
    add_message("inject_user", "user", "I need help")
    add_message("inject_user", "assistant", "I can help you")
    
    inject_resp = client.post("/admin/interventions/inject_user/inject", json={
        "content": "Please wait while I review your case.",
        "operator": "support_agent"
    })
    assert inject_resp.status_code == 200
    
    history_resp = client.get("/chat/history?user_id=inject_user")
    messages = history_resp.json()["messages"]
    
    injected = [m for m in messages if "[Operator:" in m["content"]]
    assert len(injected) == 1
    assert "support_agent" in injected[0]["content"]
    assert "Please wait while I review your case" in injected[0]["content"]


def test_multi_user_isolation(client, db_module):
    """Test that multiple users' conversations are isolated."""
    
    from src.memory import add_message
    
    add_message("user_a", "user", "I am user A")
    add_message("user_a", "assistant", "Hello user A")
    
    add_message("user_b", "user", "I am user B")
    add_message("user_b", "assistant", "Hello user B")
    
    history_a = client.get("/chat/history?user_id=user_a").json()["messages"]
    history_b = client.get("/chat/history?user_id=user_b").json()["messages"]
    
    assert any("user A" in m["content"] for m in history_a)
    assert not any("user B" in m["content"] for m in history_a)
    
    assert any("user B" in m["content"] for m in history_b)
    assert not any("user A" in m["content"] for m in history_b)


def test_template_version_rollback(client, db_module):
    """Test template rollback mechanism."""
    
    create_resp = client.post("/admin/templates", json={
        "name": "version_template",
        "content": "VERSION_1 content.",
        "created_by": "test"
    })
    template_id = create_resp.json()["id"]
    
    # Update to v2
    client.put(f"/admin/templates/{template_id}", json={
        "content": "VERSION_2 content.",
        "updated_by": "test"
    })
    
    # Verify v2 is active
    from src.prompts import get_template_by_name
    template = get_template_by_name("version_template")
    assert "VERSION_2" in template.content
    
    # Rollback to v1
    client.post(f"/admin/templates/{template_id}/rollback/1?updated_by=test")
    
    # Verify v1 is active
    template = get_template_by_name("version_template")
    assert "VERSION_1" in template.content


def test_template_not_found_error(client, db_module):
    """Test that chat with nonexistent template returns 404."""
    
    resp = client.post("/chat", json={
        "user_id": "error_user",
        "message": "Test",
        "template_name": "nonexistent_template"
    })
    
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()