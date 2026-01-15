"""
Context builder for assembling prompts from templates, memory, and history.

This module combines:
- Templates (from prompts.py)
- User memory (from memory.py)
- Conversation history (from memory.py)

Into a final rendered prompt ready for the LLM.
"""

import logging
from typing import Optional, Any
from datetime import datetime

from src.prompts import (
    get_template_by_name,
    render_template,
    TemplateNotFoundError,
)
from src.memory import (
    get_recent_messages,
    get_all_memory,
    get_user_state,
    count_messages,
    ConversationMessage,
)
from src.guardrails import apply_guardrails

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ERRORS
# ═══════════════════════════════════════════════════════════════════════════

class ContextError(Exception):
    """Base exception for context operations."""
    pass


class ContextBuildError(ContextError):
    """Error building context from template and data."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# HISTORY FORMATTING
# ═══════════════════════════════════════════════════════════════════════════

def format_history_for_template(
    messages: list[ConversationMessage],
    format_style: str = "default"
) -> list[dict[str, str]]:
    """Format conversation messages for template rendering."""
    if format_style == "compact":
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
    elif format_style == "detailed":
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
                "id": msg.id
            }
            for msg in messages
        ]
    else:
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]


def format_history_as_text(
    messages: list[ConversationMessage],
    include_roles: bool = True
) -> str:
    """Format conversation messages as plain text."""
    if not messages:
        return ""

    lines = []
    for msg in messages:
        if include_roles:
            role_label = "User" if msg.role == "user" else "Assistant"
            lines.append(f"{role_label}: {msg.content}")
        else:
            lines.append(msg.content)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY FORMATTING
# ═══════════════════════════════════════════════════════════════════════════

def format_memory_for_template(memories: list) -> dict[str, Any]:
    """Format user memories as a dict for template rendering."""
    return {mem.key: mem.value for mem in memories}


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT BUILDING
# ═══════════════════════════════════════════════════════════════════════════

def build_context_variables(
    user_id: str,
    history_limit: int = 10,
    include_memory: bool = True,
    include_state: bool = True,
    tenant_id: Optional[int] = None
) -> dict[str, Any]:
    """Gather all context data for a user."""
    # Get conversation history
    messages = get_recent_messages(user_id, count=history_limit, tenant_id=tenant_id)

    # Format history in multiple ways for template flexibility
    history = format_history_for_template(messages, format_style="default")
    history_text = format_history_as_text(messages, include_roles=True)

    # Get user memory
    memory = {}
    if include_memory:
        memories = get_all_memory(user_id, tenant_id=tenant_id)
        memory = format_memory_for_template(memories)

    # Get user state
    state = None
    if include_state:
        user_state = get_user_state(user_id, tenant_id=tenant_id)
        if user_state:
            state = user_state.mode

    return {
        "user_id": user_id,
        "history": history,
        "history_text": history_text,
        "memory": memory,
        "state": state,
        "timestamp": datetime.now().isoformat(),
        "has_history": len(messages) > 0,
        "message_count": len(messages)
    }


def build_prompt_context(
    user_id: str,
    template_name: str,
    history_limit: int = 10,
    additional_variables: Optional[dict[str, Any]] = None,
    guardrail_config: Optional[str] = None,
    tenant_id: Optional[int] = None
) -> str:
    """Build complete prompt from template, memory, and history."""
    try:
        # Get template
        template = get_template_by_name(template_name, tenant_id=tenant_id)

        # Build context variables
        variables = build_context_variables(
            user_id,
            history_limit=history_limit,
            include_memory=True,
            include_state=True,
            tenant_id=tenant_id
        )

        # Merge with additional variables (additional takes precedence)
        if additional_variables:
            variables.update(additional_variables)

        # Render template
        rendered = render_template(template.id, variables, tenant_id=tenant_id)

        logger.info(
            f"Built prompt context for user {user_id} using template '{template_name}' "
            f"(history: {variables['message_count']} messages)"
        )

        # Apply guardrails if specified
        if guardrail_config:
            rendered = apply_guardrails(rendered, guardrail_config, tenant_id=tenant_id)

        return rendered

    except TemplateNotFoundError:
        raise
    except Exception as e:
        raise ContextBuildError(f"Failed to build context: {e}")


def build_prompt_context_simple(
    user_id: str,
    template_name: str,
    user_message: str,
    guardrail_config: Optional[str] = None,
    tenant_id: Optional[int] = None,
    session_id: Optional[int] = None
) -> str:
    """Simplified context builder for immediate user message."""
    additional_vars = {"current_message": user_message}
    
    # Build base prompt
    rendered = build_prompt_context(
        user_id,
        template_name,
        additional_variables=additional_vars,
        guardrail_config=guardrail_config,
        tenant_id=tenant_id
    )
    
    # Auto-inject sentiment context if session_id provided (regardless of template)
    if session_id is not None:
        try:
            from src.sentiment import generate_sentiment_context
            sentiment_ctx = generate_sentiment_context(session_id)
            if sentiment_ctx:
                # Inject after system prompt, before user message
                # Find the user message marker and insert before it
                if "<|im_start|>user" in rendered:
                    rendered = rendered.replace(
                        "<|im_start|>user",
                        f"{sentiment_ctx}\n<|im_start|>user"
                    )
                else:
                    # Fallback: prepend to prompt
                    rendered = f"{sentiment_ctx}\n{rendered}"
        except Exception as e:
            logger.warning(f"Failed to inject sentiment context: {e}")
    
    return rendered


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT INSPECTION
# ═══════════════════════════════════════════════════════════════════════════

def get_context_summary(user_id: str, tenant_id: Optional[int] = None) -> dict[str, Any]:
    """Get summary of available context for a user."""
    # Count messages
    message_count = count_messages(user_id, tenant_id=tenant_id)

    # Get memory keys
    memories = get_all_memory(user_id, tenant_id=tenant_id)
    memory_keys = [m.key for m in memories]

    # Get state
    user_state = get_user_state(user_id, tenant_id=tenant_id)
    state = user_state.mode if user_state else None

    return {
        "user_id": user_id,
        "message_count": message_count,
        "memory_count": len(memories),
        "memory_keys": memory_keys,
        "state": state,
        "has_context": message_count > 0 or len(memories) > 0
    }


def preview_prompt_context(
    user_id: str,
    template_name: str,
    history_limit: int = 10,
    tenant_id: Optional[int] = None
) -> dict[str, Any]:
    """Preview what context would be used for a prompt."""
    template = get_template_by_name(template_name, tenant_id=tenant_id)
    variables = build_context_variables(
        user_id,
        history_limit=history_limit,
        tenant_id=tenant_id
    )
    
    return {
        "template_name": template.name,
        "template_id": template.id,
        "template_version": template.current_version,
        "template_content": template.content,
        "variables": variables,
        "variable_keys": list(variables.keys()),
        "would_render": True
    }
