"""
Context builder for assembling prompts from templates, memory, and history.

This module combines:
- Templates (from prompts.py)
- User memory (from memory.py)
- Conversation history (from memory.py)

Into a final rendered prompt ready for the LLM.

Example:
    >>> # Build complete prompt
    >>> prompt = build_prompt_context(
    ...     user_id="user123",
    ...     template_name="chatbot",
    ...     history_limit=10
    ... )
    >>> 
    >>> # Use with LLM
    >>> response = await call_mistral(prompt)
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
    ConversationMessage,
)

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
    """
    Format conversation messages for template rendering.
    
    Args:
        messages: List of conversation messages (chronological order)
        format_style: Formatting style ('default', 'compact', 'detailed')
    
    Returns:
        List of dicts with 'role' and 'content' keys
    
    Example:
        >>> messages = get_recent_messages("user123", 5)
        >>> formatted = format_history_for_template(messages)
        >>> # [{"role": "user", "content": "Hello"}, ...]
    """
    if format_style == "compact":
        # Just role and content, no timestamps
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
    
    elif format_style == "detailed":
        # Include timestamps and IDs
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
                "id": msg.id
            }
            for msg in messages
        ]
    
    else:  # default
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]


def format_history_as_text(
    messages: list[ConversationMessage],
    include_roles: bool = True
) -> str:
    """
    Format conversation messages as plain text.
    
    Useful for templates that want history as a single string
    rather than structured data.
    
    Args:
        messages: List of conversation messages (chronological order)
        include_roles: Include "User:" and "Assistant:" labels
    
    Returns:
        Formatted text string
    
    Example:
        >>> messages = get_recent_messages("user123", 3)
        >>> text = format_history_as_text(messages)
        >>> print(text)
        User: Hello
        Assistant: Hi there!
        User: How are you?
    """
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
    """
    Format user memories as a dict for template rendering.
    
    Args:
        memories: List of UserMemory objects
    
    Returns:
        Dict mapping memory keys to values
    
    Example:
        >>> memories = get_all_memory("user123")
        >>> formatted = format_memory_for_template(memories)
        >>> # {"preferences": {...}, "context": {...}}
    """
    return {mem.key: mem.value for mem in memories}


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT BUILDING
# ═══════════════════════════════════════════════════════════════════════════

def build_context_variables(
    user_id: str,
    history_limit: int = 10,
    include_memory: bool = True,
    include_state: bool = True
) -> dict[str, Any]:
    """
    Gather all context data for a user.
    
    Args:
        user_id: User identifier
        history_limit: Number of recent messages to include
        include_memory: Include user memory in context
        include_state: Include user state in context
    
    Returns:
        Dict of template variables:
        {
            "user_id": str,
            "history": list[dict],
            "history_text": str,
            "memory": dict,
            "state": str | None,
            "timestamp": str
        }
    
    Example:
        >>> variables = build_context_variables("user123", history_limit=5)
        >>> variables["user_id"]
        'user123'
        >>> variables["history"]
        [{"role": "user", "content": "Hello"}, ...]
    """
    # Get conversation history
    messages = get_recent_messages(user_id, count=history_limit)
    
    # Format history in multiple ways for template flexibility
    history = format_history_for_template(messages, format_style="default")
    history_text = format_history_as_text(messages, include_roles=True)
    
    # Get user memory
    memory = {}
    if include_memory:
        memories = get_all_memory(user_id)
        memory = format_memory_for_template(memories)
    
    # Get user state
    state = None
    if include_state:
        user_state = get_user_state(user_id)
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
    additional_variables: Optional[dict[str, Any]] = None
) -> str:
    """
    Build complete prompt from template, memory, and history.
    
    This is the main function for assembling prompts. It:
    1. Gets the template by name
    2. Gathers user context (history, memory, state)
    3. Combines with any additional variables
    4. Renders the template
    
    Args:
        user_id: User identifier
        template_name: Name of template to use
        history_limit: Number of recent messages to include
        additional_variables: Extra variables to pass to template
    
    Returns:
        Rendered prompt string ready for LLM
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
        ContextBuildError: If context building fails
    
    Example:
        >>> # Simple usage
        >>> prompt = build_prompt_context("user123", "chatbot")
        >>> 
        >>> # With additional variables
        >>> prompt = build_prompt_context(
        ...     "user123",
        ...     "code_assistant",
        ...     history_limit=20,
        ...     additional_variables={"language": "Python"}
        ... )
    """
    try:
        # Get template
        template = get_template_by_name(template_name)
        
        # Build context variables
        variables = build_context_variables(
            user_id,
            history_limit=history_limit,
            include_memory=True,
            include_state=True
        )
        
        # Merge with additional variables (additional takes precedence)
        if additional_variables:
            variables.update(additional_variables)
        
        # Render template
        rendered = render_template(template.id, variables)
        
        logger.info(
            f"Built prompt context for user {user_id} using template '{template_name}' "
            f"(history: {variables['message_count']} messages)"
        )
        
        return rendered
        
    except TemplateNotFoundError:
        raise
    except Exception as e:
        raise ContextBuildError(f"Failed to build context: {e}")


def build_prompt_context_simple(
    user_id: str,
    template_name: str,
    user_message: str
) -> str:
    """
    Simplified context builder for immediate user message.
    
    Convenience function that adds the current user message
    as a variable for the template.
    
    Args:
        user_id: User identifier
        template_name: Name of template to use
        user_message: Current user message (not yet saved)
    
    Returns:
        Rendered prompt string
    
    Example:
        >>> prompt = build_prompt_context_simple(
        ...     "user123",
        ...     "chatbot",
        ...     "What is Python?"
        ... )
    """
    return build_prompt_context(
        user_id,
        template_name,
        additional_variables={"current_message": user_message}
    )


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT INSPECTION
# ═══════════════════════════════════════════════════════════════════════════

def get_context_summary(user_id: str) -> dict[str, Any]:
    """
    Get summary of available context for a user.
    
    Useful for debugging or showing user their context.
    
    Args:
        user_id: User identifier
    
    Returns:
        Dict with context statistics
    
    Example:
        >>> summary = get_context_summary("user123")
        >>> print(f"User has {summary['message_count']} messages")
        >>> print(f"Memory keys: {summary['memory_keys']}")
    """
    from src.memory import count_messages
    
    # Count messages
    message_count = count_messages(user_id)
    
    # Get memory keys
    memories = get_all_memory(user_id)
    memory_keys = [m.key for m in memories]
    
    # Get state
    user_state = get_user_state(user_id)
    state = user_state.mode if user_state else None
    
    return {
        "user_id": user_id,
        "message_count": message_count,
        "memory_keys": memory_keys,
        "memory_count": len(memories),
        "state": state,
        "has_context": message_count > 0 or len(memories) > 0
    }


def preview_prompt_context(
    user_id: str,
    template_name: str,
    history_limit: int = 10
) -> dict[str, Any]:
    """
    Preview what would be sent to LLM without actually rendering.
    
    Useful for debugging template issues.
    
    Args:
        user_id: User identifier
        template_name: Name of template to use
        history_limit: Number of recent messages to include
    
    Returns:
        Dict with template info and variables
    
    Example:
        >>> preview = preview_prompt_context("user123", "chatbot")
        >>> print(preview["template_content"][:100])
        >>> print(preview["variables"].keys())
    """
    # Get template
    template = get_template_by_name(template_name)
    
    # Build variables
    variables = build_context_variables(
        user_id,
        history_limit=history_limit
    )
    
    return {
        "template_id": template.id,
        "template_name": template.name,
        "template_content": template.content,
        "template_version": template.current_version,
        "variables": variables,
        "variable_keys": list(variables.keys())
    }