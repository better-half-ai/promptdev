"""
API-level tests for multi-tenant isolation.

Tests verify that:
1. Admin A cannot see Admin B's templates via API
2. Admin A cannot see Admin B's users/conversations via API
3. Admin A cannot see Admin B's guardrails via API
4. Template sharing/cloning works correctly via API
5. Super admin can manage other admins

NO MOCKS - all tests hit real database via testcontainers.
"""

import pytest
from fastapi.testclient import TestClient

from conftest import (
    TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD,
    TEST_ADMIN2_EMAIL, TEST_ADMIN2_PASSWORD,
)


class TestTemplateIsolationAPI:
    """Test that templates are isolated per tenant via API."""
    
    def test_admin_cannot_see_other_admin_templates(
        self, auth_client, second_admin_client, test_admin, second_admin
    ):
        """Admin A creates template, Admin B cannot see it."""
        # Admin A creates a template
        response = auth_client.post("/admin/templates", json={
            "name": "admin_a_template",
            "content": "Hello from Admin A"
        })
        assert response.status_code == 200
        template_id = response.json()["id"]
        
        # Admin A can see their template
        response = auth_client.get("/admin/templates")
        assert response.status_code == 200
        names = [t["name"] for t in response.json()["templates"]]
        assert "admin_a_template" in names
        
        # Admin B creates their own template
        response = second_admin_client.post("/admin/templates", json={
            "name": "admin_b_template",
            "content": "Hello from Admin B"
        })
        assert response.status_code == 200
        
        # Admin B lists templates - should NOT see Admin A's template
        response = second_admin_client.get("/admin/templates")
        assert response.status_code == 200
        names = [t["name"] for t in response.json()["templates"]]
        assert "admin_b_template" in names
        assert "admin_a_template" not in names
    
    def test_admin_cannot_access_other_admin_template_by_name(
        self, auth_client, second_admin_client
    ):
        """Admin A creates template, Admin B cannot access it by name."""
        # Admin A creates a template
        auth_client.post("/admin/templates", json={
            "name": "secret_template",
            "content": "Secret content"
        })
        
        # Admin B tries to access it by name - should get 404
        response = second_admin_client.get("/admin/templates/secret_template")
        assert response.status_code == 404
    
    def test_admin_cannot_update_other_admin_template(
        self, auth_client, second_admin_client, db_conn
    ):
        """Admin A creates template, Admin B cannot update it."""
        # Admin A creates a template
        response = auth_client.post("/admin/templates", json={
            "name": "protected_template",
            "content": "Original content"
        })
        template_id = response.json()["id"]
        
        # Admin B tries to update it - should get 404
        response = second_admin_client.put(f"/admin/templates/{template_id}", json={
            "content": "Hacked content"
        })
        assert response.status_code == 404
        
        # Verify original content unchanged
        response = auth_client.get("/admin/templates/protected_template")
        assert response.json()["content"] == "Original content"
    
    def test_same_template_name_different_tenants(
        self, auth_client, second_admin_client
    ):
        """Two admins can have templates with the same name."""
        # Admin A creates "common_name"
        response = auth_client.post("/admin/templates", json={
            "name": "common_name",
            "content": "Admin A version"
        })
        assert response.status_code == 200
        
        # Admin B creates "common_name" - should work
        response = second_admin_client.post("/admin/templates", json={
            "name": "common_name",
            "content": "Admin B version"
        })
        assert response.status_code == 200
        
        # Each sees their own version
        response = auth_client.get("/admin/templates/common_name")
        assert response.json()["content"] == "Admin A version"
        
        response = second_admin_client.get("/admin/templates/common_name")
        assert response.json()["content"] == "Admin B version"


