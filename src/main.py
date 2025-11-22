"""
FastAPI application for PromptDev - Prompt engineering workbench.

This module provides:
- User endpoints: Chat, history management
- Admin endpoints: Template management, monitoring, interventions
- Guardrails: Preset configurations and custom restrictions
- Interventions: Halt, resume, inject capabilities

Architecture:
- Users chat via /chat endpoint (templates applied transparently)
- Operators manage templates, view conversations, intervene when needed
- All user data (conversation_history, user_memory, user_state) isolated by user_id
- Templates and versions managed globally by operators
"""

import logging
import time
from typing import Optional, Any
from datetime import datetime, UTC
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
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
    TemplateNotFoundError,
)
from src.memory import (
    add_message,
    get_conversation_history,
    get_recent_messages,
    count_messages,
    clear_conversation_history,
    set_memory,
    get_memory,
    get_all_memory,
    delete_memory,
    get_user_state,
    set_user_state,
    delete_user_state,
    UserState,
)
from src.context import (
    build_prompt_context,
    build_prompt_context_simple,
    get_context_summary,
)
from src.guardrails import (
    create_config,
    get_config,
    get_config_by_id,
    list_configs,
    update_config,
    delete_config,
    apply_guardrails,
    get_preset_names,
    GuardrailNotFoundError,
    InvalidRulesError,
)
from src.llm_client import call_mistral_simple
from src.telemetry import track_llm_request, get_dashboard_stats, get_user_stats, aggregate_metrics
from db.db import get_conn, put_conn

logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="PromptDev API",
    description="Prompt engineering workbench with template versioning",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for dashboard UI
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to operator dashboard."""
    return RedirectResponse(url="/static/dashboard.html")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MODELS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class ChatRequest(BaseModel):
    """User chat request."""
    user_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    template_name: Optional[str] = None  # If None, use default active template
    guardrail_config: Optional[str] = None  # Optional guardrail config to apply


class ChatResponse(BaseModel):
    """Chat response."""
    response: str
    metadata: dict[str, Any]


class TemplateCreate(BaseModel):
    """Create template request."""
    name: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    created_by: str = Field(..., min_length=1)


class TemplateUpdate(BaseModel):
    """Update template request."""
    content: str = Field(..., min_length=1)
    updated_by: str = Field(..., min_length=1)
    change_description: Optional[str] = None


class MemoryUpdate(BaseModel):
    """Update memory request."""
    value: dict[str, Any]


class HaltRequest(BaseModel):
    """Halt conversation request."""
    operator: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class InjectRequest(BaseModel):
    """Inject message request."""
    content: str = Field(..., min_length=1)
    operator: str = Field(..., min_length=1)


class GuardrailCreate(BaseModel):
    """Create guardrail config request."""
    name: str = Field(..., min_length=1)
    rules: list[dict[str, Any]]
    description: Optional[str] = None
    created_by: Optional[str] = None


class GuardrailUpdate(BaseModel):
    """Update guardrail config request."""
    rules: Optional[list[dict[str, Any]]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# INTERVENTION HELPERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def halt_conversation(user_id: str, operator: str, reason: str) -> None:
    """
    Halt a user's conversation.
    
    Sets user_state to 'halted' with metadata about who halted it and why.
    """
    set_user_state(user_id, "halted")
    set_memory(user_id, "__halt_metadata", {
        "operator": operator,
        "reason": reason,
        "halted_at": datetime.now(UTC).isoformat()
    })
    logger.info(f"Conversation halted for user {user_id} by {operator}: {reason}")


def resume_conversation(user_id: str, operator: str) -> None:
    """
    Resume a halted conversation.
    
    Sets user_state back to 'active' and clears halt metadata.
    """
    set_user_state(user_id, "active")
    delete_memory(user_id, "__halt_metadata")
    logger.info(f"Conversation resumed for user {user_id} by {operator}")


def is_conversation_halted(user_id: str) -> bool:
    """Check if a conversation is halted."""
    state = get_user_state(user_id)
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


def inject_message(user_id: str, content: str, operator: str) -> int:
    """
    Inject an operator message into conversation history.
    
    Returns the message ID.
    """
    msg_id = add_message(user_id, "assistant", f"[Operator: {operator}] {content}")
    logger.info(f"Message injected for user {user_id} by {operator}")
    return msg_id


def get_default_template_name() -> str:
    """
    Get the default/active template name.
    
    For now, returns the first template alphabetically.
    In production, this would query for is_active flag.
    """
    templates = list_templates()
    if not templates:
        raise HTTPException(status_code=500, detail="No templates available")
    # Return first template (sorted by name)
    return sorted(templates, key=lambda t: t.name)[0].name


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SYSTEM ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# USER ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a chat message.
    
    User sends a message, system:
    1. Checks if conversation is halted
    2. Loads appropriate template (user-specified or default)
    3. Builds prompt with user context (history, memory, state)
    4. Calls LLM
    5. Stores user message and LLM response
    6. Returns response
    """
    # Check if halted
    if is_conversation_halted(request.user_id):
        halt_meta = get_memory(request.user_id, "__halt_metadata") or {}
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
        template = get_template_by_name(template_name)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
    
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Build prompt with context
    try:
        prompt = build_prompt_context_simple(
            request.user_id,
            template_name,
            request.message,
            guardrail_config=request.guardrail_config
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
        # Track failed request
        response_time_ms = int((time.time() - start_time) * 1000)
        track_llm_request(
            user_id=request.user_id,
            template_name=template_name,
            response_time_ms=response_time_ms,
            error=error
        )
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")
    
    # Calculate timing and track successful request
    response_time_ms = int((time.time() - start_time) * 1000)
    track_llm_request(
        user_id=request.user_id,
        template_name=template_name,
        response_time_ms=response_time_ms,
        error=None
    )
    
    # Store messages
    add_message(request.user_id, "user", request.message)
    add_message(request.user_id, "assistant", llm_response)
    
    return ChatResponse(
        response=llm_response,
        metadata={
            "template_used": template_name,
            "message_count": count_messages(request.user_id),
            "response_time_ms": response_time_ms
        }
    )


@app.get("/chat/history")
async def get_history(
    user_id: str = Query(..., min_length=1),
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0)
):
    """Get chat history for a user."""
    messages = get_conversation_history(user_id, limit=limit, offset=offset)
    return {
        "user_id": user_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ],
        "total_count": count_messages(user_id)
    }


