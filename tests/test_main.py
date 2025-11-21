"""
Test suite for main.py API endpoints.

Tests cover:
- System: Health check
- User endpoints: Chat, history (requires Mistral)
- Admin/Template: CRUD, versioning, rollback
- Admin/Monitoring: Users, conversations, memory, state
- Admin/Interventions: Halt, resume, inject, list halted
- Integration: Full workflows, multi-user isolation
"""

import pytest
import asyncio
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

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
    """FastAPI test client."""
    from src.main import app
    return TestClient(app)


@pytest.fixture
def sample_template(db_module):
    """Create sample template for testing."""
    from src.prompts import create_template
    return create_template(
        "test_chatbot",
        "You are helpful. User: {{current_message}}",
        created_by="test"
    )


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_health(client):
    """Test health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# USER ENDPOINT TESTS (require Mistral)
# ═══════════════════════════════════════════════════════════════════════════

def test_chat_basic(client, sample_template, mistral_available):
    """Test basic chat flow."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello",
        "template_name": "test_chatbot"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["metadata"]["template_used"] == "test_chatbot"


def test_chat_without_template(client, sample_template, mistral_available):
    """Test chat with default template selection."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello"
    })
    
    assert response.status_code == 200
    assert response.json()["metadata"]["template_used"] == "test_chatbot"


def test_chat_halted(client, sample_template):
    """Test that halted conversation blocks chat."""
    from src.main import halt_conversation
    
    halt_conversation("user1", "admin", "Testing")
    
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello"
    })
    
    assert response.status_code == 423
    assert "halted" in response.json()["detail"].lower()


def test_get_history(client):
    """Test retrieving chat history."""
    from src.memory import add_message
    
    add_message("user1", "user", "Hello")
    add_message("user1", "assistant", "Hi")
    
    response = client.get("/chat/history?user_id=user1")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["messages"]) == 2
    assert data["total_count"] == 2


def test_clear_history(client):
    """Test clearing chat history."""
    from src.memory import add_message
    
    add_message("user1", "user", "Hello")
    add_message("user1", "assistant", "Hi")
    
    response = client.delete("/chat/history/user1")
    
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_list_templates(client, sample_template):
    """Test listing all templates."""
    response = client.get("/admin/templates")
    
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    assert any(t["name"] == "test_chatbot" for t in data["templates"])


def test_create_template(client):
    """Test creating a new template."""
    response = client.post("/admin/templates", json={
        "name": "new_template",
        "content": "Test {{var}}",
        "created_by": "admin"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "new_template"
    assert data["version"] == 1


def test_get_template(client, sample_template):
    """Test getting a specific template."""
    response = client.get("/admin/templates/test_chatbot")
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_chatbot"


def test_update_template(client, sample_template):
    """Test updating a template."""
    response = client.put(f"/admin/templates/{sample_template}", json={
        "content": "Updated content",
        "updated_by": "admin"
    })
    
    assert response.status_code == 200
    assert response.json()["new_version"] == 2


def test_template_history(client, sample_template):
    """Test viewing template version history."""
    client.put(f"/admin/templates/{sample_template}", json={
        "content": "Version 2",
        "updated_by": "admin"
    })
    
    response = client.get(f"/admin/templates/{sample_template}/history")
    
    assert response.status_code == 200
    assert len(response.json()["versions"]) == 2


def test_rollback_template(client, sample_template):
    """Test rolling back a template to previous version."""
    client.put(f"/admin/templates/{sample_template}", json={
        "content": "Version 2",
        "updated_by": "admin"
    })
    
    response = client.post(
        f"/admin/templates/{sample_template}/rollback/1?updated_by=admin"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["rolled_back_to"] == 1
    assert data["new_version"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# MONITORING TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_list_users(client):
    """Test listing all users with activity."""
    from src.memory import add_message
    
    add_message("user1", "user", "Hello")
    add_message("user2", "user", "Hi")
    
    response = client.get("/admin/users")
    
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2


def test_get_conversation(client):
    """Test getting a user's full conversation."""
    from src.memory import add_message
    
    add_message("user1", "user", "Hello")
    add_message("user1", "assistant", "Hi")
    
    response = client.get("/admin/conversations/user1")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["messages"]) == 2


