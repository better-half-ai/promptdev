"""
FastAPI application for PromptDev - Multi-tenant prompt engineering workbench.

This module provides:
- User endpoints: Chat, history management
- Admin endpoints: Template management, monitoring, interventions
- Guardrails: Preset configurations and custom restrictions
- Interventions: Halt, resume, inject capabilities

Architecture:
- Users chat via /chat endpoint (templates applied transparently)
- Operators manage templates, view conversations, intervene when needed
- Each admin (tenant) has isolated templates, users, guardrails
- tenant_id flows from authenticated session to all DB operations
"""

import logging
import time
from typing import Optional, Any
from datetime import datetime, UTC
from fastapi import FastAPI, HTTPException, Query, Depends, Response, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from pydantic import BaseModel, Field

# Import from other modules
from src.prompts import (
    create_template,
    update_template,
    get_template,
    get_template_by_name,
    list_templates,
    get_version_history,
    rollback_to_version,
    delete_template,
    set_template_shareable,
    list_shared_templates,
    clone_template,
    TemplateNotFoundError,
    PromptError,
)
from src.memory import (
    add_message,
    get_conversation_history,
    get_recent_messages,
    count_messages,
    clear_conversation_history,
    list_users,
    set_memory,
    get_memory,
    get_all_memory,
    delete_memory,
    get_user_state,
    set_user_state,
    delete_user_state,
    halt_user,
    resume_user,
    is_user_halted,
    list_halted_users,
    UserState,
)
from src.context import (
    build_prompt_context,
    build_prompt_context_simple,
    get_context_summary,
)
from src.guardrails import (
    create_config as create_guardrail,
    get_config as get_guardrail,
    get_config_by_id,
    list_configs as list_guardrails,
    update_config as update_guardrail,
    delete_config as delete_guardrail,
    apply_guardrails,
    get_preset_names,
    GuardrailNotFoundError,
    InvalidRulesError,
)
from src.llm_client import call_mistral_simple
from src.telemetry import track_llm_request, get_dashboard_stats, get_user_stats, aggregate_metrics
from src.auth import (
    # Types
    Admin,
    EndUser,
    AuthContext,
    UserType,
    # Admin auth
    get_current_admin,
    super_admin_required,
    authenticate_admin,
    create_admin_session,
    create_admin,
    list_admins,
    update_admin,
    delete_admin,
    # End user auth
    get_current_end_user,
    authenticate_end_user,
    create_user_session,
    create_end_user,
    get_end_user,
    list_end_users,
    update_end_user,
    delete_end_user,
    # Unified auth
    get_auth_context,
    # Utilities
    audit_log_from_request,
    # Constants
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_MAX_AGE,
    USER_SESSION_COOKIE,
    USER_SESSION_MAX_AGE,
    # Backwards compat
    authenticate,
    create_session_token,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
)
from db.db import get_conn, put_conn

logger = logging.getLogger(__name__)

