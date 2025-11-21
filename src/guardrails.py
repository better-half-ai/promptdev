"""
Guardrail configuration management for controlling LLM behavior.

This module manages system prompt instructions that override or control
the base LLM's built-in safety filters and behavior patterns.

Operators can:
1. Use preset configs (unrestricted, research_safe, clinical)
2. Create custom guardrail configs with multiple rules
3. Apply configs to modify system prompts before LLM calls
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
import json

from db.db import get_conn, put_conn


# ═══════════════════════════════════════════════════════════════════════
# ERRORS
# ═══════════════════════════════════════════════════════════════════════

class GuardrailError(Exception):
    """Base exception for guardrail operations."""
    pass


class GuardrailNotFoundError(GuardrailError):
    """Raised when guardrail config doesn't exist."""
    pass


class InvalidRulesError(GuardrailError):
    """Raised when rules JSON is invalid."""
    pass


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════

class GuardrailConfig(BaseModel):
    """Guardrail configuration."""
    id: int
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    rules: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════
# CRUD OPERATIONS
# ═══════════════════════════════════════════════════════════════════════

def create_config(
    name: str,
    rules: List[Dict[str, Any]],
    description: Optional[str] = None,
    created_by: Optional[str] = None
) -> int:
    """
    Create a new guardrail configuration.
    
    Args:
        name: Unique config name
        rules: List of rule dictionaries
        description: Optional description
        created_by: Creator identifier
        
    Returns:
        Config ID
        
    Raises:
        InvalidRulesError: If rules are invalid
        GuardrailError: If creation fails
    """
    # Validate rules
    if not isinstance(rules, list):
        raise InvalidRulesError("Rules must be a list")
    
    for rule in rules:
        if not isinstance(rule, dict):
            raise InvalidRulesError("Each rule must be a dictionary")
        if "type" not in rule:
            raise InvalidRulesError("Each rule must have a 'type' field")
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO guardrail_configs (name, description, rules, created_by)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (name, description, json.dumps(rules), created_by)
            )
            config_id = cur.fetchone()[0]
        conn.commit()
        return config_id
    except Exception as e:
        conn.rollback()
        raise GuardrailError(f"Failed to create config: {e}")
    finally:
        put_conn(conn)


def get_config(name: str) -> GuardrailConfig:
    """
    Get guardrail config by name.
    
    Args:
        name: Config name
        
    Returns:
        GuardrailConfig object
        
    Raises:
        GuardrailNotFoundError: If config doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, rules, created_at, updated_at, created_by, is_active
                FROM guardrail_configs
                WHERE name = %s AND is_active = true
                """,
                (name,)
            )
            row = cur.fetchone()
            
            if not row:
                raise GuardrailNotFoundError(f"Config '{name}' not found")
            
            return GuardrailConfig(
                id=row[0],
                name=row[1],
                description=row[2],
                rules=row[3],  # PostgreSQL returns JSONB as Python list/dict
                created_at=row[4],
                updated_at=row[5],
                created_by=row[6],
                is_active=row[7]
            )
    finally:
        put_conn(conn)


def get_config_by_id(config_id: int) -> GuardrailConfig:
    """
    Get guardrail config by ID.
    
    Args:
        config_id: Config ID
        
    Returns:
        GuardrailConfig object
        
    Raises:
        GuardrailNotFoundError: If config doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, rules, created_at, updated_at, created_by, is_active
                FROM guardrail_configs
                WHERE id = %s
                """,
                (config_id,)
            )
            row = cur.fetchone()
            
            if not row:
                raise GuardrailNotFoundError(f"Config ID {config_id} not found")
            
            return GuardrailConfig(
                id=row[0],
                name=row[1],
                description=row[2],
                rules=row[3],
                created_at=row[4],
                updated_at=row[5],
                created_by=row[6],
                is_active=row[7]
            )
    finally:
        put_conn(conn)


