"""
Authentication module for PromptDev.

Supports two auth realms:
- Admin: operators who manage templates, monitor users, intervene
- End User: chat users who belong to a tenant

Both use cookie-based sessions with JWT tokens.
"""

import os
import logging
import secrets
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional, Literal
from enum import Enum

import jwt
import bcrypt
import psycopg2.extras
from fastapi import HTTPException, status, Cookie, Request, Depends

from db.db import get_conn, put_conn

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"

ADMIN_SESSION_COOKIE = "promptdev_admin"
ADMIN_SESSION_MAX_AGE = 86400 * 7  # 7 days

USER_SESSION_COOKIE = "promptdev_user"
USER_SESSION_MAX_AGE = 86400 * 30  # 30 days


class UserType(str, Enum):
    ADMIN = "admin"
    END_USER = "end_user"


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Admin:
    """Admin user (tenant owner)."""
    id: int
    email: str
    is_super: bool = False

    @property
    def tenant_id(self) -> int:
        return self.id


@dataclass
class EndUser:
    """End user (chat user within a tenant)."""
    id: int
    tenant_id: int
    external_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None


@dataclass
class AuthContext:
    """
    Unified auth context for all authenticated requests.

    Provides tenant_id regardless of whether requester is admin or end user.
    """
    tenant_id: int
    user_type: UserType
    user_id: str  # admin.email or end_user.external_id

    # Original objects for detailed access
    admin: Optional[Admin] = None
    end_user: Optional[EndUser] = None

    @property
    def is_admin(self) -> bool:
        return self.user_type == UserType.ADMIN

    @property
    def is_end_user(self) -> bool:
        return self.user_type == UserType.END_USER


# ═══════════════════════════════════════════════════════════════════════════
# PASSWORD UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# JWT TOKEN UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def create_token(payload: dict, expires_in: int) -> str:
    """Create a JWT token."""
    exp = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    payload["exp"] = exp
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid token: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN AUTH
# ═══════════════════════════════════════════════════════════════════════════

def create_admin_session(admin: Admin) -> str:
    """Create session token for admin."""
    return create_token({
        "type": "admin",
        "admin_id": admin.id,
        "email": admin.email,
        "is_super": admin.is_super,
    }, ADMIN_SESSION_MAX_AGE)


def verify_admin_session(token: str) -> Optional[Admin]:
    """Verify admin session token."""
    payload = verify_token(token)
    if not payload or payload.get("type") != "admin":
        return None
    return Admin(
        id=payload["admin_id"],
        email=payload["email"],
        is_super=payload.get("is_super", False)
    )


def authenticate_admin(email: str, password: str) -> Optional[Admin]:
    """Authenticate admin by email and password."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, password_hash, is_active, COALESCE(is_super, false)
                FROM admins WHERE email = %s
                """,
                (email,)
            )
            row = cur.fetchone()
            if not row:
                return None

            admin_id, admin_email, password_hash, is_active, is_super = row

            if not is_active:
                return None

            if not verify_password(password, password_hash):
                return None

            # Update last_login
            cur.execute(
                "UPDATE admins SET last_login = NOW() WHERE id = %s",
                (admin_id,)
            )
            conn.commit()

            return Admin(id=admin_id, email=admin_email, is_super=is_super)
    finally:
        put_conn(conn)


