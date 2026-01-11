"""
FastAPI application for PromptDev - Multi-tenant prompt engineering workbench.

Architecture:
- Each admin (tenant) has isolated templates, users, guardrails
- tenant_id flows from authenticated session to all DB operations
- Super admin can manage other admins
"""

import logging
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, Query, Depends, Response, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from pydantic import BaseModel, Field

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
    count_messages,
    clear_conversation_history,
    list_users,
    set_memory,
    get_memory,
    get_all_memory,
    delete_memory,
    get_user_state,
    halt_user,
    resume_user,
    is_user_halted,
    list_halted_users,
)
from src.guardrails import (
    create_config as create_guardrail,
    get_config as get_guardrail,
    list_configs as list_guardrails,
    update_config as update_guardrail,
    delete_config as delete_guardrail,
    get_preset_names,
    GuardrailNotFoundError,
)
from src.auth import (
    Admin,
    get_current_admin,
    super_admin_required,
    authenticate,
    create_session_token,
    create_admin,
    list_admins,
    update_admin,
    delete_admin,
    audit_log_from_request,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
)

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
# AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: str
    password: str


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
    )
    
    audit_log_from_request(admin, req, "login")
    
    return {"status": "ok", "email": admin.email, "is_super": admin.is_super}


@app.post("/admin/logout")
async def admin_logout(response: Response, req: Request, admin: Admin = Depends(get_current_admin)):
    """Clear session cookie."""
    audit_log_from_request(admin, req, "logout")
    response.delete_cookie(key=SESSION_COOKIE_NAME)
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

class AdminCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)


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
# TEMPLATES (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

class TemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    content: str = Field(min_length=1)


class TemplateUpdate(BaseModel):
    content: str = Field(min_length=1)
    change_description: Optional[str] = None


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
                "is_shareable": t.is_shareable,
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
            "is_shareable": template.is_shareable,
            "cloned_from_id": template.cloned_from_id,
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
# USERS (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/admin/users")
async def list_all_users(admin: Admin = Depends(get_current_admin)):
    """List all users with conversation activity."""
    users = list_users(tenant_id=admin.tenant_id)
    return {"count": len(users), "users": users}


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
            "is_halted": state.is_halted,
            "halt_reason": state.halt_reason,
            "halted_by": state.halted_by,
            "halted_at": state.halted_at.isoformat() if state.halted_at else None,
            "personality_id": state.personality_id
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# INTERVENTIONS (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

class HaltRequest(BaseModel):
    reason: str


@app.post("/admin/users/{user_id}/halt")
async def halt_user_endpoint(
    user_id: str,
    request: HaltRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Halt a user's conversation."""
    halt_user(user_id, request.reason, admin.email, tenant_id=admin.tenant_id)
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
    resume_user(user_id, tenant_id=admin.tenant_id)
    audit_log_from_request(admin, req, "user_resume", "user", user_id)
    return {"status": "resumed", "user_id": user_id}


class InjectRequest(BaseModel):
    content: str


@app.post("/admin/users/{user_id}/inject")
async def inject_message(
    user_id: str,
    request: InjectRequest,
    req: Request,
    admin: Admin = Depends(get_current_admin)
):
    """Inject a message into user's conversation."""
    msg_id = add_message(
        user_id, "assistant",
        f"[Operator: {admin.email}] {request.content}",
        tenant_id=admin.tenant_id
    )
    audit_log_from_request(admin, req, "user_inject", "user", user_id)
    return {"message_id": msg_id}


@app.get("/admin/halted")
async def list_halted_users_endpoint(admin: Admin = Depends(get_current_admin)):
    """List all halted users."""
    users = list_halted_users(tenant_id=admin.tenant_id)
    return {
        "count": len(users),
        "halted_users": users
    }


# ═══════════════════════════════════════════════════════════════════════════
# GUARDRAILS (TENANT ISOLATED)
# ═══════════════════════════════════════════════════════════════════════════

class GuardrailCreate(BaseModel):
    name: str
    rules: list
    description: Optional[str] = None


@app.get("/admin/guardrails")
async def list_guardrails_endpoint(admin: Admin = Depends(get_current_admin)):
    """List all guardrail configs (tenant + system presets)."""
    configs = list_guardrails(tenant_id=admin.tenant_id)
    return {
        "count": len(configs),
        "configs": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "is_system": c.tenant_id is None,
                "is_active": c.is_active
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
            "is_system": config.tenant_id == 0,
            "is_active": config.is_active
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")


@app.delete("/admin/guardrails/{config_id}")
async def delete_guardrail_endpoint(
    config_id: int,
    hard: bool = False,
    req: Request = None,
    admin: Admin = Depends(get_current_admin)
):
    """Delete a guardrail config (own configs only)."""
    try:
        delete_guardrail(config_id, soft=not hard, tenant_id=admin.tenant_id)
        audit_log_from_request(admin, req, "guardrail_delete", "guardrail", str(config_id))
        return {"status": "deleted"}
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail="Config not found or is system preset")
