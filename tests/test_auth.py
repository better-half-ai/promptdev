"""
Tests for multi-tenant authentication system.

Tests:
- Password hashing
- Session tokens
- Super admin auth
- Regular admin CRUD
- Authentication flow
- Tenant isolation
- Audit logging
"""

import os
import pytest
from unittest.mock import patch

from conftest import (
    TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD,
    TEST_SUPER_EMAIL, TEST_SUPER_PASSWORD
)


# ============================================================
# Password Hashing Tests
# ============================================================

class TestPasswordHashing:
    """Test bcrypt password hashing."""
    
    def test_hash_password_returns_bcrypt_hash(self, db_module):
        from src.auth import hash_password
        
        hashed = hash_password("testpassword123")
        
        assert hashed != "testpassword123"
        assert hashed.startswith("$2b$")
    
    def test_hash_password_different_each_time(self, db_module):
        from src.auth import hash_password
        
        hash1 = hash_password("testpassword123")
        hash2 = hash_password("testpassword123")
        
        assert hash1 != hash2  # Different salts
    
    def test_verify_password_correct(self, db_module):
        from src.auth import hash_password, verify_password
        
        hashed = hash_password("testpassword123")
        
        assert verify_password("testpassword123", hashed) is True
    
    def test_verify_password_incorrect(self, db_module):
        from src.auth import hash_password, verify_password
        
        hashed = hash_password("testpassword123")
        
        assert verify_password("wrongpassword", hashed) is False


# ============================================================
# Session Token Tests
# ============================================================

class TestSessionTokens:
    """Test session token creation and verification."""
    
    def test_create_session_token_regular_admin(self, db_module):
        from src.auth import create_session_token
        
        token = create_session_token(admin_id=1, email="test@example.com", is_super=False)
        
        assert token is not None
        assert len(token) > 0
    
    def test_create_session_token_super_admin(self, db_module):
        from src.auth import create_session_token
        
        token = create_session_token(admin_id=None, email="super@example.com", is_super=True)
        
        assert token is not None
    
    def test_verify_valid_token(self, db_module):
        from src.auth import create_session_token, verify_session_token
        
        token = create_session_token(admin_id=1, email="test@example.com", is_super=False)
        payload = verify_session_token(token)
        
        assert payload is not None
        assert payload["admin_id"] == 1
        assert payload["email"] == "test@example.com"
        assert payload["is_super"] is False
    
    def test_verify_super_admin_token(self, db_module):
        from src.auth import create_session_token, verify_session_token
        
        token = create_session_token(admin_id=None, email="super@example.com", is_super=True)
        payload = verify_session_token(token)
        
        assert payload["admin_id"] is None
        assert payload["is_super"] is True
    
    def test_verify_invalid_token(self, db_module):
        from src.auth import verify_session_token
        
        payload = verify_session_token("invalid.token.here")
        
        assert payload is None
    
    def test_verify_tampered_token(self, db_module):
        from src.auth import create_session_token, verify_session_token
        
        token = create_session_token(admin_id=1, email="test@example.com", is_super=False)
        tampered = token[:-5] + "XXXXX"
        
        assert verify_session_token(tampered) is None


# ============================================================
# Admin CRUD Tests
# ============================================================

