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
        from src.auth import create_admin
        from db.db import get_conn, put_conn
        
        admin_id = create_admin("newadmin@example.com", "password123")
        
        assert admin_id > 0
        
        # Verify in DB directly
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT email, is_active FROM admins WHERE id = %s", (admin_id,))
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "newadmin@example.com"
                assert row[1] is True
        finally:
            put_conn(conn)
    
    def test_create_duplicate_admin_fails(self, db_module):
        from src.auth import create_admin
        
        create_admin("dupe@example.com", "password123")
        
        with pytest.raises(ValueError, match="already exists"):
            create_admin("dupe@example.com", "password456")
    
    def test_list_admins(self, db_module):
        from src.auth import create_admin, list_admins
        
        create_admin("list1@example.com", "password123")
        create_admin("list2@example.com", "password123")
        
        admins = list_admins()
        emails = [a["email"] for a in admins]
        
        assert "list1@example.com" in emails
        assert "list2@example.com" in emails
    
    def test_update_admin_deactivate(self, db_module):
        from src.auth import create_admin, update_admin
        from db.db import get_conn, put_conn
        
        admin_id = create_admin("deactivate@example.com", "password123")
        
        update_admin(admin_id, is_active=False)
        
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT is_active FROM admins WHERE id = %s", (admin_id,))
                row = cur.fetchone()
                assert row[0] is False
        finally:
            put_conn(conn)
    
    def test_update_admin_password(self, db_module):
        from src.auth import create_admin, update_admin, verify_password
        from db.db import get_conn, put_conn
        
        admin_id = create_admin("updatepw@example.com", "oldpassword")
        
        update_admin(admin_id, password="newpassword123")
        
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM admins WHERE id = %s", (admin_id,))
                row = cur.fetchone()
                assert verify_password("newpassword123", row[0]) is True
                assert verify_password("oldpassword", row[0]) is False
        finally:
            put_conn(conn)
    
    def test_delete_admin(self, db_module):
        from src.auth import create_admin, delete_admin
        from db.db import get_conn, put_conn
        
        admin_id = create_admin("todelete@example.com", "password123")
        
        result = delete_admin(admin_id)
        
        assert result is True
        # delete_admin does soft delete (sets is_active=False)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT is_active FROM admins WHERE id = %s", (admin_id,))
                row = cur.fetchone()
                assert row[0] is False
        finally:
            put_conn(conn)


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
        assert admin.tenant_id == admin.id
    
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
        from src.auth import create_admin, update_admin, authenticate
        
        admin_id = create_admin("inactive@example.com", "password123")
        update_admin(admin_id, is_active=False)
        
        admin = authenticate("inactive@example.com", "password123")
        
        assert admin is None


# ============================================================
# Audit Logging Tests
# ============================================================

class TestAuditLogging:
    """Test audit log functionality."""
    
    def test_audit_log_creates_entry(self, db_module, db_conn):
        from src.auth import create_admin, audit_log, Admin
        
        admin_id = create_admin("audituser@example.com", "password123")
        admin = Admin(id=admin_id, email="audituser@example.com", is_super=False)
        
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
                SELECT admin_id, action, resource_type, resource_id, ip_address
                FROM admin_audit_log WHERE admin_id = %s
            """, (admin_id,))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] == admin_id
        assert row[1] == "test_action"
        assert row[2] == "test"
        assert row[3] == "123"
        assert row[4] == "127.0.0.1"
    
    def test_audit_log_super_admin(self, db_module, db_conn):
        from src.auth import audit_log, Admin
        
        admin = Admin(id=None, email="super@admin.com", is_super=True)
        
        audit_log(
            admin=admin,
            action="super_action",
            resource_type="admin",
            resource_id="new_admin"
        )
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT admin_id, action FROM admin_audit_log 
                WHERE action = %s
            """, ("super_action",))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] is None  # super admin has no ID
        assert row[1] == "super_action"


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
    
    def test_super_admin_tenant_id_is_none(self, db_module):
        from src.auth import Admin
        
        admin = Admin(id=None, email="super@example.com", is_super=True)
        
        # For super admin with id=None, tenant_id property returns None
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
            await get_current_admin(admin_session=None)
        
        assert exc.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_current_admin_invalid_session(self, db_module):
        from fastapi import HTTPException
        from src.auth import get_current_admin
        
        with pytest.raises(HTTPException) as exc:
            await get_current_admin(admin_session="invalid.token.here")
        
        assert exc.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_current_admin_valid_session(self, db_module):
        from src.auth import create_admin, create_session_token, get_current_admin
        
        admin_id = create_admin("dep@example.com", "password123")
        token = create_session_token(admin_id=admin_id, email="dep@example.com", is_super=False)
        
        admin = await get_current_admin(admin_session=token)
        
        assert admin.email == "dep@example.com"
        assert admin.tenant_id == admin_id
    
    @pytest.mark.asyncio
    async def test_super_admin_required_not_super(self, db_module):
        from fastapi import HTTPException
        from src.auth import create_admin, Admin, super_admin_required
        
        admin_id = create_admin("notsup@example.com", "password123")
        admin = Admin(id=admin_id, email="notsup@example.com", is_super=False)
        
        with pytest.raises(HTTPException) as exc:
            await super_admin_required(admin=admin)
        
        assert exc.value.status_code == 403
    
    @pytest.mark.asyncio
    async def test_super_admin_required_is_super(self, db_module):
        from src.auth import Admin, super_admin_required
        
        admin = Admin(id=None, email="super@example.com", is_super=True)
        
        result = await super_admin_required(admin=admin)
        
        assert result.is_super is True