@app.delete("/chat/history/{user_id}")
async def clear_history(user_id: str):
    """Clear chat history for a user."""
    deleted = clear_conversation_history(user_id)
    return {
        "user_id": user_id,
        "deleted_count": deleted
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN: TEMPLATE ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.get("/admin/templates")
async def list_all_templates():
    """List all templates."""
    templates = list_templates()
    return {
        "count": len(templates),
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "version": t.current_version,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat()
            }
            for t in templates
        ]
    }


@app.post("/admin/templates")
async def create_new_template(request: TemplateCreate):
    """Create a new template."""
    try:
        template_id = create_template(
            request.name,
            request.content,
            created_by=request.created_by
        )
        template = get_template(template_id)
        return {
            "id": template.id,
            "name": template.name,
            "version": template.current_version,
            "created_at": template.created_at.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/admin/templates/{name}")
async def get_template_by_name_endpoint(name: str):
    """Get a specific template by name."""
    try:
        template = get_template_by_name(name)
        return {
            "id": template.id,
            "name": template.name,
            "content": template.content,
            "version": template.current_version,
            "created_at": template.created_at.isoformat(),
            "updated_at": template.updated_at.isoformat()
        }
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")


@app.put("/admin/templates/{template_id}")
async def update_template_endpoint(template_id: int, request: TemplateUpdate):
    """Update a template (creates new version)."""
    try:
        new_version = update_template(
            template_id,
            request.content,
            created_by=request.updated_by,  # FIX: created_by not updated_by
            change_description=request.change_description
        )
        return {
            "template_id": template_id,
            "new_version": new_version,
            "updated_by": request.updated_by
        }
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/admin/templates/{template_id}/history")
async def get_template_history(template_id: int):
    """Get version history for a template."""
    try:
        versions = get_version_history(template_id)
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
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")


@app.post("/admin/templates/{template_id}/rollback/{version}")
async def rollback_template_endpoint(
    template_id: int,
    version: int,
    updated_by: str = Query(..., min_length=1)
):
    """Rollback template to a previous version."""
    try:
        new_version = rollback_to_version(
            template_id,
            version,
            created_by=updated_by  # FIX: created_by not updated_by
        )
        return {
            "template_id": template_id,
            "rolled_back_to": version,
            "new_version": new_version
        }
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template or version not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN: MONITORING ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.get("/admin/users")
async def list_users():
    """List all users with conversation activity."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT user_id, 
                    COUNT(*) as message_count,
                    MAX(created_at) as last_activity
                FROM conversation_history
                GROUP BY user_id
                ORDER BY last_activity DESC
            """)
            users = []
            for row in cur.fetchall():
                users.append({
                    "user_id": row[0],
                    "message_count": row[1],
                    "last_activity": row[2].isoformat()
                })
            return {
                "count": len(users),
                "users": users
            }
    finally:
        put_conn(conn)


