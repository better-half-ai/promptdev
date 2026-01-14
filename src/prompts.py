"""
Template-based prompt management with Jinja2 rendering and multi-tenant support.
"""

import logging
from typing import Optional, Any
from datetime import datetime
from jinja2 import TemplateSyntaxError as Jinja2SyntaxError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, Field, ConfigDict

from db.db import get_conn, put_conn

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ERRORS
# ═══════════════════════════════════════════════════════════════════════════

class PromptError(Exception):
    """Base exception for prompt operations."""
    pass


class TemplateNotFoundError(PromptError):
    """Template does not exist."""
    pass


class TemplateSyntaxError(PromptError):
    """Invalid Jinja2 syntax in template."""
    pass


class TemplateRenderError(PromptError):
    """Error rendering template with provided variables."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

class Template(BaseModel):
    """A prompt template with metadata."""
    
    id: int
    name: str = Field(..., min_length=1, max_length=255)
    content: str
    current_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    tenant_id: Optional[int] = None
    is_shareable: bool = False
    cloned_from_id: Optional[int] = None
    cloned_from_tenant: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


class TemplateVersion(BaseModel):
    """A version of a template in the history."""
    
    id: int
    template_id: int
    version: int = Field(ge=1)
    content: str
    created_at: datetime
    created_by: Optional[str] = None
    change_description: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _tenant_clause(tenant_id: Optional[int]) -> tuple[str, list]:
    """
    Return SQL clause and params for tenant filtering.
    NULL tenant_id = system/test data.
    """
    if tenant_id is None:
        return "tenant_id IS NULL", []
    return "tenant_id = %s", [tenant_id]


TEMPLATE_COLUMNS = """
    id, name, content, current_version, created_at, updated_at, 
    is_active, tenant_id, is_shareable, cloned_from_id, cloned_from_tenant
"""


def _row_to_template(row) -> Template:
    """Convert a database row to a Template object."""
    return Template(
        id=row[0],
        name=row[1],
        content=row[2],
        current_version=row[3],
        created_at=row[4],
        updated_at=row[5],
        is_active=row[6],
        tenant_id=row[7],
        is_shareable=row[8] if row[8] is not None else False,
        cloned_from_id=row[9],
        cloned_from_tenant=row[10]
    )


def _validate_jinja2(content: str) -> None:
    """Validate Jinja2 syntax."""
    try:
        env = SandboxedEnvironment()
        env.parse(content)
    except Jinja2SyntaxError as e:
        raise TemplateSyntaxError(f"Invalid Jinja2 syntax: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CRUD OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════

def create_template(
    name: str,
    content: str,
    created_by: Optional[str] = None,
    change_description: Optional[str] = None,
    tenant_id: Optional[int] = None
) -> int:
    """Create a new template with version 1."""
    if not name or not name.strip():
        raise PromptError("Template name cannot be empty")
    
    _validate_jinja2(content)
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_prompt (tenant_id, name, content, current_version)
                VALUES (%s, %s, %s, 1)
                RETURNING id
                """,
                (tenant_id, name, content)
            )
            template_id = cur.fetchone()[0]
            
            cur.execute(
                """
                INSERT INTO prompt_version_history 
                (tenant_id, template_id, version, content, created_by, change_description)
                VALUES (%s, %s, 1, %s, %s, %s)
                """,
                (tenant_id, template_id, content, created_by, change_description)
            )
            
            conn.commit()
            return template_id
            
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            raise PromptError(f"Template name '{name}' already exists")
        raise PromptError(f"Failed to create template: {e}")
    finally:
        put_conn(conn)


def get_template(template_id: int, tenant_id: Optional[int] = None) -> Template:
    """Get a template by ID."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT {TEMPLATE_COLUMNS} FROM system_prompt WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            return _row_to_template(row)
    finally:
        put_conn(conn)


def get_template_by_name(name: str, tenant_id: Optional[int] = None) -> Template:
    """Get a template by name."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT {TEMPLATE_COLUMNS} FROM system_prompt WHERE name = %s AND {tenant_clause}",
                [name] + tenant_params
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template '{name}' not found")
            return _row_to_template(row)
    finally:
        put_conn(conn)


