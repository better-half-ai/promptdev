"""
Multi-tenant authentication module.

Provides:
- Super admin auth (from env vars)
- Regular admin auth (from database)
- Tenant isolation via admin_id
- Audit logging for all actions
"""

import os
from dataclasses import dataclass
from typing import Optional
import json

import bcrypt
from fastapi import Cookie, HTTPException, Request, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import db.db as db

# Session config
SESSION_COOKIE_NAME = "promptdev_admin_session"
SESSION_MAX_AGE = 86400  # 24 hours
SECRET_KEY = os.environ.get("SESSION_SECRET_KEY") or os.urandom(32).hex()

# Super admin from env
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL")
SUPER_ADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASSWORD")

_serializer = URLSafeTimedSerializer(SECRET_KEY)


@dataclass
class Admin:
    """Represents authenticated admin."""
    id: Optional[int]  # None for super admin
    email: str
    tenant_id: Optional[int]  # None for super admin (can access all)
    is_super: bool = False


# ============================================================
# Password hashing
# ============================================================

def hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ============================================================
# Session tokens
# ============================================================

def create_session_token(admin_id: Optional[int], email: str, is_super: bool) -> str:
    """Create signed session token."""
    return _serializer.dumps({
        "admin_id": admin_id,
        "email": email,
        "is_super": is_super
    })


def verify_session_token(token: str) -> Optional[dict]:
    """Verify session token and return payload if valid."""
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


# ============================================================
# Audit logging
# ============================================================

def audit_log(
    admin: Admin,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> None:
    """Log admin action to audit trail."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO admin_audit_log 
                (admin_id, admin_email, action, resource_type, resource_id, details, ip_address, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                admin.id,
                admin.email,
                action,
                resource_type,
                resource_id,
                json.dumps(details) if details else None,
                ip_address,
                user_agent
            ))
            conn.commit()
    finally:
        db.put_conn(conn)


def audit_log_from_request(
    admin: Admin,
    request: Request,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None
) -> None:
    """Log admin action with request context."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    audit_log(admin, action, resource_type, resource_id, details, ip, ua)


# ============================================================
# Admin CRUD
# ============================================================

def get_admin_by_email(email: str) -> Optional[dict]:
    """Get admin by email."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, password_hash, is_active, created_at, last_login
                FROM admins WHERE email = %s
            """, (email,))
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "email": row[1],
                    "password_hash": row[2],
                    "is_active": row[3],
                    "created_at": row[4],
                    "last_login": row[5],
                }
            return None
    finally:
        db.put_conn(conn)


def get_admin_by_id(admin_id: int) -> Optional[dict]:
    """Get admin by ID."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, password_hash, is_active, created_at, last_login
                FROM admins WHERE id = %s
            """, (admin_id,))
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "email": row[1],
                    "password_hash": row[2],
                    "is_active": row[3],
                    "created_at": row[4],
                    "last_login": row[5],
                }
            return None
    finally:
        db.put_conn(conn)


def create_admin(email: str, password: str, created_by: Optional[int] = None) -> int:
    """
    Create new admin.
    Returns admin ID.
    Raises ValueError if email already exists.
    """
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO admins (email, password_hash, created_by)
                VALUES (%s, %s, %s) RETURNING id
            """, (email, hash_password(password), created_by))
            admin_id = cur.fetchone()[0]
            conn.commit()
            return admin_id
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise ValueError(f"Email '{email}' already exists")
        raise
    finally:
        db.put_conn(conn)


def update_admin_last_login(admin_id: int) -> None:
    """Update last_login timestamp."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE admins SET last_login = NOW() WHERE id = %s",
                (admin_id,)
            )
            conn.commit()
    finally:
        db.put_conn(conn)


def list_admins() -> list[dict]:
    """List all admins (for super admin)."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, is_active, created_at, created_by, last_login
                FROM admins ORDER BY created_at DESC
            """)
            return [
                {
                    "id": row[0],
                    "email": row[1],
                    "is_active": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "created_by": row[4],
                    "last_login": row[5].isoformat() if row[5] else None,
                }
                for row in cur.fetchall()
            ]
    finally:
        db.put_conn(conn)


def update_admin(admin_id: int, is_active: Optional[bool] = None, password: Optional[str] = None) -> bool:
    """Update admin. Returns True if updated."""
    conn = db.get_conn()
    try:
        updates = []
        params = []
        
        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)
        
        if password is not None:
            updates.append("password_hash = %s")
            params.append(hash_password(password))
        
        if not updates:
            return False
        
        params.append(admin_id)
        
        with conn.cursor() as cur:
            cur.execute(f"""
                UPDATE admins SET {', '.join(updates)} WHERE id = %s
            """, params)
            conn.commit()
            return cur.rowcount > 0
    finally:
        db.put_conn(conn)


def delete_admin(admin_id: int) -> bool:
    """Delete admin. Returns True if deleted."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admins WHERE id = %s", (admin_id,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        db.put_conn(conn)


# ============================================================
# Authentication
# ============================================================

def authenticate(email: str, password: str) -> Optional[Admin]:
    """
    Authenticate admin and return Admin object if valid.
    Checks super admin first, then database.
    """
    # Check super admin
    if SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD:
        if email == SUPER_ADMIN_EMAIL and password == SUPER_ADMIN_PASSWORD:
            return Admin(id=None, email=email, tenant_id=None, is_super=True)
    
    # Check database admin
    admin = get_admin_by_email(email)
    if not admin:
        return None
    
    if not admin["is_active"]:
        return None
    
    if not verify_password(password, admin["password_hash"]):
        return None
    
    update_admin_last_login(admin["id"])
    return Admin(id=admin["id"], email=admin["email"], tenant_id=admin["id"], is_super=False)


# ============================================================
# FastAPI dependencies
# ============================================================

async def get_current_admin(
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)
) -> Admin:
    """
    FastAPI dependency that requires valid admin session.
    Returns Admin object with tenant_id.
    Raises 401 if not authenticated.
    """
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )
    
    payload = verify_session_token(session)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Cookie"},
        )
    
    # Super admin
    if payload.get("is_super"):
        if not SUPER_ADMIN_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Super admin not configured",
            )
        return Admin(
            id=None,
            email=payload["email"],
            tenant_id=None,
            is_super=True
        )
    
    # Regular admin - verify still exists and active
    admin = get_admin_by_id(payload["admin_id"])
    if not admin or not admin["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin not found or inactive",
            headers={"WWW-Authenticate": "Cookie"},
        )
    
    return Admin(
        id=admin["id"],
        email=admin["email"],
        tenant_id=admin["id"],
        is_super=False
    )


def super_admin_required(
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)
) -> Admin:
    """FastAPI dependency that requires super admin."""
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    
    payload = verify_session_token(session)
    if not payload or not payload.get("is_super"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    
    return Admin(
        id=None,
        email=payload["email"],
        tenant_id=None,
        is_super=True
    )