class TestAdminCRUD:
    """Test admin create, read, update, delete."""
    
    def test_create_admin(self, db_module):
        from src.auth import create_admin, get_admin_by_email
        
        admin_id = create_admin("newadmin@example.com", "password123")
        
        assert admin_id > 0
        
        admin = get_admin_by_email("newadmin@example.com")
        assert admin is not None
        assert admin["email"] == "newadmin@example.com"
        assert admin["is_active"] is True
    
    def test_create_duplicate_admin_fails(self, db_module):
        from src.auth import create_admin
        
        create_admin("dupe@example.com", "password123")
        
        with pytest.raises(ValueError, match="already exists"):
            create_admin("dupe@example.com", "password456")
    
    def test_get_admin_by_id(self, db_module):
        from src.auth import create_admin, get_admin_by_id
        
        admin_id = create_admin("byid@example.com", "password123")
        
        admin = get_admin_by_id(admin_id)
        assert admin is not None
        assert admin["email"] == "byid@example.com"
    
    def test_get_nonexistent_admin(self, db_module):
        from src.auth import get_admin_by_email, get_admin_by_id
        
        assert get_admin_by_email("nonexistent@example.com") is None
        assert get_admin_by_id(99999) is None
    
    def test_list_admins(self, db_module):
        from src.auth import create_admin, list_admins
        
        create_admin("list1@example.com", "password123")
        create_admin("list2@example.com", "password123")
        
        admins = list_admins()
        emails = [a["email"] for a in admins]
        
        assert "list1@example.com" in emails
        assert "list2@example.com" in emails
    
    def test_update_admin_deactivate(self, db_module):
        from src.auth import create_admin, get_admin_by_id, update_admin
        
        admin_id = create_admin("deactivate@example.com", "password123")
        
        update_admin(admin_id, is_active=False)
        
        admin = get_admin_by_id(admin_id)
        assert admin["is_active"] is False
    
    def test_update_admin_password(self, db_module):
        from src.auth import create_admin, get_admin_by_id, update_admin, verify_password
        
        admin_id = create_admin("updatepw@example.com", "oldpassword")
        
        update_admin(admin_id, password="newpassword123")
        
        admin = get_admin_by_id(admin_id)
        assert verify_password("newpassword123", admin["password_hash"]) is True
        assert verify_password("oldpassword", admin["password_hash"]) is False
    
    def test_delete_admin(self, db_module):
        from src.auth import create_admin, get_admin_by_id, delete_admin
        
        admin_id = create_admin("todelete@example.com", "password123")
        
        result = delete_admin(admin_id)
        
        assert result is True
        assert get_admin_by_id(admin_id) is None


# ============================================================
# Authentication Tests
# ============================================================

class TestAuthentication:
    """Test authentication flow."""
    
    def test_authenticate_regular_admin(self, db_module):
        from src.auth import create_admin, authenticate
        
        create_admin("auth@example.com", "correctpassword")
        
        admin = authenticate("auth@example.com", "correctpassword")
        
        assert admin is not None
        assert admin.email == "auth@example.com"
        assert admin.is_super is False
        assert admin.tenant_id is not None
    
    def test_authenticate_wrong_password(self, db_module):
        from src.auth import create_admin, authenticate
        
        create_admin("wrongpw@example.com", "correctpassword")
        
        admin = authenticate("wrongpw@example.com", "wrongpassword")
        
        assert admin is None
    
    def test_authenticate_nonexistent_admin(self, db_module):
        from src.auth import authenticate
        
        admin = authenticate("nobody@example.com", "password")
        
        assert admin is None
    
    def test_authenticate_inactive_admin(self, db_module):
        from src.auth import create_admin, update_admin, authenticate, get_admin_by_email
        
        create_admin("inactive@example.com", "password123")
        admin_data = get_admin_by_email("inactive@example.com")
        update_admin(admin_data["id"], is_active=False)
        
        admin = authenticate("inactive@example.com", "password123")
        
        assert admin is None
    
    @patch.dict(os.environ, {"SUPER_ADMIN_EMAIL": "super@test.com", "SUPER_ADMIN_PASSWORD": "supersecret"})
    def test_authenticate_super_admin(self, db_module):
        # Need to reload module to pick up env vars
        import importlib
        import src.auth
        importlib.reload(src.auth)
        
        admin = src.auth.authenticate("super@test.com", "supersecret")
        
        assert admin is not None
        assert admin.is_super is True
        assert admin.tenant_id is None
    
    @patch.dict(os.environ, {"SUPER_ADMIN_EMAIL": "super@test.com", "SUPER_ADMIN_PASSWORD": "supersecret"})
    def test_authenticate_super_admin_wrong_password(self, db_module):
        import importlib
        import src.auth
        importlib.reload(src.auth)
        
        admin = src.auth.authenticate("super@test.com", "wrongpassword")
        
        # Should not authenticate as super admin, and not in DB either
        assert admin is None