def list_configs(include_inactive: bool = False) -> List[GuardrailConfig]:
    """
    List all guardrail configs.
    
    Args:
        include_inactive: Include inactive configs
        
    Returns:
        List of GuardrailConfig objects
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if include_inactive:
                query = "SELECT id, name, description, rules, created_at, updated_at, created_by, is_active FROM guardrail_configs ORDER BY name"
                cur.execute(query)
            else:
                query = "SELECT id, name, description, rules, created_at, updated_at, created_by, is_active FROM guardrail_configs WHERE is_active = true ORDER BY name"
                cur.execute(query)
            
            rows = cur.fetchall()
            
            return [
                GuardrailConfig(
                    id=row[0],
                    name=row[1],
                    description=row[2],
                    rules=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    created_by=row[6],
                    is_active=row[7]
                )
                for row in rows
            ]
    finally:
        put_conn(conn)


def update_config(
    config_id: int,
    rules: Optional[List[Dict[str, Any]]] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None
) -> None:
    """
    Update guardrail config.
    
    Args:
        config_id: Config ID to update
        rules: New rules (if provided)
        description: New description (if provided)
        is_active: New active status (if provided)
        
    Raises:
        GuardrailNotFoundError: If config doesn't exist
        InvalidRulesError: If rules are invalid
    """
    # Validate rules if provided
    if rules is not None:
        if not isinstance(rules, list):
            raise InvalidRulesError("Rules must be a list")
        
        for rule in rules:
            if not isinstance(rule, dict):
                raise InvalidRulesError("Each rule must be a dictionary")
            if "type" not in rule:
                raise InvalidRulesError("Each rule must have a 'type' field")
    
    # Build update query dynamically
    updates = []
    params = []
    
    if rules is not None:
        updates.append("rules = %s")
        params.append(json.dumps(rules))
    
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    
    if is_active is not None:
        updates.append("is_active = %s")
        params.append(is_active)
    
    if not updates:
        return  # Nothing to update
    
    updates.append("updated_at = NOW()")
    params.append(config_id)
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = f"UPDATE guardrail_configs SET {', '.join(updates)} WHERE id = %s"
            cur.execute(query, params)
            
            if cur.rowcount == 0:
                raise GuardrailNotFoundError(f"Config ID {config_id} not found")
        
        conn.commit()
    except GuardrailNotFoundError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise GuardrailError(f"Failed to update config: {e}")
    finally:
        put_conn(conn)


def delete_config(config_id: int, soft: bool = True) -> None:
    """
    Delete guardrail config.
    
    Args:
        config_id: Config ID to delete
        soft: If True, mark inactive; if False, hard delete
        
    Raises:
        GuardrailNotFoundError: If config doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if soft:
                cur.execute(
                    "UPDATE guardrail_configs SET is_active = false, updated_at = NOW() WHERE id = %s",
                    (config_id,)
                )
            else:
                cur.execute(
                    "DELETE FROM guardrail_configs WHERE id = %s",
                    (config_id,)
                )
            
            if cur.rowcount == 0:
                raise GuardrailNotFoundError(f"Config ID {config_id} not found")
        
        conn.commit()
    except GuardrailNotFoundError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise GuardrailError(f"Failed to delete config: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════
# APPLY LOGIC
# ═══════════════════════════════════════════════════════════════════════

def apply_guardrails(base_prompt: str, config_name: str) -> str:
    """
    Apply guardrail config to modify system prompt.
    
    Prepends guardrail system instructions to the base prompt.
    Rules are sorted by priority (higher priority first).
    
    Args:
        base_prompt: Original system prompt
        config_name: Guardrail config name to apply
        
    Returns:
        Modified prompt with guardrail instructions
        
    Raises:
        GuardrailNotFoundError: If config doesn't exist
    """
    config = get_config(config_name)
    
    # Sort rules by priority (higher first), default priority = 0
    sorted_rules = sorted(
        config.rules,
        key=lambda r: r.get("priority", 0),
        reverse=True
    )
    
    # Build guardrail instructions
    instructions = []
    for rule in sorted_rules:
        if rule["type"] == "system_instruction" and "content" in rule:
            instructions.append(rule["content"])
    
    if not instructions:
        return base_prompt
    
    # Prepend instructions to base prompt
    guardrail_section = "\n\n".join(instructions)
    return f"{guardrail_section}\n\n{base_prompt}"


def get_preset_names() -> List[str]:
    """
    Get list of preset guardrail config names.
    
    Returns:
        List of preset names
    """
    return ["unrestricted", "research_safe", "clinical"]


def validate_rules(rules: List[Dict[str, Any]]) -> bool:
    """
    Validate rules structure.
    
    Args:
        rules: List of rule dictionaries to validate
        
    Returns:
        True if valid
        
    Raises:
        InvalidRulesError: If rules are invalid
    """
    if not isinstance(rules, list):
        raise InvalidRulesError("Rules must be a list")
    
    for rule in rules:
        if not isinstance(rule, dict):
            raise InvalidRulesError("Each rule must be a dictionary")
        if "type" not in rule:
            raise InvalidRulesError("Each rule must have a 'type' field")
    
    return True