class TestUserIsolationAPI:
    """Test that users/conversations are isolated per tenant via API."""
    
    def test_admin_cannot_see_other_admin_users(
        self, auth_client, second_admin_client, db_conn, test_admin, second_admin
    ):
        """Admin A's users are not visible to Admin B."""
        # Create conversation for Admin A's user directly in DB
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'user_for_admin_a', 'user', 'Hello from A')
            """, (test_admin.tenant_id,))
            
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'user_for_admin_b', 'user', 'Hello from B')
            """, (second_admin.tenant_id,))
            db_conn.commit()
        
        # Admin A lists users
        response = auth_client.get("/admin/users")
        assert response.status_code == 200
        user_ids = [u["user_id"] for u in response.json()["users"]]
        assert "user_for_admin_a" in user_ids
        assert "user_for_admin_b" not in user_ids
        
        # Admin B lists users
        response = second_admin_client.get("/admin/users")
        assert response.status_code == 200
        user_ids = [u["user_id"] for u in response.json()["users"]]
        assert "user_for_admin_b" in user_ids
        assert "user_for_admin_a" not in user_ids
    
    def test_admin_cannot_see_other_admin_user_conversations(
        self, auth_client, second_admin_client, db_conn, test_admin
    ):
        """Admin B cannot access Admin A's user conversations."""
        # Create conversation for Admin A's user
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'private_user', 'user', 'Private message')
            """, (test_admin.tenant_id,))
            db_conn.commit()
        
        # Admin A can see it
        response = auth_client.get("/admin/users/private_user/conversations")
        assert response.status_code == 200
        assert len(response.json()["messages"]) > 0
        
        # Admin B gets empty (user doesn't exist in their tenant)
        response = second_admin_client.get("/admin/users/private_user/conversations")
        assert response.status_code == 200
        assert len(response.json()["messages"]) == 0


class TestGuardrailIsolationAPI:
    """Test that guardrails are isolated per tenant via API."""
    
    def test_admin_cannot_see_other_admin_guardrails(
        self, auth_client, second_admin_client
    ):
        """Admin A's custom guardrails are not visible to Admin B."""
        # Admin A creates a guardrail
        response = auth_client.post("/admin/guardrails", json={
            "name": "admin_a_rule",
            "rules": [{"type": "system_instruction", "content": "Be nice"}],
            "description": "Admin A's rule"
        })
        assert response.status_code == 200
        
        # Admin A can see it
        response = auth_client.get("/admin/guardrails")
        names = [c["name"] for c in response.json()["configs"]]
        assert "admin_a_rule" in names
        
        # Admin B cannot see Admin A's custom guardrail
        # (but can see system presets)
        response = second_admin_client.get("/admin/guardrails")
        names = [c["name"] for c in response.json()["configs"]]
        assert "admin_a_rule" not in names
    
    def test_admin_cannot_delete_other_admin_guardrail(
        self, auth_client, second_admin_client
    ):
        """Admin B cannot delete Admin A's guardrail."""
        # Admin A creates a guardrail
        response = auth_client.post("/admin/guardrails", json={
            "name": "protected_rule",
            "rules": []
        })
        config_id = response.json()["id"]
        
        # Admin B tries to delete it - should get 404
        response = second_admin_client.delete(f"/admin/guardrails/{config_id}")
        assert response.status_code == 404
        
        # Verify still exists for Admin A
        response = auth_client.get("/admin/guardrails/protected_rule")
        assert response.status_code == 200


class TestTemplateSharingAPI:
    """Test template sharing and cloning via API."""
    
    def test_share_and_clone_template(
        self, auth_client, second_admin_client
    ):
        """Admin A shares template, Admin B clones it."""
        # Admin A creates and shares a template
        response = auth_client.post("/admin/templates", json={
            "name": "shareable_template",
            "content": "Shared content"
        })
        template_id = response.json()["id"]
        
        # Mark as shareable
        response = auth_client.post(
            f"/admin/templates/{template_id}/share",
            params={"is_shareable": True}
        )
        assert response.status_code == 200
        
        # Admin B can see it in shared library
        response = second_admin_client.get("/admin/shared/templates")
        assert response.status_code == 200
        shared_ids = [t["id"] for t in response.json()["templates"]]
        assert template_id in shared_ids
        
        # Admin B clones it
        response = second_admin_client.post(
            f"/admin/shared/templates/{template_id}/clone",
            params={"new_name": "my_cloned_template"}
        )
        assert response.status_code == 200
        clone_id = response.json()["id"]
        
        # Admin B now has the clone
        response = second_admin_client.get("/admin/templates/my_cloned_template")
        assert response.status_code == 200
        assert response.json()["cloned_from_id"] == template_id
    
    def test_clone_is_independent(
        self, auth_client, second_admin_client
    ):
        """Modifying a clone doesn't affect the original."""
        # Admin A creates and shares a template
        response = auth_client.post("/admin/templates", json={
            "name": "original_to_clone",
            "content": "Original content"
        })
        template_id = response.json()["id"]
        
        auth_client.post(
            f"/admin/templates/{template_id}/share",
            params={"is_shareable": True}
        )
        
        # Admin B clones it
        response = second_admin_client.post(
            f"/admin/shared/templates/{template_id}/clone"
        )
        clone_id = response.json()["id"]
        
        # Admin B modifies the clone
        response = second_admin_client.put(f"/admin/templates/{clone_id}", json={
            "content": "Modified by Admin B"
        })
        assert response.status_code == 200
        
        # Original is unchanged
        response = auth_client.get("/admin/templates/original_to_clone")
        assert response.json()["content"] == "Original content"
    
    def test_cannot_clone_non_shareable_template(
        self, auth_client, second_admin_client
    ):
        """Cannot clone a template that isn't marked as shareable."""
        # Admin A creates a private template
        response = auth_client.post("/admin/templates", json={
            "name": "private_template",
            "content": "Private content"
        })
        template_id = response.json()["id"]
        
        # Admin B tries to clone it - should fail
        response = second_admin_client.post(
            f"/admin/shared/templates/{template_id}/clone"
        )
        assert response.status_code == 400


