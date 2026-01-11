"""
Tests for main.py FastAPI routes.
All admin routes require authentication via auth_client fixture.
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.memory import add_message, set_memory, clear_conversation_history


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_template(auth_client):
    """Create a sample template for testing."""
    response = auth_client.post("/admin/templates", json={
        "name": "test_chatbot",
        "content": "You are a helpful assistant. {{user_id}}",
        "created_by": "test"
    })
    assert response.status_code == 200
    return response.json()["id"]


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_list_templates(auth_client, sample_template):
    """Test listing all templates."""
    response = auth_client.get("/admin/templates")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert len(data["templates"]) >= 1


def test_create_template(auth_client):
    """Test creating a new template."""
    response = auth_client.post("/admin/templates", json={
        "name": "new_template",
        "content": "Test {{var}}",
        "created_by": "admin"
    })
    assert response.status_code == 200
    assert "id" in response.json()


def test_get_template(auth_client, sample_template):
    """Test getting a specific template."""
    response = auth_client.get("/admin/templates/test_chatbot")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_chatbot"


def test_update_template(auth_client, sample_template):
    """Test updating a template."""
    response = auth_client.put(f"/admin/templates/{sample_template}", json={
        "content": "Updated content",
        "updated_by": "admin"
    })
    assert response.status_code == 200
    assert response.json()["new_version"] == 2


def test_template_history(auth_client, sample_template):
    """Test viewing template version history."""
    # Create a second version
    auth_client.put(f"/admin/templates/{sample_template}", json={
        "content": "Version 2",
        "updated_by": "admin"
    })

    response = auth_client.get(f"/admin/templates/{sample_template}/history")
    assert response.status_code == 200
    versions = response.json()["versions"]
    assert len(versions) >= 2


def test_rollback_template(auth_client, sample_template):
    """Test rolling back a template to previous version."""
    # Create version 2
    auth_client.put(f"/admin/templates/{sample_template}", json={
        "content": "Version 2",
        "updated_by": "admin"
    })

    response = auth_client.post(
        f"/admin/templates/{sample_template}/rollback/1?updated_by=admin"
    )
    assert response.status_code == 200


def test_delete_template(auth_client):
    """Test deleting a template."""
    # Create a template to delete
    create_resp = auth_client.post("/admin/templates", json={
        "name": "to_delete",
        "content": "Delete me",
        "created_by": "admin"
    })
    template_id = create_resp.json()["id"]

    response = auth_client.delete(f"/admin/templates/{template_id}")
    assert response.status_code == 200


def test_get_nonexistent_template(auth_client):
    """Test getting a template that doesn't exist."""
    response = auth_client.get("/admin/templates/nonexistent")
    assert response.status_code == 404


def test_update_nonexistent_template(auth_client):
    """Test updating a template that doesn't exist."""
    response = auth_client.put("/admin/templates/99999", json={
        "content": "New content",
        "updated_by": "admin"
    })
    assert response.status_code == 404


def test_create_template_with_empty_name(auth_client):
    """Test creating template with empty name."""
    response = auth_client.post("/admin/templates", json={
        "name": "",
        "content": "Content",
        "created_by": "admin"
    })
    assert response.status_code == 422 or response.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_list_users(auth_client, db_module):
    """Test listing all users with activity."""
    add_message("user1", "user", "Hello")
    add_message("user2", "user", "Hi")

    response = auth_client.get("/admin/users")
    assert response.status_code == 200
    assert "users" in response.json()


def test_get_conversation(auth_client, db_module):
    """Test getting a user's full conversation."""
    add_message("conv_user", "user", "Hello")
    add_message("conv_user", "assistant", "Hi")

    response = auth_client.get("/admin/users/conv_user/conversations")
    assert response.status_code == 200
    data = response.json()
    assert "messages" in data


def test_clear_conversation(auth_client, db_module):
    """Test clearing a user's conversation."""
    add_message("clear_user", "user", "Hello")
    
    response = auth_client.delete("/admin/users/clear_user/conversations")
    assert response.status_code == 200


def test_get_memory(auth_client, db_module):
    """Test getting user memory."""
    set_memory("mem_user", "prefs", {"theme": "dark"})

    response = auth_client.get("/admin/users/mem_user/memory")
    assert response.status_code == 200
    assert "memory" in response.json()


def test_get_state(auth_client, db_module):
    """Test getting user state."""
    response = auth_client.get("/admin/users/state_user/state")
    assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# INTERVENTION TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_halt_conversation(auth_client, db_module):
    """Test halting a conversation."""
    response = auth_client.post("/admin/users/halt_user/halt", json={
        "reason": "Testing halt"
    })
    assert response.status_code == 200


def test_resume_conversation(auth_client, db_module):
    """Test resuming a halted conversation."""
    # First halt
    auth_client.post("/admin/users/resume_user/halt", json={
        "reason": "Testing"
    })
    
    # Then resume
    response = auth_client.post("/admin/users/resume_user/resume")
    assert response.status_code == 200


