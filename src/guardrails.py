"""
Guardrail configuration management for controlling LLM behavior.

This module manages system prompt instructions that override or control
the base LLM's built-in safety filters and behavior patterns.
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
    tenant_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _tenant_clause(tenant_id: Optional[int]) -> tuple[str, list]:
    """
    Return SQL clause and params for tenant filtering.
    NULL tenant_id = system/test data, use IS NULL check.
    """
    if tenant_id is None:
        return "tenant_id IS NULL", []
    else:
        return "tenant_id = %s", [tenant_id]


GUARDRAIL_COLUMNS = "id, name, description, rules, created_at, updated_at, created_by, is_active, tenant_id"


def _row_to_config(row) -> GuardrailConfig:
    """Convert database row to GuardrailConfig."""
    return GuardrailConfig(
        id=row[0],
        name=row[1],
        description=row[2],
        rules=row[3],
        created_at=row[4],
        updated_at=row[5],
        created_by=row[6],
        is_active=row[7],
        tenant_id=row[8]
    )


# ═══════════════════════════════════════════════════════════════════════
# CRUD OPERATIONS
# ═══════════════════════════════════════════════════════════════════════

def create_config(
    name: str,
    rules: List[Dict[str, Any]],
    description: Optional[str] = None,
    created_by: Optional[str] = None,
    tenant_id: Optional[int] = None
) -> int:
    """Create a new guardrail configuration."""
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
                INSERT INTO guardrail_configs (tenant_id, name, description, rules, created_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, name, description, json.dumps(rules), created_by)
            )
            config_id = cur.fetchone()[0]
        conn.commit()
        return config_id
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            raise GuardrailError(f"Config name '{name}' already exists")
        raise GuardrailError(f"Failed to create config: {e}")
    finally:
        put_conn(conn)


def get_config(name: str, tenant_id: Optional[int] = None) -> GuardrailConfig:
    """Get guardrail config by name."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            # First try tenant-specific config
            cur.execute(
                f"""
                SELECT {GUARDRAIL_COLUMNS}
                FROM guardrail_configs
                WHERE name = %s AND {tenant_clause} AND is_active = true
                """,
                [name] + tenant_params
            )
            row = cur.fetchone()
            
            # Fall back to system config (tenant_id IS NULL)
            if not row and tenant_id is not None:
                cur.execute(
                    f"""
                    SELECT {GUARDRAIL_COLUMNS}
                    FROM guardrail_configs
                    WHERE name = %s AND tenant_id IS NULL AND is_active = true
                    """,
                    (name,)
                )
                row = cur.fetchone()
            
            if not row:
                raise GuardrailNotFoundError(f"Config '{name}' not found")
            
            return _row_to_config(row)
    finally:
        put_conn(conn)


def get_config_by_id(config_id: int, tenant_id: Optional[int] = None) -> GuardrailConfig:
    """Get guardrail config by ID."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT {GUARDRAIL_COLUMNS}
                FROM guardrail_configs
                WHERE id = %s AND ({tenant_clause} OR tenant_id IS NULL)
                """,
                [config_id] + tenant_params
            )
            row = cur.fetchone()
            
            if not row:
                raise GuardrailNotFoundError(f"Config ID {config_id} not found")
            
            return _row_to_config(row)
    finally:
        put_conn(conn)


def list_configs(include_inactive: bool = False, tenant_id: Optional[int] = None) -> List[GuardrailConfig]:
    """List all guardrail configs for tenant (plus system configs)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            if include_inactive:
                cur.execute(
                    f"""
                    SELECT {GUARDRAIL_COLUMNS}
                    FROM guardrail_configs
                    WHERE {tenant_clause} OR tenant_id IS NULL
                    ORDER BY name
                    """,
                    tenant_params
                )
            else:
                cur.execute(
                    f"""
                    SELECT {GUARDRAIL_COLUMNS}
                    FROM guardrail_configs
                    WHERE ({tenant_clause} OR tenant_id IS NULL) AND is_active = true
                    ORDER BY name
                    """,
                    tenant_params
                )
            
            return [_row_to_config(row) for row in cur.fetchall()]
    finally:
        put_conn(conn)


def update_config(
    config_id: int,
    rules: Optional[List[Dict[str, Any]]] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    tenant_id: Optional[int] = None
) -> None:
    """Update guardrail config."""
    if rules is not None:
        if not isinstance(rules, list):
            raise InvalidRulesError("Rules must be a list")
        
        for rule in rules:
            if not isinstance(rule, dict):
                raise InvalidRulesError("Each rule must be a dictionary")
            if "type" not in rule:
                raise InvalidRulesError("Each rule must have a 'type' field")
    
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
        return
    
    updates.append("updated_at = NOW()")
    
    tenant_clause, tenant_params = _tenant_clause(tenant_id)
    params.append(config_id)
    params.extend(tenant_params)
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = f"UPDATE guardrail_configs SET {', '.join(updates)} WHERE id = %s AND {tenant_clause}"
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


def delete_config(config_id: int, soft: bool = True, tenant_id: Optional[int] = None) -> None:
    """Delete guardrail config."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            if soft:
                cur.execute(
                    f"UPDATE guardrail_configs SET is_active = false, updated_at = NOW() WHERE id = %s AND {tenant_clause}",
                    [config_id] + tenant_params
                )
            else:
                cur.execute(
                    f"DELETE FROM guardrail_configs WHERE id = %s AND {tenant_clause}",
                    [config_id] + tenant_params
                )
            
            if cur.rowcount == 0:
                raise GuardrailNotFoundError(f"Config ID {config_id} not found")
        
        conn.commit()
    except GuardrailNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise GuardrailError(f"Failed to delete config: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════
# APPLY LOGIC
# ═══════════════════════════════════════════════════════════════════════

def apply_guardrails(base_prompt: str, config_name: str, tenant_id: Optional[int] = None) -> str:
    """Apply guardrail config to modify system prompt."""
    config = get_config(config_name, tenant_id)
    
    sorted_rules = sorted(
        config.rules,
        key=lambda r: r.get("priority", 0),
        reverse=True
    )
    
    instructions = []
    for rule in sorted_rules:
        if rule["type"] == "system_instruction" and "content" in rule:
            instructions.append(rule["content"])
    
    if not instructions:
        return base_prompt
    
    guardrail_section = "\n\n".join(instructions)
    return f"{guardrail_section}\n\n{base_prompt}"


def get_preset_names() -> List[str]:
    """Get list of preset guardrail config names."""
    return ["unrestricted", "research_safe", "clinical"]


def validate_rules(rules: List[Dict[str, Any]]) -> bool:
    """Validate rules structure."""
    if not isinstance(rules, list):
        raise InvalidRulesError("Rules must be a list")
    
    for rule in rules:
        if not isinstance(rule, dict):
            raise InvalidRulesError("Each rule must be a dictionary")
        if "type" not in rule:
            raise InvalidRulesError("Each rule must have a 'type' field")
    
    return True