@app.get("/admin/conversations/{user_id}")
async def get_user_conversation(user_id: str):
    """Get conversation history for any user (admin view)."""
    messages = get_conversation_history(user_id)
    state = get_user_state(user_id)
    
    return {
        "user_id": user_id,
        "state": state.mode if state else None,
        "message_count": len(messages),
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    }


@app.get("/admin/conversations/export")
async def export_conversation(user_id: str = Query(...)):
    """Export conversation as JSON download."""
    messages = get_conversation_history(user_id)
    state = get_user_state(user_id)
    all_memory = get_all_memory(user_id)
    
    export_data = {
        "user_id": user_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "state": state.mode if state else None,
        "memory": all_memory,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    }
    
    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f"attachment; filename=conversation_{user_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
        }
    )


@app.get("/admin/memory/{user_id}")
async def get_user_memory(user_id: str):
    """Get all memory for a user."""
    memories = get_all_memory(user_id)
    return {
        "user_id": user_id,
        "memory": {
            mem.key: mem.value
            for mem in memories
        }
    }


@app.put("/admin/memory/{user_id}/{key}")
async def set_user_memory(user_id: str, key: str, request: MemoryUpdate):
    """Set a memory value for a user."""
    mem_id = set_memory(user_id, key, request.value)
    return {
        "user_id": user_id,
        "key": key,
        "memory_id": mem_id
    }


@app.get("/admin/state/{user_id}")
async def get_state(user_id: str):
    """Get user state."""
    state = get_user_state(user_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"No state found for user {user_id}")
    
    return {
        "user_id": state.user_id,
        "mode": state.mode,
        "updated_at": state.updated_at.isoformat()
    }