app = FastAPI(
    title="PromptDev API",
    description="Multi-tenant prompt engineering workbench",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════
# STATIC PAGES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/dashboard.html")


@app.get("/login")
async def login_page():
    return FileResponse("static/login.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory="static"), name="static")


# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """User chat request."""
    user_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    template_name: Optional[str] = None
    guardrail_config: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response."""
    response: str
    metadata: dict[str, Any]


class LoginRequest(BaseModel):
    email: str
    password: str


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    content: str = Field(min_length=1)


class TemplateUpdate(BaseModel):
    content: str = Field(min_length=1)
    change_description: Optional[str] = None


class MemoryUpdate(BaseModel):
    """Update memory request."""
    value: dict[str, Any]


class HaltRequest(BaseModel):
    reason: str


class InjectRequest(BaseModel):
    content: str


class GuardrailCreate(BaseModel):
    name: str
    rules: list
    description: Optional[str] = None


class GuardrailUpdate(BaseModel):
    """Update guardrail config request."""
    rules: Optional[list[dict[str, Any]]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AdminCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)


# ═══════════════════════════════════════════════════════════════════════════
# INTERVENTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def halt_conversation(user_id: str, operator: str, reason: str, tenant_id: Optional[int] = None) -> None:
    """Halt a user's conversation."""
    set_user_state(user_id, "halted", tenant_id=tenant_id)
    set_memory(user_id, "__halt_metadata", {
        "operator": operator,
        "reason": reason,
        "halted_at": datetime.now(UTC).isoformat()
    }, tenant_id=tenant_id)
    logger.info(f"Conversation halted for user {user_id} by {operator}: {reason}")


def resume_conversation(user_id: str, operator: str, tenant_id: Optional[int] = None) -> None:
    """Resume a halted conversation."""
    set_user_state(user_id, "active", tenant_id=tenant_id)
    delete_memory(user_id, "__halt_metadata", tenant_id=tenant_id)
    logger.info(f"Conversation resumed for user {user_id} by {operator}")


def is_conversation_halted(user_id: str, tenant_id: Optional[int] = None) -> bool:
    """Check if a conversation is halted."""
    state = get_user_state(user_id, tenant_id=tenant_id)
    return state is not None and state.mode == "halted"


def get_halted_users() -> list[dict[str, Any]]:
    """Get all users with halted conversations."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, mode, updated_at 
                FROM user_state 
                WHERE mode = 'halted'
                ORDER BY updated_at DESC
            """)
            results = []
            for row in cur.fetchall():
                user_id = row[0]
                halt_meta = get_memory(user_id, "__halt_metadata") or {}
                results.append({
                    "user_id": user_id,
                    "halted_at": row[2].isoformat(),
                    "operator": halt_meta.get("operator"),
                    "reason": halt_meta.get("reason")
                })
            return results
    finally:
        put_conn(conn)


def inject_message_helper(user_id: str, content: str, operator: str) -> int:
    """Inject an operator message into conversation history."""
    msg_id = add_message(user_id, "assistant", f"[Operator: {operator}] {content}")
    logger.info(f"Message injected for user {user_id} by {operator}")
    return msg_id


def get_default_template_name() -> str:
    """Get the default/active template name."""
    templates = list_templates()
    if not templates:
        raise HTTPException(status_code=500, detail="No templates available")
    return sorted(templates, key=lambda t: t.name)[0].name


# ═══════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/admin/login")
async def admin_login(request: LoginRequest, response: Response, req: Request):
    """Authenticate admin and set session cookie."""
    admin = authenticate(request.email, request.password)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_session_token(admin.id, admin.email, admin.is_super)
    
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    
    audit_log_from_request(admin, req, "login")
    
    return {"status": "ok", "email": admin.email, "is_super": admin.is_super}


@app.post("/admin/logout")
async def admin_logout(response: Response, req: Request, admin: Admin = Depends(get_current_admin)):
    """Clear session cookie."""
    audit_log_from_request(admin, req, "logout")
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@app.get("/admin/me")
async def get_current_admin_info(admin: Admin = Depends(get_current_admin)):
    """Get current admin info."""
    return {
        "id": admin.id,
        "email": admin.email,
        "tenant_id": admin.tenant_id,
        "is_super": admin.is_super
    }


# ═══════════════════════════════════════════════════════════════════════════
# SUPER ADMIN: MANAGE ADMINS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/super/admins")
async def list_all_admins(admin: Admin = Depends(super_admin_required)):
    """List all admins (super admin only)."""
    return {"admins": list_admins()}


@app.post("/super/admins")
async def create_new_admin(
    request: AdminCreate,
    req: Request,
    admin: Admin = Depends(super_admin_required)
):
    """Create new admin (super admin only)."""
    try:
        admin_id = create_admin(request.email, request.password)
        audit_log_from_request(admin, req, "admin_create", "admin", str(admin_id))
        return {"id": admin_id, "email": request.email}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/super/admins/{admin_id}")
async def update_admin_endpoint(
    admin_id: int,
    is_active: Optional[bool] = None,
    password: Optional[str] = None,
    req: Request = None,
    admin: Admin = Depends(super_admin_required)
):
    """Update admin (super admin only)."""
    if not update_admin(admin_id, is_active=is_active, password=password):
        raise HTTPException(status_code=404, detail="Admin not found")
    audit_log_from_request(admin, req, "admin_update", "admin", str(admin_id))
    return {"status": "updated"}


@app.delete("/super/admins/{admin_id}")
async def delete_admin_endpoint(
    admin_id: int,
    req: Request,
    admin: Admin = Depends(super_admin_required)
):
    """Delete admin (super admin only)."""
    if not delete_admin(admin_id):
        raise HTTPException(status_code=404, detail="Admin not found")
    audit_log_from_request(admin, req, "admin_delete", "admin", str(admin_id))
    return {"status": "deleted"}


# ═══════════════════════════════════════════════════════════════════════════
# CHAT ENDPOINTS (Authenticated - admin or end user)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth: AuthContext = Depends(get_auth_context)):
    """
    Send a chat message.
    
    Accepts admin or end user authentication.
    All data isolated by tenant_id.
    
    For end users, user_id in request is ignored - uses authenticated user's external_id.
    """
    tenant_id = auth.tenant_id
    
    # For end users, override user_id with their external_id
    if auth.is_end_user:
        user_id = auth.user_id
    else:
        user_id = request.user_id
    
    # Check if halted
    if is_conversation_halted(user_id, tenant_id=tenant_id):
        halt_meta = get_memory(user_id, "__halt_metadata", tenant_id=tenant_id) or {}
        raise HTTPException(
            status_code=423,
            detail=f"Conversation halted by {halt_meta.get('operator', 'unknown')}: "
                   f"{halt_meta.get('reason', 'No reason provided')}"
        )
    
    # Determine template
    template_name = request.template_name
    if not template_name:
        template_name = get_default_template_name()
    
    # Check template exists
    try:
        template = get_template_by_name(template_name, tenant_id=tenant_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
    
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Build prompt with context
    try:
        prompt = build_prompt_context_simple(
            user_id,
            template_name,
            request.message,
            guardrail_config=request.guardrail_config,
            tenant_id=tenant_id
        )
    except Exception as e:
        logger.error(f"Failed to build context: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to build context: {e}")
    
    # Call LLM with timing and telemetry
    start_time = time.time()
    error = None
    llm_response = ""
    
    try:
        llm_response = await call_mistral_simple(prompt=prompt)
    except Exception as e:
        error = str(e)
        logger.error(f"LLM call failed: {e}")
        response_time_ms = int((time.time() - start_time) * 1000)
        track_llm_request(
            user_id=user_id,
            template_name=template_name,
            response_time_ms=response_time_ms,
            error=error,
            tenant_id=tenant_id
        )
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")
    
    response_time_ms = int((time.time() - start_time) * 1000)
    track_llm_request(
        user_id=user_id,
        template_name=template_name,
        response_time_ms=response_time_ms,
        error=None,
        tenant_id=tenant_id
    )
    
    # Store messages
    add_message(user_id, "user", request.message, tenant_id=tenant_id)
    add_message(user_id, "assistant", llm_response, tenant_id=tenant_id)
    
    return ChatResponse(
        response=llm_response,
        metadata={
            "template_used": template_name,
            "message_count": count_messages(user_id, tenant_id=tenant_id),
            "response_time_ms": response_time_ms
        }
    )


@app.get("/chat/history")
async def get_chat_history(
    user_id: Optional[str] = Query(None, min_length=1),
    limit: Optional[int] = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context)
):
    """
    Get chat history.
    
    For end users: returns their own history (user_id param ignored).
    For admins: returns history for specified user_id.
    """
    tenant_id = auth.tenant_id
    
    if auth.is_end_user:
        effective_user_id = auth.user_id
    else:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required for admin")
        effective_user_id = user_id
    
    messages = get_conversation_history(effective_user_id, limit=limit, offset=offset, tenant_id=tenant_id)
    return {
        "user_id": effective_user_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ],
        "total_count": count_messages(effective_user_id, tenant_id=tenant_id)
    }