def create_admin(email: str, password: str, created_by: str = None) -> int:
    """Create a new admin."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admins (email, password_hash, created_by)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (email, hash_password(password), created_by)
            )
            admin_id = cur.fetchone()[0]
            conn.commit()
            return admin_id
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            raise ValueError(f"Admin with email {email} already exists")
        raise
    finally:
        put_conn(conn)


def list_admins() -> list[dict]:
    """List all admins."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, is_active, created_at, last_login
                FROM admins ORDER BY id
                """
            )
            return [
                {
                    "id": row[0],
                    "email": row[1],
                    "is_active": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "last_login": row[4].isoformat() if row[4] else None,
                }
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def get_admin_by_email(email: str) -> Optional[Admin]:
    """Get admin by email."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, COALESCE(is_super, false) FROM admins WHERE email = %s AND is_active = true",
                (email,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return Admin(id=row[0], email=row[1], is_super=row[2])
    finally:
        put_conn(conn)


def update_admin(admin_id: int, is_active: bool = None, password: str = None) -> bool:
    """Update admin."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            updates = []
            params = []

            if is_active is not None:
                updates.append("is_active = %s")
                params.append(is_active)

            if password is not None:
                updates.append("password_hash = %s")
                params.append(hash_password(password))

            if not updates:
                return True

            params.append(admin_id)
            cur.execute(
                f"UPDATE admins SET {', '.join(updates)} WHERE id = %s",
                params
            )
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_conn(conn)


def delete_admin(admin_id: int) -> bool:
    """Delete admin (soft delete by deactivating)."""
    return update_admin(admin_id, is_active=False)


# ═══════════════════════════════════════════════════════════════════════════
# END USER AUTH
# ═══════════════════════════════════════════════════════════════════════════

def create_user_session(user: EndUser) -> str:
    """Create session token for end user."""
    return create_token({
        "type": "end_user",
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "external_id": user.external_id,
    }, USER_SESSION_MAX_AGE)


def verify_user_session(token: str) -> Optional[EndUser]:
    """Verify end user session token."""
    payload = verify_token(token)
    if not payload or payload.get("type") != "end_user":
        return None
    return EndUser(
        id=payload["user_id"],
        tenant_id=payload["tenant_id"],
        external_id=payload["external_id"]
    )


def authenticate_end_user(tenant_id: int, email: str, password: str) -> Optional[EndUser]:
    """Authenticate end user by email and password within a tenant."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, external_id, email, display_name, password_hash, is_active
                FROM end_users
                WHERE tenant_id = %s AND email = %s
                """,
                (tenant_id, email)
            )
            row = cur.fetchone()
            if not row:
                return None

            user_id, tid, external_id, user_email, display_name, password_hash, is_active = row

            if not is_active:
                return None

            if not password_hash or not verify_password(password, password_hash):
                return None

            # Update last_seen
            cur.execute(
                "UPDATE end_users SET last_seen = NOW() WHERE id = %s",
                (user_id,)
            )
            conn.commit()

            return EndUser(
                id=user_id,
                tenant_id=tid,
                external_id=external_id,
                email=user_email,
                display_name=display_name
            )
    finally:
        put_conn(conn)


def create_end_user(
    tenant_id: int,
    external_id: str,
    email: str = None,
    password: str = None,
    display_name: str = None,
    metadata: dict = None
) -> EndUser:
    """Create a new end user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            password_hash = hash_password(password) if password else None
            cur.execute(
                """
                INSERT INTO end_users (tenant_id, external_id, email, password_hash, display_name, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, external_id, email, password_hash, display_name, metadata or {})
            )
            user_id = cur.fetchone()[0]
            conn.commit()

            return EndUser(
                id=user_id,
                tenant_id=tenant_id,
                external_id=external_id,
                email=email,
                display_name=display_name
            )
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            raise ValueError(f"User already exists in this tenant")
        raise
    finally:
        put_conn(conn)


def get_end_user(tenant_id: int, external_id: str) -> Optional[EndUser]:
    """Get end user by external_id within a tenant."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, external_id, email, display_name
                FROM end_users
                WHERE tenant_id = %s AND external_id = %s AND is_active = true
                """,
                (tenant_id, external_id)
            )
            row = cur.fetchone()
            if not row:
                return None
            return EndUser(
                id=row[0],
                tenant_id=row[1],
                external_id=row[2],
                email=row[3],
                display_name=row[4]
            )
    finally:
        put_conn(conn)


def get_end_user_by_id(user_id: int) -> Optional[EndUser]:
    """Get end user by ID."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, external_id, email, display_name
                FROM end_users WHERE id = %s AND is_active = true
                """,
                (user_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return EndUser(
                id=row[0],
                tenant_id=row[1],
                external_id=row[2],
                email=row[3],
                display_name=row[4]
            )
    finally:
        put_conn(conn)


def list_end_users(tenant_id: int, include_inactive: bool = False) -> list[dict]:
    """List all end users for a tenant."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = "WHERE tenant_id = %s"
            if not include_inactive:
                where += " AND is_active = true"

            cur.execute(
                f"""
                SELECT id, external_id, email, display_name, created_at, last_seen, is_active
                FROM end_users {where}
                ORDER BY created_at DESC
                """,
                (tenant_id,)
            )
            return [
                {
                    "id": row[0],
                    "external_id": row[1],
                    "email": row[2],
                    "display_name": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "last_seen": row[5].isoformat() if row[5] else None,
                    "is_active": row[6],
                }
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def update_end_user(
    user_id: int,
    email: str = None,
    password: str = None,
    display_name: str = None,
    is_active: bool = None,
    metadata: dict = None
) -> bool:
    """Update end user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            updates = ["updated_at = NOW()"]
            params = []

            if email is not None:
                updates.append("email = %s")
                params.append(email)

            if password is not None:
                updates.append("password_hash = %s")
                params.append(hash_password(password))

            if display_name is not None:
                updates.append("display_name = %s")
                params.append(display_name)

            if is_active is not None:
                updates.append("is_active = %s")
                params.append(is_active)

            if metadata is not None:
                updates.append("metadata = %s")
                params.append(metadata)

            params.append(user_id)
            cur.execute(
                f"UPDATE end_users SET {', '.join(updates)} WHERE id = %s",
                params
            )
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_conn(conn)


def delete_end_user(user_id: int, hard: bool = False) -> bool:
    """Delete end user."""
    if hard:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM end_users WHERE id = %s", (user_id,))
                conn.commit()
                return cur.rowcount > 0
        finally:
            put_conn(conn)
    else:
        return update_end_user(user_id, is_active=False)


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════

async def get_current_admin(
    admin_session: Optional[str] = Cookie(None, alias=ADMIN_SESSION_COOKIE)
) -> Admin:
    """
    FastAPI dependency: requires valid admin session.
    Raises 401 if not authenticated.
    """
    if not admin_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )

    admin = verify_admin_session(admin_session)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Cookie"},
        )

    return admin


async def super_admin_required(
    admin: Admin = Depends(get_current_admin)
) -> Admin:
    """FastAPI dependency: requires super admin."""
    if not admin.is_super:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required"
        )
    return admin


async def get_current_end_user(
    user_session: Optional[str] = Cookie(None, alias=USER_SESSION_COOKIE)
) -> EndUser:
    """
    FastAPI dependency: requires valid end user session.
    Raises 401 if not authenticated.
    """
    if not user_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )

    user = verify_user_session(user_session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Cookie"},
        )

    return user


async def get_auth_context(
    admin_session: Optional[str] = Cookie(None, alias=ADMIN_SESSION_COOKIE),
    user_session: Optional[str] = Cookie(None, alias=USER_SESSION_COOKIE)
) -> AuthContext:
    """
    FastAPI dependency: accepts either admin or end user session.

    Priority: admin > end_user

    Returns AuthContext with tenant_id for all DB operations.
    Raises 401 if neither authenticated.
    """
    # Try admin first
    if admin_session:
        admin = verify_admin_session(admin_session)
        if admin:
            return AuthContext(
                tenant_id=admin.tenant_id,
                user_type=UserType.ADMIN,
                user_id=admin.email,
                admin=admin
            )

    # Try end user
    if user_session:
        user = verify_user_session(user_session)
        if user:
            return AuthContext(
                tenant_id=user.tenant_id,
                user_type=UserType.END_USER,
                user_id=user.external_id,
                end_user=user
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Cookie"},
    )


async def get_optional_auth_context(
    admin_session: Optional[str] = Cookie(None, alias=ADMIN_SESSION_COOKIE),
    user_session: Optional[str] = Cookie(None, alias=USER_SESSION_COOKIE)
) -> Optional[AuthContext]:
    """
    FastAPI dependency: optionally authenticated.
    Returns None if not authenticated.
    """
    try:
        return await get_auth_context(admin_session, user_session)
    except HTTPException:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT LOGGING
# ═══════════════════════════════════════════════════════════════════════════

def audit_log(
    admin: Admin,
    action: str,
    resource_type: str = None,
    resource_id: str = None,
    details: dict = None,
    ip_address: str = None,
    user_agent: str = None
) -> int:
    """Record an audit log entry."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_audit_log
                (admin_id, admin_email, action, resource_type, resource_id, details, ip_address, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (admin.id, admin.email, action, resource_type, resource_id,
                 psycopg2.extras.Json(details) if details else None, ip_address, user_agent)
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
    finally:
        put_conn(conn)


def audit_log_from_request(
    admin: Admin,
    request: Request,
    action: str,
    resource_type: str = None,
    resource_id: str = None,
    details: dict = None
) -> int:
    """Record audit log with request context."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return audit_log(admin, action, resource_type, resource_id, details, ip, ua)


# ═══════════════════════════════════════════════════════════════════════════
# EXPORTS (backwards compatibility)
# ═══════════════════════════════════════════════════════════════════════════

# Old names for compatibility
SESSION_COOKIE_NAME = ADMIN_SESSION_COOKIE
SESSION_MAX_AGE = ADMIN_SESSION_MAX_AGE

def authenticate(email: str, password: str) -> Optional[Admin]:
    """Alias for authenticate_admin."""
    return authenticate_admin(email, password)

def create_session_token(admin_id: int, email: str, is_super: bool = False) -> str:
    """Create admin session token (backwards compatible)."""
    return create_admin_session(Admin(id=admin_id, email=email, is_super=is_super))

def verify_session_token(token: str) -> Optional[dict]:
    """Verify admin session token (backwards compatible)."""
    admin = verify_admin_session(token)
    if not admin:
        return None
    return {
        "admin_id": admin.id,
        "email": admin.email,
        "is_super": admin.is_super
    }
