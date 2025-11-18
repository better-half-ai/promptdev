"""
Template-based prompt management with Jinja2 rendering and immutable versioning.

This module provides:
- CRUD operations for prompt templates
- Immutable versioning (every change creates a new version)
- Rollback to any previous version
- Jinja2 template rendering with variable substitution
- Syntax validation before saving
- Full audit trail in prompt_version_history

Example:
    >>> # Create a template
    >>> template_id = create_template(
    ...     "system_greeting",
    ...     "You are {{role}}. Context: {{context}}"
    ... )
    >>> 
    >>> # Render with variables
    >>> content = render_template(
    ...     template_id,
    ...     {"role": "helpful assistant", "context": "customer support"}
    ... )
    >>> 
    >>> # Update creates new version
    >>> update_template(template_id, "You are {{role}}. Mission: {{mission}}")
    >>> 
    >>> # Rollback to v1 (creates v3 with v1 content)
    >>> rollback_to_version(template_id, 1)
"""

import logging
from typing import Optional, Any
from datetime import datetime
from jinja2 import Environment, TemplateSyntaxError as Jinja2SyntaxError, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, Field, field_validator

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
    
    @field_validator('content')
    @classmethod
    def validate_jinja2_syntax(cls, v: str) -> str:
        """Validate Jinja2 template syntax."""
        try:
            env = SandboxedEnvironment()
            env.parse(v)
            return v
        except Jinja2SyntaxError as e:
            raise TemplateSyntaxError(f"Invalid Jinja2 syntax: {e}")
    
    class Config:
        from_attributes = True


class TemplateVersion(BaseModel):
    """A version of a template in the history."""
    
    id: int
    template_id: int
    version: int = Field(ge=1)
    content: str
    created_at: datetime
    created_by: Optional[str] = None
    change_description: Optional[str] = None
    
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# CRUD OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════