@app.delete("/chat/history/{user_id}")
async def clear_chat_history(user_id: str, admin: Admin = Depends(get_current_admin)):
    """Clear chat history for a user. Admin only."""
    tenant_id = admin.tenant_id
    deleted = clear_conversation_history(user_id, tenant_id=tenant_id)
    return {
        "user_id": user_id,
        "deleted_count": deleted
    }


# ═══════════════════════════════════════════════════════════════════════════
# END USER AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

class EndUserLoginRequest(BaseModel):
    """End user login request."""
    email: str
    password: str
    tenant_id: int  # Which tenant to login to


class EndUserRegisterRequest(BaseModel):
    """End user registration request."""
    external_id: str = Field(..., min_length=1)
    email: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    display_name: Optional[str] = None


class EndUserUpdateRequest(BaseModel):
    """End user update request."""
    email: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    display_name: Optional[str] = None
    is_active: Optional[bool] = None


@app.post("/user/login")
async def end_user_login(request: EndUserLoginRequest, response: Response):
    """End user login."""
    user = authenticate_end_user(request.tenant_id, request.email, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_user_session(user)
    response.set_cookie(
        key=USER_SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=False,  # Set True in production with HTTPS
        samesite="lax",
        max_age=USER_SESSION_MAX_AGE,
        path="/",
    )
    
    return {
        "status": "ok",
        "user": {
            "id": user.id,
            "external_id": user.external_id,
            "email": user.email,
            "display_name": user.display_name
        }
    }


@app.post("/user/logout")
async def end_user_logout(response: Response, user: EndUser = Depends(get_current_end_user)):
    """End user logout."""
    response.delete_cookie(key=USER_SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/user/me")
async def get_current_user_info(user: EndUser = Depends(get_current_end_user)):
    """Get current end user info."""
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "external_id": user.external_id,
        "email": user.email,
        "display_name": user.display_name
    }


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: END USER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/end-users")
async def list_tenant_end_users(
    admin: Admin = Depends(get_current_admin),
    include_inactive: bool = Query(False)
):
    """List all end users for this tenant."""
    users = list_end_users(admin.tenant_id, include_inactive=include_inactive)
    return {"count": len(users), "users": users}


@app.post("/admin/end-users")
async def create_tenant_end_user(
    request: EndUserRegisterRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Create a new end user for this tenant."""
    try:
        user = create_end_user(
            tenant_id=admin.tenant_id,
            external_id=request.external_id,
            email=request.email,
            password=request.password,
            display_name=request.display_name
        )
        audit_log_from_request(admin, req, "end_user_create", "end_user", str(user.id))
        return {
            "id": user.id,
            "external_id": user.external_id,
            "email": user.email
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/admin/end-users/{user_id}")
async def get_tenant_end_user(
    user_id: int,
    admin: Admin = Depends(get_current_admin)
):
    """Get end user details."""
    from src.auth import get_end_user_by_id
    user = get_end_user_by_id(user_id)
    if not user or user.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "external_id": user.external_id,
        "email": user.email,
        "display_name": user.display_name
    }


@app.put("/admin/end-users/{user_id}")
async def update_tenant_end_user(
    user_id: int,
    request: EndUserUpdateRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Update end user."""
    from src.auth import get_end_user_by_id
    user = get_end_user_by_id(user_id)
    if not user or user.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not update_end_user(
        user_id,
        email=request.email,
        password=request.password,
        display_name=request.display_name,
        is_active=request.is_active
    ):
        raise HTTPException(status_code=404, detail="User not found")
    
    audit_log_from_request(admin, req, "end_user_update", "end_user", str(user_id))
    return {"status": "updated"}


@app.delete("/admin/end-users/{user_id}")
async def delete_tenant_end_user(
    user_id: int,
    req: Request,
    hard: bool = Query(False),
    admin: Admin = Depends(get_current_admin)
):
    """Delete end user."""
    from src.auth import get_end_user_by_id
    user = get_end_user_by_id(user_id)
    if not user or user.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not delete_end_user(user_id, hard=hard):
        raise HTTPException(status_code=404, detail="User not found")
    
    audit_log_from_request(admin, req, "end_user_delete", "end_user", str(user_id))
    return {"status": "deleted" if hard else "deactivated"}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: TEMPLATE ENDPOINTS (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/templates")
async def list_all_templates(
    admin: Admin = Depends(get_current_admin),
    include_inactive: bool = Query(False)
):
    """List all templates for this tenant."""
    templates = list_templates(include_inactive=include_inactive, tenant_id=admin.tenant_id)
    return {
        "count": len(templates),
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "version": t.current_version,
                "is_active": t.is_active,
                "is_shareable": getattr(t, 'is_shareable', False),
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat()
            }
            for t in templates
        ]
    }


@app.post("/admin/templates")
async def create_new_template(
    request: TemplateCreate,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Create a new template."""
    try:
        template_id = create_template(
            request.name,
            request.content,
            created_by=admin.email,
            tenant_id=admin.tenant_id
        )
        audit_log_from_request(admin, req, "template_create", "template", str(template_id))
        return {"id": template_id, "name": request.name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/admin/templates/{name}")
async def get_template_by_name_endpoint(
    name: str,
    admin: Admin = Depends(get_current_admin)
):
    """Get a template by name."""
    try:
        template = get_template_by_name(name, tenant_id=admin.tenant_id)
        return {
            "id": template.id,
            "name": template.name,
            "content": template.content,
            "version": template.current_version,
            "is_shareable": getattr(template, 'is_shareable', False),
            "cloned_from_id": getattr(template, 'cloned_from_id', None),
            "created_at": template.created_at.isoformat(),
            "updated_at": template.updated_at.isoformat()
        }
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")


@app.put("/admin/templates/{template_id}")
async def update_template_endpoint(
    template_id: int,
    request: TemplateUpdate,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Update a template (creates new version)."""
    try:
        new_version = update_template(
            template_id,
            request.content,
            created_by=admin.email,
            change_description=request.change_description,
            tenant_id=admin.tenant_id
        )
        audit_log_from_request(admin, req, "template_update", "template", str(template_id))
        return {"template_id": template_id, "new_version": new_version}
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")


@app.delete("/admin/templates/{template_id}")
async def delete_template_endpoint(
    template_id: int,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Delete a template (soft delete)."""
    if not delete_template(template_id, tenant_id=admin.tenant_id):
        raise HTTPException(status_code=404, detail="Template not found")
    audit_log_from_request(admin, req, "template_delete", "template", str(template_id))
    return {"status": "deleted"}


@app.get("/admin/templates/{template_id}/history")
async def get_template_history(
    template_id: int,
    admin: Admin = Depends(get_current_admin)
):
    """Get version history for a template."""
    try:
        versions = get_version_history(template_id, tenant_id=admin.tenant_id)
        return {
            "template_id": template_id,
            "versions": [
                {
                    "version": v.version,
                    "content": v.content,
                    "created_at": v.created_at.isoformat(),
                    "created_by": v.created_by,
                    "change_description": v.change_description
                }
                for v in versions
            ]
        }
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")


@app.post("/admin/templates/{template_id}/rollback/{version}")
async def rollback_template(
    template_id: int,
    version: int,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Rollback template to a previous version."""
    try:
        new_version = rollback_to_version(
            template_id, version,
            created_by=admin.email,
            tenant_id=admin.tenant_id
        )
        audit_log_from_request(
            admin, req, "template_rollback", "template", str(template_id),
            {"from_version": version, "to_version": new_version}
        )
        return {"new_version": new_version}
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template or version not found")


@app.post("/admin/templates/{template_id}/share")
async def share_template(
    template_id: int,
    is_shareable: bool,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Set whether a template is shareable."""
    if not set_template_shareable(template_id, is_shareable, tenant_id=admin.tenant_id):
        raise HTTPException(status_code=404, detail="Template not found")
    audit_log_from_request(
        admin, req, "template_share", "template", str(template_id),
        {"is_shareable": is_shareable}
    )
    return {"status": "updated", "is_shareable": is_shareable}


@app.post("/admin/templates/{template_id}/activate")
async def activate_template_endpoint(
    template_id: int,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Activate a template."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE system_prompt SET is_active = true, updated_at = NOW() WHERE id = %s",
                (template_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Template not found")
            conn.commit()
        audit_log_from_request(admin, req, "template_activate", "template", str(template_id))
        return {"message": "Template activated"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        put_conn(conn)


@app.post("/admin/templates/{template_id}/deactivate")
async def deactivate_template_endpoint(
    template_id: int,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Deactivate a template."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE system_prompt SET is_active = false, updated_at = NOW() WHERE id = %s",
                (template_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Template not found")
            conn.commit()
        audit_log_from_request(admin, req, "template_deactivate", "template", str(template_id))
        return {"message": "Template deactivated"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# SHARED TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/shared/templates")
async def list_shared_templates_endpoint(admin: Admin = Depends(get_current_admin)):
    """List all shareable templates from any tenant."""
    templates = list_shared_templates()
    return {
        "count": len(templates),
        "templates": [
            {
                "id": t.id,
                "tenant_id": t.tenant_id,
                "name": t.name,
                "version": t.current_version,
                "created_at": t.created_at.isoformat()
            }
            for t in templates
        ]
    }


@app.post("/admin/shared/templates/{template_id}/clone")
async def clone_shared_template(
    template_id: int,
    new_name: Optional[str] = None,
    req: Request = None,
    admin: Admin = Depends(get_current_admin)
):
    """Clone a shared template into your space."""
    try:
        new_id = clone_template(template_id, admin.tenant_id, new_name)
        audit_log_from_request(
            admin, req, "template_clone", "template", str(new_id),
            {"source_template_id": template_id}
        )
        return {"id": new_id}
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    except PromptError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: USER MONITORING (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/users")
async def admin_list_users(admin: Admin = Depends(get_current_admin)):
    """List all users with conversation activity."""
    users = list_users(tenant_id=admin.tenant_id)
    return {"count": len(users), "users": users}


@app.get("/admin/conversations/{user_id}")
async def get_conversation(
    user_id: str,
    limit: int = Query(100, ge=1, le=1000),
    admin: Admin = Depends(get_current_admin)
):
    """Get conversation for a user (used by monitor.html)."""
    messages = get_conversation_history(user_id, limit=limit, tenant_id=admin.tenant_id)
    state = get_user_state(user_id, tenant_id=admin.tenant_id)
    return {
        "user_id": user_id,
        "message_count": count_messages(user_id, tenant_id=admin.tenant_id),
        "state": state.mode if state else "active",
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat()
            }
            for m in messages
        ]
    }


@app.get("/admin/conversations/{user_id}/export")
async def export_conversation(
    user_id: str,
    format: str = Query("json"),
    admin: Admin = Depends(get_current_admin)
):
    """Export conversation for a user."""
    messages = get_conversation_history(user_id, limit=10000, tenant_id=admin.tenant_id)
    data = {
        "user_id": user_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "message_count": len(messages),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat()
            }
            for m in messages
        ]
    }
    return data


@app.post("/admin/interventions/{user_id}/halt")
async def intervention_halt(
    user_id: str,
    request: HaltRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Halt a user's conversation (used by monitor.html)."""
    halt_user(user_id, request.reason, admin.email, tenant_id=admin.tenant_id)
    audit_log_from_request(admin, req, "user_halt", "user", user_id, {"reason": request.reason})
    return {"status": "halted", "user_id": user_id}


@app.post("/admin/interventions/{user_id}/resume")
async def intervention_resume(
    user_id: str,
    operator: str = Query(...),
    req: Request = None,
    admin: Admin = Depends(get_current_admin)
):
    """Resume a halted user's conversation (used by monitor.html)."""
    resume_user(user_id, tenant_id=admin.tenant_id)
    audit_log_from_request(admin, req, "user_resume", "user", user_id)
    return {"status": "resumed", "user_id": user_id}


@app.post("/admin/interventions/{user_id}/inject")
async def intervention_inject(
    user_id: str,
    request: InjectRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Inject a message into a user's conversation (used by monitor.html)."""
    add_message(user_id, "assistant", request.message, tenant_id=admin.tenant_id)
    audit_log_from_request(admin, req, "user_inject", "user", user_id, {"message": request.message[:100]})
    return {"status": "injected", "user_id": user_id}


@app.get("/admin/users/{user_id}/conversations")
async def get_user_conversations(
    user_id: str,
    limit: int = Query(100, ge=1, le=1000),
    admin: Admin = Depends(get_current_admin)
):
    """Get conversation history for a user."""
    messages = get_conversation_history(user_id, limit=limit, tenant_id=admin.tenant_id)
    return {
        "user_id": user_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat()
            }
            for m in messages
        ],
        "total_count": count_messages(user_id, tenant_id=admin.tenant_id)
    }


@app.delete("/admin/users/{user_id}/conversations")
async def clear_user_conversations(
    user_id: str,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Clear conversation history for a user."""
    deleted = clear_conversation_history(user_id, tenant_id=admin.tenant_id)
    audit_log_from_request(admin, req, "user_clear_history", "user", user_id)
    return {"deleted": deleted}


@app.get("/admin/users/{user_id}/memory")
async def get_user_memory_endpoint(
    user_id: str,
    admin: Admin = Depends(get_current_admin)
):
    """Get all memory for a user."""
    memory = get_all_memory(user_id, tenant_id=admin.tenant_id)
    return {"user_id": user_id, "memory": memory}


@app.put("/admin/users/{user_id}/memory/{key}")
async def set_user_memory_endpoint(
    user_id: str,
    key: str,
    request: MemoryUpdate,
    admin: Admin = Depends(get_current_admin)
):
    """Set a memory value for a user."""
    mem_id = set_memory(user_id, key, request.value, tenant_id=admin.tenant_id)
    return {"user_id": user_id, "key": key, "memory_id": mem_id}


@app.get("/admin/users/{user_id}/state")
async def get_user_state_endpoint(
    user_id: str,
    admin: Admin = Depends(get_current_admin)
):
    """Get user state."""
    state = get_user_state(user_id, tenant_id=admin.tenant_id)
    if not state:
        return {"user_id": user_id, "state": None}
    return {
        "user_id": user_id,
        "state": {
            "mode": state.mode,
            "is_halted": getattr(state, 'is_halted', state.mode == 'halted'),
            "halt_reason": getattr(state, 'halt_reason', None),
            "halted_by": getattr(state, 'halted_by', None),
            "halted_at": getattr(state, 'halted_at', state.updated_at).isoformat() if hasattr(state, 'halted_at') and state.halted_at else None,
            "personality_id": getattr(state, 'personality_id', None)
        }
    }


@app.put("/admin/users/{user_id}/state")
async def set_state(
    user_id: str,
    mode: str = Query(..., min_length=1),
    admin: Admin = Depends(get_current_admin)
):
    """Set user state."""
    set_user_state(user_id, mode, tenant_id=admin.tenant_id)
    return {"user_id": user_id, "mode": mode}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: INTERVENTIONS (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/admin/users/{user_id}/halt")
async def halt_user_endpoint(
    user_id: str,
    request: HaltRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Halt a user's conversation."""
    halt_conversation(user_id, admin.email, request.reason, tenant_id=admin.tenant_id)
    audit_log_from_request(
        admin, req, "user_halt", "user", user_id,
        {"reason": request.reason}
    )
    return {"status": "halted", "user_id": user_id}


@app.post("/admin/users/{user_id}/resume")
async def resume_user_endpoint(
    user_id: str,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Resume a halted user's conversation."""
    if not is_conversation_halted(user_id, tenant_id=admin.tenant_id):
        raise HTTPException(status_code=400, detail="Conversation is not halted")
    resume_conversation(user_id, admin.email, tenant_id=admin.tenant_id)
    audit_log_from_request(admin, req, "user_resume", "user", user_id)
    return {"status": "resumed", "user_id": user_id}


@app.post("/admin/users/{user_id}/inject")
async def inject_message(
    user_id: str,
    request: InjectRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Inject a message into user's conversation."""
    msg_id = inject_message_helper(user_id, request.content, admin.email)
    audit_log_from_request(admin, req, "user_inject", "user", user_id)
    return {"message_id": msg_id}


@app.get("/admin/halted")
async def list_halted_users_endpoint(admin: Admin = Depends(get_current_admin)):
    """List all halted users."""
    halted = get_halted_users()
    return {
        "count": len(halted),
        "halted_users": halted
    }


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: GUARDRAILS (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/guardrails")
async def list_guardrails_endpoint(
    admin: Admin = Depends(get_current_admin),
    include_inactive: bool = Query(False)
):
    """List all guardrail configs (tenant + system presets)."""
    configs = list_guardrails(tenant_id=admin.tenant_id, include_inactive=include_inactive)
    return {
        "count": len(configs),
        "configs": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "rule_count": len(c.rules),
                "is_system": c.tenant_id is None,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat(),
                "created_by": c.created_by
            }
            for c in configs
        ]
    }


@app.post("/admin/guardrails")
async def create_guardrail_endpoint(
    request: GuardrailCreate,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Create a new guardrail config."""
    try:
        config_id = create_guardrail(
            request.name, request.rules,
            request.description, admin.email,
            tenant_id=admin.tenant_id
        )
        audit_log_from_request(admin, req, "guardrail_create", "guardrail", str(config_id))
        return {"id": config_id, "name": request.name}
    except InvalidRulesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create config: {e}")


@app.get("/admin/guardrails/presets")
async def get_preset_names_endpoint(admin: Admin = Depends(get_current_admin)):
    """Get names of system preset guardrails."""
    return {"presets": get_preset_names()}


@app.get("/admin/guardrails/{name}")
async def get_guardrail_endpoint(
    name: str,
    admin: Admin = Depends(get_current_admin)
):
    """Get a guardrail config by name."""
    try:
        config = get_guardrail(name, tenant_id=admin.tenant_id)
        return {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "rules": config.rules,
            "is_system": config.tenant_id is None or config.tenant_id == 0,
            "is_active": config.is_active,
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
            "created_by": config.created_by
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")


@app.get("/admin/guardrails/id/{config_id}")
async def get_guardrail_by_id_endpoint(
    config_id: int,
    admin: Admin = Depends(get_current_admin)
):
    """Get a guardrail config by ID."""
    try:
        config = get_config_by_id(config_id)
        return {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "rules": config.rules,
            "is_system": config.tenant_id is None or config.tenant_id == 0,
            "is_active": config.is_active,
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
            "created_by": config.created_by
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config ID {config_id} not found")


@app.put("/admin/guardrails/{config_id}")
async def update_guardrail_endpoint(
    config_id: int,
    request: GuardrailUpdate,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Update a guardrail configuration."""
    try:
        update_guardrail(
            config_id=config_id,
            rules=request.rules,
            description=request.description,
            is_active=request.is_active
        )
        audit_log_from_request(admin, req, "guardrail_update", "guardrail", str(config_id))
        return {"id": config_id, "message": "Config updated successfully"}
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config ID {config_id} not found")
    except InvalidRulesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {e}")


@app.delete("/admin/guardrails/{config_id}")
async def delete_guardrail_endpoint(
    config_id: int,
    hard: bool = Query(False),
    req: Request = None,
    admin: Admin = Depends(get_current_admin)
):
    """Delete a guardrail config (own configs only)."""
    try:
        delete_guardrail(config_id, soft=not hard, tenant_id=admin.tenant_id)
        audit_log_from_request(admin, req, "guardrail_delete", "guardrail", str(config_id))
        return {"status": "deleted" if hard else "deactivated"}
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail="Config not found or is system preset")


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: TELEMETRY & STATS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/stats/overview")
async def get_stats_overview(admin: Admin = Depends(get_current_admin)):
    """Get aggregated dashboard statistics."""
    try:
        stats = get_dashboard_stats()
        return {
            "active_users_today": stats.active_users_today,
            "active_users_hour": getattr(stats, 'active_users_hour', 0),
            "total_messages_today": stats.total_messages_today,
            "messages_per_hour": getattr(stats, 'messages_per_hour', 0),
            "avg_response_time_ms": stats.avg_response_time_ms,
            "error_rate_percent": stats.error_rate_percent,
            "top_templates": getattr(stats, 'top_templates', [])
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {
            "active_users_today": 0,
            "active_users_hour": 0,
            "total_messages_today": 0,
            "messages_per_hour": 0,
            "avg_response_time_ms": 0,
            "error_rate_percent": 0.0,
            "top_templates": []
        }


@app.get("/admin/stats/users/{user_id}")
async def get_user_statistics(
    user_id: str,
    admin: Admin = Depends(get_current_admin)
):
    """Get statistics for a specific user."""
    stats = get_user_stats(user_id)
    if not stats:
        raise HTTPException(status_code=404, detail=f"No statistics found for user {user_id}")
    return stats


@app.post("/admin/stats/aggregate")
async def trigger_aggregation(admin: Admin = Depends(get_current_admin)):
    """Manually trigger metric aggregation."""
    try:
        aggregate_metrics()
        return {"status": "success", "message": "Metrics aggregated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Aggregation failed: {e}")