def list_templates(include_inactive: bool = False, tenant_id: Optional[int] = None) -> list[Template]:
    """List templates for a tenant. Auto-clones default template if tenant has none."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            
            # Check if tenant has any templates
            cur.execute(
                f"SELECT COUNT(*) FROM system_prompt WHERE {tenant_clause}",
                tenant_params
            )
            count = cur.fetchone()[0]
            
            # If no templates and tenant_id is set, clone the default system template
            if count == 0 and tenant_id is not None:
                _clone_default_template_for_tenant(cur, tenant_id)
                conn.commit()
            
            if include_inactive:
                cur.execute(
                    f"SELECT {TEMPLATE_COLUMNS} FROM system_prompt WHERE {tenant_clause} ORDER BY name",
                    tenant_params
                )
            else:
                cur.execute(
                    f"SELECT {TEMPLATE_COLUMNS} FROM system_prompt WHERE {tenant_clause} AND is_active = true ORDER BY name",
                    tenant_params
                )
            return [_row_to_template(row) for row in cur.fetchall()]
    finally:
        put_conn(conn)


def _clone_default_template_for_tenant(cur, tenant_id: int) -> Optional[int]:
    """Clone the default system template to a tenant. Returns new template ID or None."""
    # Find the default system template (tenant_id IS NULL, name = 'default')
    cur.execute(
        "SELECT id, content FROM system_prompt WHERE tenant_id IS NULL AND name = 'default' LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        logger.warning("No default system template found to clone")
        return None
    
    source_id, content = row
    
    # Clone it for this tenant
    cur.execute(
        """
        INSERT INTO system_prompt 
        (tenant_id, name, content, current_version, cloned_from_id)
        VALUES (%s, 'default', %s, 1, %s)
        RETURNING id
        """,
        (tenant_id, content, source_id)
    )
    new_id = cur.fetchone()[0]
    
    # Add version history
    cur.execute(
        """
        INSERT INTO prompt_version_history 
        (tenant_id, template_id, version, content, created_by, change_description)
        VALUES (%s, %s, 1, %s, 'system', 'Auto-cloned from default template')
        """,
        (tenant_id, new_id, content)
    )
    
    logger.info(f"Auto-cloned default template for tenant {tenant_id}, new template id={new_id}")
    return new_id


def update_template(
    template_id: int,
    content: str,
    created_by: Optional[str] = None,
    change_description: Optional[str] = None,
    tenant_id: Optional[int] = None
) -> int:
    """Update template content, creating a new version."""
    _validate_jinja2(content)
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT current_version FROM system_prompt WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            
            new_version = row[0] + 1
            
            cur.execute(
                f"""
                UPDATE system_prompt 
                SET content = %s, current_version = %s, updated_at = NOW()
                WHERE id = %s AND {tenant_clause}
                """,
                [content, new_version, template_id] + tenant_params
            )
            
            cur.execute(
                """
                INSERT INTO prompt_version_history 
                (tenant_id, template_id, version, content, created_by, change_description)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (tenant_id, template_id, new_version, content, created_by, change_description)
            )
            
            conn.commit()
            return new_version
            
    except TemplateNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise PromptError(f"Failed to update template: {e}")
    finally:
        put_conn(conn)


def deactivate_template(template_id: int, tenant_id: Optional[int] = None) -> bool:
    """Soft delete a template by setting is_active = false."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"UPDATE system_prompt SET is_active = false, updated_at = NOW() WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            if cur.rowcount == 0:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            conn.commit()
            return True
    finally:
        put_conn(conn)


def activate_template(template_id: int, tenant_id: Optional[int] = None) -> bool:
    """Re-activate a deactivated template."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"UPDATE system_prompt SET is_active = true, updated_at = NOW() WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            if cur.rowcount == 0:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            conn.commit()
            return True
    finally:
        put_conn(conn)