@app.put("/admin/state/{user_id}")
async def set_state(user_id: str, mode: str = Query(..., min_length=1)):
    """Set user state."""
    set_user_state(user_id, mode)
    return {
        "user_id": user_id,
        "mode": mode
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN: INTERVENTION ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.post("/admin/interventions/{user_id}/halt")
async def halt_user_conversation(user_id: str, request: HaltRequest):
    """Halt a user's conversation."""
    halt_conversation(user_id, request.operator, request.reason)
    return {
        "user_id": user_id,
        "status": "halted",
        "operator": request.operator,
        "reason": request.reason
    }


@app.post("/admin/interventions/{user_id}/resume")
async def resume_user_conversation(
    user_id: str,
    operator: str = Query(..., min_length=1)
):
    """Resume a halted conversation."""
    if not is_conversation_halted(user_id):
        raise HTTPException(status_code=400, detail="Conversation is not halted")
    
    resume_conversation(user_id, operator)
    return {
        "user_id": user_id,
        "status": "active",
        "operator": operator
    }


@app.post("/admin/interventions/{user_id}/inject")
async def inject_operator_message(user_id: str, request: InjectRequest):
    """Inject an operator message into conversation."""
    msg_id = inject_message(user_id, request.content, request.operator)
    return {
        "user_id": user_id,
        "message_id": msg_id,
        "operator": request.operator
    }


@app.get("/admin/interventions")
async def list_halted_conversations():
    """List all halted conversations."""
    halted = get_halted_users()
    return {
        "count": len(halted),
        "halted_users": halted
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN: GUARDRAILS ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.post("/admin/guardrails")
async def create_guardrail_config(request: GuardrailCreate):
    """Create a new guardrail configuration."""
    try:
        config_id = create_config(
            name=request.name,
            rules=request.rules,
            description=request.description,
            created_by=request.created_by
        )
        return {
            "id": config_id,
            "name": request.name
        }
    except InvalidRulesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create config: {e}")


@app.get("/admin/guardrails")
async def list_guardrail_configs(include_inactive: bool = Query(False)):
    """List all guardrail configurations."""
    configs = list_configs(include_inactive=include_inactive)
    return {
        "count": len(configs),
        "configs": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "rule_count": len(c.rules),
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat(),
                "created_by": c.created_by
            }
            for c in configs
        ]
    }


@app.get("/admin/guardrails/presets")
async def list_preset_configs():
    """List available preset configurations."""
    return {
        "presets": get_preset_names()
    }


@app.get("/admin/guardrails/{name}")
async def get_guardrail_config(name: str):
    """Get a specific guardrail configuration by name."""
    try:
        config = get_config(name)
        return {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "rules": config.rules,
            "is_active": config.is_active,
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
            "created_by": config.created_by
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")


@app.get("/admin/guardrails/id/{config_id}")
async def get_guardrail_config_by_id(config_id: int):
    """Get a specific guardrail configuration by ID."""
    try:
        config = get_config_by_id(config_id)
        return {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "rules": config.rules,
            "is_active": config.is_active,
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
            "created_by": config.created_by
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config ID {config_id} not found")


@app.put("/admin/guardrails/{config_id}")
async def update_guardrail_config(config_id: int, request: GuardrailUpdate):
    """Update a guardrail configuration."""
    try:
        update_config(
            config_id=config_id,
            rules=request.rules,
            description=request.description,
            is_active=request.is_active
        )
        return {
            "id": config_id,
            "message": "Config updated successfully"
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config ID {config_id} not found")
    except InvalidRulesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {e}")


@app.delete("/admin/guardrails/{config_id}")
async def delete_guardrail_config(
    config_id: int,
    soft: bool = Query(True, description="Soft delete (inactive) vs hard delete")
):
    """Delete a guardrail configuration."""
    try:
        delete_config(config_id, soft=soft)
        return {
            "id": config_id,
            "message": f"Config {'deactivated' if soft else 'deleted'} successfully"
        }
    except GuardrailNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config ID {config_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete config: {e}")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ADMIN: TELEMETRY & STATS ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@app.get("/admin/stats/overview")
async def get_stats_overview():
    """Get aggregated dashboard statistics."""
    stats = get_dashboard_stats()
    return {
        "active_users_today": stats.active_users_today,
        "active_users_hour": stats.active_users_hour,
        "total_messages_today": stats.total_messages_today,
        "messages_per_hour": stats.messages_per_hour,
        "avg_response_time_ms": stats.avg_response_time_ms,
        "error_rate_percent": stats.error_rate_percent,
        "top_templates": stats.top_templates
    }


@app.get("/admin/stats/users/{user_id}")
async def get_user_statistics(user_id: str):
    """Get statistics for a specific user."""
    stats = get_user_stats(user_id)
    if not stats:
        raise HTTPException(status_code=404, detail=f"No statistics found for user {user_id}")
    return stats


@app.post("/admin/stats/aggregate")
async def trigger_aggregation():
    """Manually trigger metric aggregation."""
    try:
        aggregate_metrics()
        return {"status": "success", "message": "Metrics aggregated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Aggregation failed: {e}")