def test_get_memory(client):
    """Test getting user memory."""
    from src.memory import set_memory
    
    set_memory("user1", "prefs", {"theme": "dark"})
    
    response = client.get("/admin/memory/user1")
    
    assert response.status_code == 200
    assert "prefs" in response.json()["memory"]


def test_set_memory(client):
    """Test setting user memory."""
    response = client.put("/admin/memory/user1/test", json={
        "value": {"data": "test"}
    })
    
    assert response.status_code == 200
    
    from src.memory import get_memory
    assert get_memory("user1", "test")["data"] == "test"


def test_get_set_state(client):
    """Test getting and setting user state."""
    response = client.put("/admin/state/user1?mode=active")
    assert response.status_code == 200
    
    response = client.get("/admin/state/user1")
    assert response.status_code == 200
    assert response.json()["mode"] == "active"


# ═══════════════════════════════════════════════════════════════════════════
# INTERVENTION TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_halt_conversation(client):
    """Test halting a conversation."""
    response = client.post("/admin/interventions/user1/halt", json={
        "operator": "admin",
        "reason": "Testing"
    })
    
    assert response.status_code == 200
    assert response.json()["status"] == "halted"


def test_resume_conversation(client):
    """Test resuming a halted conversation."""
    from src.main import halt_conversation
    
    halt_conversation("user1", "admin", "Test")
    
    response = client.post("/admin/interventions/user1/resume?operator=admin")
    
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_inject_message(client):
    """Test injecting an operator message."""
    response = client.post("/admin/interventions/user1/inject", json={
        "content": "Operator message",
        "operator": "admin"
    })
    
    assert response.status_code == 200
    assert "message_id" in response.json()
    
    from src.memory import get_conversation_history
    messages = get_conversation_history("user1")
    assert len(messages) == 1
    assert "[Operator: admin]" in messages[0].content


def test_list_halted(client):
    """Test listing all halted conversations."""
    from src.main import halt_conversation
    
    halt_conversation("user1", "admin", "Reason 1")
    halt_conversation("user2", "admin", "Reason 2")
    
    response = client.get("/admin/interventions")
    
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_full_chat_flow(client, sample_template, mistral_available):
    """Test complete chat flow."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    # Chat
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello"
    })
    
    assert response.status_code == 200
    
    # Check history
    response = client.get("/chat/history?user_id=user1")
    assert len(response.json()["messages"]) == 2  # User + assistant


def test_halt_blocks_chat(client, sample_template):
    """Test that halting actually blocks chat."""
    # Halt
    client.post("/admin/interventions/user1/halt", json={
        "operator": "admin",
        "reason": "Test"
    })
    
    # Try to chat
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello"
    })
    
    assert response.status_code == 423


def test_multiple_users_isolation(client, sample_template, mistral_available):
    """Test that multiple users' conversations are isolated."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    # User 1
    client.post("/chat", json={
        "user_id": "user1",
        "message": "User 1 message"
    })
    
    # User 2
    client.post("/chat", json={
        "user_id": "user2",
        "message": "User 2 message"
    })
    
    # Check isolation
    hist1 = client.get("/chat/history?user_id=user1").json()
    hist2 = client.get("/chat/history?user_id=user2").json()
    
    assert len(hist1["messages"]) == 2
    assert len(hist2["messages"]) == 2
    
    # Check user messages are in respective histories
    user1_messages = [m["content"] for m in hist1["messages"]]
    user2_messages = [m["content"] for m in hist2["messages"]]
    
    assert "User 1 message" in user1_messages
    assert "User 2 message" in user2_messages
    assert "User 2 message" not in user1_messages
    assert "User 1 message" not in user2_messages


def test_template_versioning_flow(client):
    """Test complete template versioning workflow."""
    # Create
    response = client.post("/admin/templates", json={
        "name": "version_test",
        "content": "Version 1",
        "created_by": "admin"
    })
    template_id = response.json()["id"]
    
    # Update
    client.put(f"/admin/templates/{template_id}", json={
        "content": "Version 2",
        "updated_by": "admin"
    })
    
    # Update again
    client.put(f"/admin/templates/{template_id}", json={
        "content": "Version 3",
        "updated_by": "admin"
    })
    
    # Check history
    response = client.get(f"/admin/templates/{template_id}/history")
    assert len(response.json()["versions"]) == 3
    
    # Rollback to v1
    response = client.post(f"/admin/templates/{template_id}/rollback/1?updated_by=admin")
    assert response.json()["new_version"] == 4
    
    # Verify content rolled back
    response = client.get("/admin/templates/version_test")
    assert response.json()["content"] == "Version 1"
    assert response.json()["version"] == 4