def create_template(
    name: str,
    content: str,
    created_by: Optional[str] = None,
    change_description: Optional[str] = None
) -> int:
    """
    Create a new template with version 1.
    
    Args:
        name: Unique template name
        content: Jinja2 template content
        created_by: Optional user/system identifier
        change_description: Optional description of this template
    
    Returns:
        Template ID
    
    Raises:
        TemplateSyntaxError: If Jinja2 syntax is invalid
        PromptError: If database operation fails
    """
    # Validate syntax
    Template(
        id=0,
        name=name,
        content=content,
        current_version=1,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Insert template
            cur.execute(
                """
                INSERT INTO system_prompt (name, content, current_version, is_active)
                VALUES (%s, %s, 1, true)
                RETURNING id
                """,
                (name, content)
            )
            template_id = cur.fetchone()[0]
            
            # Insert version history
            cur.execute(
                """
                INSERT INTO prompt_version_history 
                (template_id, version, content, created_by, change_description)
                VALUES (%s, 1, %s, %s, %s)
                """,
                (template_id, content, created_by, change_description)
            )
            
            conn.commit()
            logger.info(f"Created template '{name}' (id={template_id}) v1")
            return template_id
            
    except Exception as e:
        conn.rollback()
        raise PromptError(f"Failed to create template: {e}")
    finally:
        put_conn(conn)


def get_template(template_id: int) -> Template:
    """
    Get a template by ID.
    
    Args:
        template_id: Template ID
    
    Returns:
        Template object
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, content, current_version, created_at, updated_at, is_active
                FROM system_prompt
                WHERE id = %s
                """,
                (template_id,)
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            
            return Template(
                id=row[0],
                name=row[1],
                content=row[2],
                current_version=row[3],
                created_at=row[4],
                updated_at=row[5],
                is_active=row[6]
            )
    finally:
        put_conn(conn)


def get_template_by_name(name: str) -> Template:
    """
    Get a template by name.
    
    Args:
        name: Template name
    
    Returns:
        Template object
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, content, current_version, created_at, updated_at, is_active
                FROM system_prompt
                WHERE name = %s
                """,
                (name,)
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template '{name}' not found")
            
            return Template(
                id=row[0],
                name=row[1],
                content=row[2],
                current_version=row[3],
                created_at=row[4],
                updated_at=row[5],
                is_active=row[6]
            )
    finally:
        put_conn(conn)


def list_templates(include_inactive: bool = False) -> list[Template]:
    """
    List all templates.
    
    Args:
        include_inactive: Whether to include inactive templates
    
    Returns:
        List of Template objects
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, name, content, current_version, created_at, updated_at, is_active
                FROM system_prompt
            """
            if not include_inactive:
                query += " WHERE is_active = true"
            query += " ORDER BY name"
            
            cur.execute(query)
            
            templates = []
            for row in cur.fetchall():
                templates.append(Template(
                    id=row[0],
                    name=row[1],
                    content=row[2],
                    current_version=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    is_active=row[6]
                ))
            return templates
    finally:
        put_conn(conn)


def update_template(
    template_id: int,
    content: str,
    created_by: Optional[str] = None,
    change_description: Optional[str] = None
) -> int:
    """
    Update template content (creates new version).
    
    Args:
        template_id: Template ID
        content: New template content
        created_by: Optional user/system identifier
        change_description: Optional description of changes
    
    Returns:
        New version number
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
        TemplateSyntaxError: If Jinja2 syntax is invalid
        PromptError: If database operation fails
    """
    # Validate syntax
    Template(
        id=template_id,
        name="temp",
        content=content,
        current_version=1,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Get current version
            cur.execute(
                "SELECT current_version, name FROM system_prompt WHERE id = %s",
                (template_id,)
            )
            row = cur.fetchone()
            if not row:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            
            current_version = row[0]
            name = row[1]
            new_version = current_version + 1
            
            # Update template
            cur.execute(
                """
                UPDATE system_prompt
                SET content = %s, current_version = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (content, new_version, template_id)
            )
            
            # Insert version history
            cur.execute(
                """
                INSERT INTO prompt_version_history
                (template_id, version, content, created_by, change_description)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (template_id, new_version, content, created_by, change_description)
            )
            
            conn.commit()
            logger.info(f"Updated template '{name}' (id={template_id}) to v{new_version}")
            return new_version
            
    except (TemplateNotFoundError, TemplateSyntaxError):
        raise
    except Exception as e:
        conn.rollback()
        raise PromptError(f"Failed to update template: {e}")
    finally:
        put_conn(conn)


def deactivate_template(template_id: int) -> None:
    """
    Deactivate a template (soft delete).
    
    Args:
        template_id: Template ID
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE system_prompt SET is_active = false, updated_at = NOW() WHERE id = %s",
                (template_id,)
            )
            if cur.rowcount == 0:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            conn.commit()
            logger.info(f"Deactivated template {template_id}")
    except TemplateNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise PromptError(f"Failed to deactivate template: {e}")
    finally:
        put_conn(conn)


def activate_template(template_id: int) -> None:
    """
    Activate a template.
    
    Args:
        template_id: Template ID
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE system_prompt SET is_active = true, updated_at = NOW() WHERE id = %s",
                (template_id,)
            )
            if cur.rowcount == 0:
                raise TemplateNotFoundError(f"Template {template_id} not found")
            conn.commit()
            logger.info(f"Activated template {template_id}")
    except TemplateNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise PromptError(f"Failed to activate template: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# VERSION MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def get_version_history(template_id: int) -> list[TemplateVersion]:
    """
    Get all versions of a template.
    
    Args:
        template_id: Template ID
    
    Returns:
        List of TemplateVersion objects (newest first)
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Verify template exists
            cur.execute("SELECT 1 FROM system_prompt WHERE id = %s", (template_id,))
            if not cur.fetchone():
                raise TemplateNotFoundError(f"Template {template_id} not found")
            
            # Get versions
            cur.execute(
                """
                SELECT id, template_id, version, content, created_at, created_by, change_description
                FROM prompt_version_history
                WHERE template_id = %s
                ORDER BY version DESC
                """,
                (template_id,)
            )
            
            versions = []
            for row in cur.fetchall():
                versions.append(TemplateVersion(
                    id=row[0],
                    template_id=row[1],
                    version=row[2],
                    content=row[3],
                    created_at=row[4],
                    created_by=row[5],
                    change_description=row[6]
                ))
            return versions
    finally:
        put_conn(conn)


def get_version(template_id: int, version: int) -> TemplateVersion:
    """
    Get a specific version of a template.
    
    Args:
        template_id: Template ID
        version: Version number
    
    Returns:
        TemplateVersion object
    
    Raises:
        TemplateNotFoundError: If template or version doesn't exist
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
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
                raise TemplateNotFoundError(
                    f"Template {template_id} version {version} not found"
                )
            
            return TemplateVersion(
                id=row[0],
                template_id=row[1],
                version=row[2],
                content=row[3],
                created_at=row[4],
                created_by=row[5],
                change_description=row[6]
            )
    finally:
        put_conn(conn)


def rollback_to_version(
    template_id: int,
    version: int,
    created_by: Optional[str] = None
) -> int:
    """
    Rollback template to a previous version (creates new version with old content).
    
    Args:
        template_id: Template ID
        version: Version to rollback to
        created_by: Optional user/system identifier
    
    Returns:
        New version number
    
    Raises:
        TemplateNotFoundError: If template or version doesn't exist
        PromptError: If database operation fails
    """
    # Get the version content
    old_version = get_version(template_id, version)
    
    # Create new version with old content
    change_desc = f"Rollback to version {version}"
    new_version = update_template(
        template_id,
        old_version.content,
        created_by,
        change_desc
    )
    
    logger.info(f"Rolled back template {template_id} from v{version} to new v{new_version}")
    return new_version


# ═══════════════════════════════════════════════════════════════════════════
# RENDERING
# ═══════════════════════════════════════════════════════════════════════════

def render_template(
    template_id: int,
    variables: Optional[dict[str, Any]] = None
) -> str:
    """
    Render a template with variables.
    
    Args:
        template_id: Template ID
        variables: Dictionary of template variables
    
    Returns:
        Rendered template content
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
        TemplateRenderError: If rendering fails
    """
    template = get_template(template_id)
    
    try:
        env = SandboxedEnvironment(
            autoescape=False,
            undefined=StrictUndefined
        )
        jinja_template = env.from_string(template.content)
        return jinja_template.render(**(variables or {}))
        
    except Exception as e:
        raise TemplateRenderError(f"Failed to render template: {e}")


def render_template_by_name(
    name: str,
    variables: Optional[dict[str, Any]] = None
) -> str:
    """
    Render a template by name with variables.
    
    Args:
        name: Template name
        variables: Dictionary of template variables
    
    Returns:
        Rendered template content
    
    Raises:
        TemplateNotFoundError: If template doesn't exist
        TemplateRenderError: If rendering fails
    """
    template = get_template_by_name(name)
    
    try:
        env = SandboxedEnvironment(
            autoescape=False,
            undefined=StrictUndefined
        )
        jinja_template = env.from_string(template.content)
        return jinja_template.render(**(variables or {}))
        
    except Exception as e:
        raise TemplateRenderError(f"Failed to render template: {e}")