def delete_template(template_id: int, tenant_id: Optional[int] = None) -> bool:
    """Hard delete a template and its version history."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"DELETE FROM system_prompt WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# VERSION MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def get_version_history(template_id: int, tenant_id: Optional[int] = None) -> list[TemplateVersion]:
    """Get all versions of a template."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT id FROM system_prompt WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            if not cur.fetchone():
                raise TemplateNotFoundError(f"Template {template_id} not found")
            
            cur.execute(
                """
                SELECT id, template_id, version, content, created_at, created_by, change_description
                FROM prompt_version_history
                WHERE template_id = %s
                ORDER BY version DESC
                """,
                (template_id,)
            )
            return [
                TemplateVersion(
                    id=row[0], template_id=row[1], version=row[2],
                    content=row[3], created_at=row[4], created_by=row[5],
                    change_description=row[6]
                )
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def get_version(template_id: int, version: int, tenant_id: Optional[int] = None) -> TemplateVersion:
    """Get a specific version of a template."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT id FROM system_prompt WHERE id = %s AND {tenant_clause}",
                [template_id] + tenant_params
            )
            if not cur.fetchone():
                raise TemplateNotFoundError(f"Template {template_id} not found")
            
            cur.execute(
                """
                SELECT id, template_id, version, content, created_at, created_by, change_description
                FROM prompt_version_history
                WHERE template_id = %s AND version = %s
                """,
                (template_id, version)
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Version {version} of template {template_id} not found")
            
            return TemplateVersion(
                id=row[0], template_id=row[1], version=row[2],
                content=row[3], created_at=row[4], created_by=row[5],
                change_description=row[6]
            )
    finally:
        put_conn(conn)


def rollback_to_version(
    template_id: int,
    version: int,
    created_by: Optional[str] = None,
    tenant_id: Optional[int] = None
) -> int:
    """Rollback template to a previous version (creates new version with old content)."""
    old_version = get_version(template_id, version, tenant_id)
    return update_template(
        template_id,
        old_version.content,
        created_by=created_by,
        change_description=f"Rollback to version {version}",
        tenant_id=tenant_id
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE RENDERING
# ═══════════════════════════════════════════════════════════════════════════

def render_template(
    template_id: int,
    variables: Optional[dict[str, Any]] = None,
    tenant_id: Optional[int] = None
) -> str:
    """Render a template with variables."""
    template = get_template(template_id, tenant_id)
    return _render_content(template.content, variables)


def render_template_by_name(
    name: str,
    variables: Optional[dict[str, Any]] = None,
    tenant_id: Optional[int] = None
) -> str:
    """Render a template by name with variables."""
    template = get_template_by_name(name, tenant_id)
    return _render_content(template.content, variables)


def _render_content(content: str, variables: Optional[dict[str, Any]] = None) -> str:
    """Internal: render template content with variables."""
    from jinja2 import StrictUndefined
    
    if variables is None:
        variables = {}
    
    try:
        env = SandboxedEnvironment(undefined=StrictUndefined)
        template = env.from_string(content)
        return template.render(**variables)
    except Jinja2SyntaxError as e:
        raise TemplateSyntaxError(f"Invalid Jinja2 syntax: {e}")
    except Exception as e:
        raise TemplateRenderError(f"Failed to render template: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE SHARING
# ═══════════════════════════════════════════════════════════════════════════

def set_template_shareable(template_id: int, is_shareable: bool, tenant_id: Optional[int] = None) -> bool:
    """Set whether a template is shareable."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"UPDATE system_prompt SET is_shareable = %s, updated_at = NOW() WHERE id = %s AND {tenant_clause}",
                [is_shareable, template_id] + tenant_params
            )
            conn.commit()
            return cur.rowcount > 0
    finally:
        put_conn(conn)


def list_shared_templates() -> list[Template]:
    """List all shareable templates."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {TEMPLATE_COLUMNS} FROM system_prompt WHERE is_shareable = true AND is_active = true ORDER BY name"
            )
            return [_row_to_template(row) for row in cur.fetchall()]
    finally:
        put_conn(conn)


def clone_template(source_template_id: int, tenant_id: int, new_name: Optional[str] = None) -> int:
    """Clone a shared template into a tenant's space."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # First check if template exists at all
            cur.execute(
                f"SELECT {TEMPLATE_COLUMNS} FROM system_prompt WHERE id = %s",
                (source_template_id,)
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template {source_template_id} not found")
            
            source = _row_to_template(row)
            if not source.is_shareable:
                raise PromptError(f"Template {source_template_id} is not shareable")
            
            clone_name = new_name or f"{source.name}_clone"
            
            cur.execute(
                """
                INSERT INTO system_prompt 
                (tenant_id, name, content, current_version, cloned_from_id, cloned_from_tenant)
                VALUES (%s, %s, %s, 1, %s, %s)
                RETURNING id
                """,
                (tenant_id, clone_name, source.content, source_template_id, source.tenant_id)
            )
            new_id = cur.fetchone()[0]
            
            cur.execute(
                """
                INSERT INTO prompt_version_history 
                (tenant_id, template_id, version, content, created_by, change_description)
                VALUES (%s, %s, 1, %s, %s, %s)
                """,
                (tenant_id, new_id, source.content, "system", f"Cloned from template {source_template_id}")
            )
            
            conn.commit()
            return new_id
            
    except TemplateNotFoundError:
        raise
    except PromptError:
        raise
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            raise PromptError(f"Template name already exists")
        raise PromptError(f"Failed to clone template: {e}")
    finally:
        put_conn(conn)