def test_list_halted(auth_client, db_module):
    """Test listing all halted conversations."""
    response = auth_client.get("/admin/halted")
    assert response.status_code == 200
    assert "halted_users" in response.json()


# ═══════════════════════════════════════════════════════════════════════════
# GUARDRAIL TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_create_guardrail_config(auth_client):
    """Test creating a guardrail configuration."""
    response = auth_client.post("/admin/guardrails", json={
        "name": "test_config",
        "rules": [
            {
                "type": "system_instruction",
                "priority": 1,
                "content": "Test instruction"
            }
        ],
        "description": "Test config",
        "created_by": "test"
    })
    assert response.status_code == 200
    assert "id" in response.json()


def test_list_guardrail_configs(auth_client):
    """Test listing guardrail configurations."""
    response = auth_client.get("/admin/guardrails")
    assert response.status_code == 200
    assert "configs" in response.json()


def test_list_preset_configs(auth_client):
    """Test listing preset configurations."""
    response = auth_client.get("/admin/guardrails/presets")
    assert response.status_code == 200
    presets = response.json()["presets"]
    assert "unrestricted" in presets


def test_get_guardrail_by_name(auth_client):
    """Test getting a specific guardrail by name."""
    response = auth_client.get("/admin/guardrails/unrestricted")
    assert response.status_code == 200
    assert response.json()["name"] == "unrestricted"


def test_delete_guardrail_soft(auth_client):
    """Test soft deleting (deactivating) a guardrail."""
    # Create a config
    create_response = auth_client.post("/admin/guardrails", json={
        "name": "delete_soft_test",
        "rules": [{"type": "system_instruction", "content": "Test"}],
        "created_by": "test"
    })
    config_id = create_response.json()["id"]

    response = auth_client.delete(f"/admin/guardrails/{config_id}")
    assert response.status_code == 200


def test_delete_guardrail_hard(auth_client):
    """Test hard deleting a guardrail."""
    # Create a config
    create_response = auth_client.post("/admin/guardrails", json={
        "name": "delete_hard_test",
        "rules": [{"type": "system_instruction", "content": "Test"}],
        "created_by": "test"
    })
    config_id = create_response.json()["id"]

    response = auth_client.delete(f"/admin/guardrails/{config_id}?hard=true")
    assert response.status_code == 200


def test_create_guardrail_with_invalid_rules(auth_client):
    """Test creating guardrail with invalid rules structure."""
    response = auth_client.post("/admin/guardrails", json={
        "name": "invalid_rules",
        "rules": [
            {"missing_type_field": "value"}
        ],
        "created_by": "test"
    })
    assert response.status_code == 400


def test_get_nonexistent_guardrail(auth_client):
    """Test getting a guardrail that doesn't exist."""
    response = auth_client.get("/admin/guardrails/nonexistent_config_xyz")
    assert response.status_code == 404


def test_delete_nonexistent_guardrail(auth_client):
    """Test deleting a guardrail that doesn't exist."""
    response = auth_client.delete("/admin/guardrails/99999")
    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE VERSIONING FLOW
# ═══════════════════════════════════════════════════════════════════════════

def test_template_versioning_flow(auth_client):
    """Test complete template versioning workflow."""
    # Create
    response = auth_client.post("/admin/templates", json={
        "name": "version_test",
        "content": "Version 1",
        "created_by": "admin"
    })
    template_id = response.json()["id"]

    # Update to v2
    auth_client.put(f"/admin/templates/{template_id}", json={
        "content": "Version 2",
        "updated_by": "admin"
    })

    # Update to v3
    auth_client.put(f"/admin/templates/{template_id}", json={
        "content": "Version 3",
        "updated_by": "admin"
    })

    # Check history
    history = auth_client.get(f"/admin/templates/{template_id}/history").json()
    assert len(history["versions"]) == 3

    # Rollback to v1
    auth_client.post(f"/admin/templates/{template_id}/rollback/1?updated_by=admin")

    # Verify via GET by name
    template = auth_client.get("/admin/templates/version_test").json()
    # Current version should be 4 (rollback creates new version)
    assert template["version"] == 4


# ═══════════════════════════════════════════════════════════════════════════
# AUTH REQUIRED TESTS (ensure unauthenticated requests fail)
# ═══════════════════════════════════════════════════════════════════════════

def test_templates_require_auth(db_module):
    """Test that template endpoints require authentication."""
    client = TestClient(app)
    
    response = client.get("/admin/templates")
    assert response.status_code == 401

    response = client.post("/admin/templates", json={"name": "x", "content": "y"})
    assert response.status_code == 401


def test_users_require_auth(db_module):
    """Test that user endpoints require authentication."""
    client = TestClient(app)
    
    response = client.get("/admin/users")
    assert response.status_code == 401


def test_guardrails_require_auth(db_module):
    """Test that guardrail endpoints require authentication."""
    client = TestClient(app)
    
    response = client.get("/admin/guardrails")
    assert response.status_code == 401