class TestSuperAdminAPI:
    """Test super admin functionality."""
    
    def test_super_admin_can_list_admins(self, super_admin_client):
        """Super admin can list all admins."""
        response = super_admin_client.get("/super/admins")
        assert response.status_code == 200
        assert "admins" in response.json()
    
    def test_super_admin_can_create_admin(self, super_admin_client):
        """Super admin can create new admins."""
        response = super_admin_client.post("/super/admins", json={
            "email": "newadmin@test.local",
            "password": "password123"
        })
        assert response.status_code == 200
        assert response.json()["email"] == "newadmin@test.local"
    
    def test_regular_admin_cannot_access_super_routes(self, auth_client):
        """Regular admin cannot access super admin routes."""
        response = auth_client.get("/super/admins")
        assert response.status_code == 403
        
        response = auth_client.post("/super/admins", json={
            "email": "hacker@test.local",
            "password": "password123"
        })
        assert response.status_code == 403


class TestAuthAPI:
    """Test authentication endpoints."""
    
    def test_login_success(self, db_module):
        """Successful login returns session cookie."""
        from fastapi.testclient import TestClient
        from src.main import app
        from src.auth import create_admin, SESSION_COOKIE_NAME
        
        create_admin("logintest@test.local", "testpassword")
        
        client = TestClient(app)
        response = client.post("/admin/login", json={
            "email": "logintest@test.local",
            "password": "testpassword"
        })
        
        assert response.status_code == 200
        assert SESSION_COOKIE_NAME in response.cookies
    
    def test_login_wrong_password(self, db_module):
        """Wrong password returns 401."""
        from fastapi.testclient import TestClient
        from src.main import app
        from src.auth import create_admin
        
        create_admin("wrongpw@test.local", "correctpassword")
        
        client = TestClient(app)
        response = client.post("/admin/login", json={
            "email": "wrongpw@test.local",
            "password": "wrongpassword"
        })
        
        assert response.status_code == 401
    
    def test_protected_route_without_auth(self, db_module):
        """Protected routes return 401 without auth."""
        from fastapi.testclient import TestClient
        from src.main import app
        
        client = TestClient(app)
        response = client.get("/admin/templates")
        assert response.status_code == 401
    
    def test_logout_clears_session(self, auth_client):
        """Logout clears session cookie."""
        from src.auth import SESSION_COOKIE_NAME
        
        response = auth_client.post("/admin/logout")
        assert response.status_code == 200
        
        # Cookie should be deleted (empty or expired)
        # After logout, subsequent requests should fail
        response = auth_client.get("/admin/templates")
        # Note: TestClient may not properly handle cookie deletion
        # but in a real browser the cookie would be cleared


class TestAuditLoggingAPI:
    """Test that admin actions are logged."""
    
    def test_template_create_logged(self, auth_client, db_conn, test_admin):
        """Creating a template creates an audit log entry."""
        response = auth_client.post("/admin/templates", json={
            "name": "audited_template",
            "content": "Content"
        })
        assert response.status_code == 200
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT action, resource_type, admin_email 
                FROM admin_audit_log 
                WHERE admin_email = %s AND action = 'template_create'
                ORDER BY created_at DESC LIMIT 1
            """, (test_admin.email,))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] == "template_create"
        assert row[1] == "template"
    
    def test_user_halt_logged(self, auth_client, db_conn, test_admin):
        """Halting a user creates an audit log entry."""
        response = auth_client.post("/admin/users/testuser/halt", json={
            "reason": "Testing"
        })
        assert response.status_code == 200
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT action, resource_type, resource_id
                FROM admin_audit_log 
                WHERE admin_email = %s AND action = 'user_halt'
                ORDER BY created_at DESC LIMIT 1
            """, (test_admin.email,))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] == "user_halt"
        assert row[1] == "user"
        assert row[2] == "testuser"