def test_intervention_workflow(client, sample_template, mistral_available):
    """Test complete intervention workflow."""
    if not mistral_available:
        pytest.skip("Mistral not available")
    
    # Start normal chat
    client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello"
    })
    
    # Operator halts
    client.post("/admin/interventions/user1/halt", json={
        "operator": "admin",
        "reason": "Need to review"
    })
    
    # Check it's in halted list
    response = client.get("/admin/interventions")
    assert response.json()["count"] == 1
    
    # Inject operator message
    client.post("/admin/interventions/user1/inject", json={
        "content": "Please hold while we review",
        "operator": "admin"
    })
    
    # Check conversation has injected message
    response = client.get("/admin/conversations/user1")
    messages = response.json()["messages"]
    assert any("[Operator:" in msg["content"] for msg in messages)
    
    # Resume
    client.post("/admin/interventions/user1/resume?operator=admin")
    
    # Verify can chat again
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Thank you"
    })
    assert response.status_code == 200


def test_memory_and_state_integration(client):
    """Test memory and state management together."""
    # Set various memory entries
    client.put("/admin/memory/user1/preferences", json={
        "value": {"theme": "dark", "language": "en"}
    })
    client.put("/admin/memory/user1/context", json={
        "value": {"topic": "Python", "level": "advanced"}
    })
    
    # Set state
    client.put("/admin/state/user1?mode=learning")
    
    # Get all memory
    response = client.get("/admin/memory/user1")
    memory = response.json()["memory"]
    assert "preferences" in memory
    assert "context" in memory
    assert memory["preferences"]["theme"] == "dark"
    
    # Get state
    response = client.get("/admin/state/user1")
    assert response.json()["mode"] == "learning"
    
    # Get full conversation view
    response = client.get("/admin/conversations/user1")
    assert response.json()["state"] == "learning"


# ═══════════════════════════════════════════════════════════════════════════
# ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_chat_with_nonexistent_template(client, db_module):
    """Test chat with invalid template name."""
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": "Hello",
        "template_name": "nonexistent"
    })
    
    assert response.status_code == 404


def test_get_nonexistent_template(client):
    """Test getting a template that doesn't exist."""
    response = client.get("/admin/templates/nonexistent")
    
    assert response.status_code == 404


def test_update_nonexistent_template(client):
    """Test updating a template that doesn't exist."""
    response = client.put("/admin/templates/99999", json={
        "content": "New content",
        "updated_by": "admin"
    })
    
    assert response.status_code == 404


def test_resume_non_halted_conversation(client):
    """Test resuming a conversation that isn't halted."""
    response = client.post("/admin/interventions/user1/resume?operator=admin")
    
    assert response.status_code == 400


def test_get_state_for_user_without_state(client):
    """Test getting state for user with no state."""
    response = client.get("/admin/state/user1")
    
    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_chat_with_empty_user_id(client, sample_template):
    """Test chat with empty user_id."""
    response = client.post("/chat", json={
        "user_id": "",
        "message": "Hello"
    })
    
    assert response.status_code == 422  # Validation error


def test_chat_with_empty_message(client, sample_template):
    """Test chat with empty message."""
    response = client.post("/chat", json={
        "user_id": "user1",
        "message": ""
    })
    
    assert response.status_code == 422  # Validation error


def test_create_template_with_empty_name(client):
    """Test creating template with empty name."""
    response = client.post("/admin/templates", json={
        "name": "",
        "content": "Content",
        "created_by": "admin"
    })
    
    assert response.status_code == 422  # Validation error


def test_halt_with_empty_reason(client):
    """Test halting with empty reason."""
    response = client.post("/admin/interventions/user1/halt", json={
        "operator": "admin",
        "reason": ""
    })
    
    assert response.status_code == 422  # Validation error