# ============================================================
# Audit Logging Tests
# ============================================================

class TestAuditLogging:
    """Test audit log functionality."""
    
    def test_audit_log_creates_entry(self, db_module, db_conn):
        from src.auth import create_admin, audit_log, Admin
        
        admin_id = create_admin("audituser@example.com", "password123")
        admin = Admin(id=admin_id, email="audituser@example.com", tenant_id=admin_id, is_super=False)
        
        audit_log(
            admin=admin,
            action="test_action",
            resource_type="test",
            resource_id="123",
            details={"foo": "bar"},
            ip_address="127.0.0.1",
            user_agent="TestAgent"
        )
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT admin_id, admin_email, action, resource_type, resource_id, details, ip_address
                FROM admin_audit_log WHERE admin_email = %s
            """, ("audituser@example.com",))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] == admin_id
        assert row[1] == "audituser@example.com"
        assert row[2] == "test_action"
        assert row[3] == "test"
        assert row[4] == "123"
        assert row[6] == "127.0.0.1"
    
    def test_audit_log_super_admin(self, db_module, db_conn):
        from src.auth import audit_log, Admin
        
        admin = Admin(id=None, email="super@admin.com", tenant_id=None, is_super=True)
        
        audit_log(
            admin=admin,
            action="super_action",
            resource_type="admin",
            resource_id="new_admin"
        )
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT admin_id, admin_email, action FROM admin_audit_log 
                WHERE admin_email = %s
            """, ("super@admin.com",))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] is None  # super admin has no ID
        assert row[1] == "super@admin.com"


# ============================================================
# Tenant Isolation Tests
# ============================================================

class TestTenantIsolation:
    """Test that data is isolated per tenant."""
    
    def test_admin_tenant_id_equals_admin_id(self, db_module):
        from src.auth import create_admin, authenticate
        
        create_admin("tenant1@example.com", "password123")
        
        admin = authenticate("tenant1@example.com", "password123")
        
        assert admin.tenant_id == admin.id
    
    def test_super_admin_has_no_tenant(self, db_module):
        from src.auth import Admin
        
        admin = Admin(id=None, email="super@example.com", tenant_id=None, is_super=True)
        
        assert admin.tenant_id is None
        assert admin.is_super is True


# ============================================================
# FastAPI Dependency Tests
# ============================================================

class TestFastAPIDependencies:
    """Test FastAPI auth dependencies."""
    
    @pytest.mark.asyncio
    async def test_get_current_admin_no_session(self, db_module):
        from fastapi import HTTPException
        from src.auth import get_current_admin
        
        with pytest.raises(HTTPException) as exc:
            await get_current_admin(session=None)
        
        assert exc.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_current_admin_invalid_session(self, db_module):
        from fastapi import HTTPException
        from src.auth import get_current_admin
        
        with pytest.raises(HTTPException) as exc:
            await get_current_admin(session="invalid")
        
        assert exc.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_current_admin_valid_session(self, db_module):
        from src.auth import create_admin, create_session_token, get_current_admin
        
        admin_id = create_admin("dep@example.com", "password123")
        token = create_session_token(admin_id=admin_id, email="dep@example.com", is_super=False)
        
        admin = await get_current_admin(session=token)
        
        assert admin.email == "dep@example.com"
        assert admin.tenant_id == admin_id
    
    def test_super_admin_required_not_super(self, db_module):
        from fastapi import HTTPException
        from src.auth import create_admin, create_session_token, super_admin_required
        
        admin_id = create_admin("notsup@example.com", "password123")
        token = create_session_token(admin_id=admin_id, email="notsup@example.com", is_super=False)
        
        with pytest.raises(HTTPException) as exc:
            super_admin_required(session=token)
        
        assert exc.value.status_code == 403
    
    def test_super_admin_required_is_super(self, db_module):
        from src.auth import create_session_token, super_admin_required
        
        token = create_session_token(admin_id=None, email="super@example.com", is_super=True)
        
        admin = super_admin_required(session=token)
        
        assert admin.is_super is True
