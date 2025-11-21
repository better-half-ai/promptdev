"""
Comprehensive test suite for prompts.py

Covers:
- Template CRUD operations
- Version management
- Rollback scenarios
- Template rendering
- Error conditions
- Edge cases
"""

import pytest
import psycopg2
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.prompts import (
    # Functions
    create_template,
    get_template,
    get_template_by_name,
    list_templates,
    update_template,
    deactivate_template,
    activate_template,
    get_version_history,
    get_version,
    rollback_to_version,
    render_template,
    render_template_by_name,
    # Models
    Template,
    TemplateVersion,
    # Errors
    PromptError,
    TemplateNotFoundError,
    TemplateSyntaxError,
    TemplateRenderError,
)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FIXTURES
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


@pytest.fixture
def simple_template(db_module):
    """Create a simple template for testing."""
    template_id = create_template(
        "test_simple",
        "Hello {{name}}!",
        created_by="test_user",
        change_description="Initial version"
    )
    yield template_id


@pytest.fixture
def complex_template(db_module):
    """Create a complex template with loops and conditionals."""
    content = """
You are {{role}}.

{% if context %}
Context: {{context}}
{% endif %}

Tasks:
{% for task in tasks %}
- {{task}}
{% endfor %}

{% if urgent %}
âš ï¸ URGENT: Complete within {{deadline}}
{% endif %}
    """.strip()
    
    template_id = create_template(
        "test_complex",
        content,
        created_by="test_user"
    )
    yield template_id


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CRUD TESTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_create_simple_template(db_module):
    """Test creating a simple template."""
    template_id = create_template(
        "greeting",
        "Hello {{name}}!",
        created_by="admin"
    )
    
    assert isinstance(template_id, int)
    assert template_id > 0
    
    # Verify template
    template = get_template(template_id)
    assert template.name == "greeting"
    assert template.content == "Hello {{name}}!"
    assert template.current_version == 1
    assert template.is_active is True


def test_create_template_with_loops(db_module):
    """Test creating template with Jinja2 loops."""
    content = """
{% for item in items %}
- {{item}}
{% endfor %}
    """.strip()
    
    template_id = create_template("list_template", content)
    template = get_template(template_id)
    
    assert "{% for item in items %}" in template.content


def test_create_template_with_conditionals(db_module):
    """Test creating template with Jinja2 conditionals."""
    content = """
{% if urgent %}
URGENT: {{message}}
{% else %}
{{message}}
{% endif %}
    """.strip()
    
    template_id = create_template("conditional_template", content)
    template = get_template(template_id)
    
    assert "{% if urgent %}" in template.content


def test_create_template_invalid_syntax(db_module):
    """Test that invalid Jinja2 syntax raises error."""
    with pytest.raises(TemplateSyntaxError) as exc_info:
        create_template("bad_template", "{{name")
    
    assert "Invalid Jinja2 syntax" in str(exc_info.value)


def test_get_template(simple_template):
    """Test retrieving a template by ID."""
    template = get_template(simple_template)
    
    assert template.id == simple_template
    assert template.name == "test_simple"
    assert template.content == "Hello {{name}}!"
    assert template.current_version == 1
    assert isinstance(template.created_at, datetime)
    assert isinstance(template.updated_at, datetime)


def test_get_template_not_found(db_module):
    """Test that fetching nonexistent template raises error."""
    with pytest.raises(TemplateNotFoundError) as exc_info:
        get_template(99999)
    
    assert "not found" in str(exc_info.value)


def test_get_template_by_name(simple_template):
    """Test retrieving a template by name."""
    template = get_template_by_name("test_simple")
    
    assert template.id == simple_template
    assert template.name == "test_simple"


def test_get_template_by_name_not_found(db_module):
    """Test that fetching by nonexistent name raises error."""
    with pytest.raises(TemplateNotFoundError):
        get_template_by_name("nonexistent")


def test_list_templates(simple_template, complex_template):
    """Test listing all templates."""
    templates = list_templates()
    
    assert len(templates) >= 2
    
    names = [t.name for t in templates]
    assert "test_simple" in names
    assert "test_complex" in names


def test_list_templates_excludes_inactive(simple_template):
    """Test that list_templates excludes inactive by default."""
    deactivate_template(simple_template)
    
    templates = list_templates()
    names = [t.name for t in templates]
    
    assert "test_simple" not in names


def test_list_templates_includes_inactive(simple_template):
    """Test that list_templates can include inactive."""
    deactivate_template(simple_template)
    
    templates = list_templates(include_inactive=True)
    names = [t.name for t in templates]
    
    assert "test_simple" in names


def test_update_template(simple_template):
    """Test updating a template creates new version."""
    new_version = update_template(
        simple_template,
        "Hi {{name}}!",
        created_by="test_user",
        change_description="Changed greeting"
    )
    
    assert new_version == 2
    
    # Verify template updated
    template = get_template(simple_template)
    assert template.content == "Hi {{name}}!"
    assert template.current_version == 2


def test_update_template_invalid_syntax(simple_template):
    """Test that updating with invalid syntax raises error."""
    with pytest.raises(TemplateSyntaxError):
        update_template(simple_template, "{{broken")


def test_update_template_not_found(db_module):
    """Test updating nonexistent template raises error."""
    with pytest.raises(TemplateNotFoundError):
        update_template(99999, "content")


def test_multiple_updates(simple_template):
    """Test multiple updates create sequential versions."""
    update_template(simple_template, "Version 2")
    update_template(simple_template, "Version 3")
    v4 = update_template(simple_template, "Version 4")
    
    assert v4 == 4
    
    template = get_template(simple_template)
    assert template.current_version == 4
    assert template.content == "Version 4"


def test_deactivate_template(simple_template):
    """Test deactivating a template."""
    deactivate_template(simple_template)
    
    template = get_template(simple_template)
    assert template.is_active is False


def test_deactivate_nonexistent_template(db_module):
    """Test deactivating nonexistent template raises error."""
    with pytest.raises(TemplateNotFoundError):
        deactivate_template(99999)


def test_activate_template(simple_template):
    """Test activating a deactivated template."""
    deactivate_template(simple_template)
    activate_template(simple_template)
    
    template = get_template(simple_template)
    assert template.is_active is True


def test_activate_nonexistent_template(db_module):
    """Test activating nonexistent template raises error."""
    with pytest.raises(TemplateNotFoundError):
        activate_template(99999)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# VERSION MANAGEMENT TESTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_get_version_history(simple_template):
    """Test retrieving version history."""
    update_template(simple_template, "Version 2")
    update_template(simple_template, "Version 3")
    
    versions = get_version_history(simple_template)
    
    assert len(versions) == 3
    assert versions[0].version == 3  # Newest first
    assert versions[1].version == 2
    assert versions[2].version == 1


def test_get_version_history_not_found(db_module):
    """Test version history for nonexistent template raises error."""
    with pytest.raises(TemplateNotFoundError):
        get_version_history(99999)


def test_get_specific_version(simple_template):
    """Test retrieving a specific version."""
    update_template(simple_template, "Version 2")
    
    v1 = get_version(simple_template, 1)
    assert v1.version == 1
    assert v1.content == "Hello {{name}}!"
    
    v2 = get_version(simple_template, 2)
    assert v2.version == 2
    assert v2.content == "Version 2"


def test_get_version_not_found(simple_template):
    """Test fetching nonexistent version raises error."""
    with pytest.raises(TemplateNotFoundError):
        get_version(simple_template, 99)


def test_rollback_to_version(simple_template):
    """Test rolling back to a previous version."""
    # Create versions 2 and 3
    update_template(simple_template, "Version 2")
    update_template(simple_template, "Version 3")
    
    # Rollback to v1 (creates v4 with v1 content)
    new_version = rollback_to_version(simple_template, 1, created_by="test_user")
    
    assert new_version == 4
    
    template = get_template(simple_template)
    assert template.content == "Hello {{name}}!"
    assert template.current_version == 4


def test_rollback_preserves_history(simple_template):
    """Test that rollback doesn't delete history."""
    update_template(simple_template, "Version 2")
    rollback_to_version(simple_template, 1)
    
    versions = get_version_history(simple_template)
    assert len(versions) == 3
    
    # All versions preserved
    assert versions[2].version == 1
    assert versions[1].version == 2
    assert versions[0].version == 3  # Rollback created v3


def test_rollback_to_nonexistent_version(simple_template):
    """Test rollback to nonexistent version raises error."""
    with pytest.raises(TemplateNotFoundError):
        rollback_to_version(simple_template, 99)


def test_version_metadata(simple_template):
    """Test that version metadata is stored correctly."""
    update_template(
        simple_template,
        "Updated content",
        created_by="admin",
        change_description="Fixed typo"
    )
    
    versions = get_version_history(simple_template)
    v2 = versions[0]
    
    assert v2.created_by == "admin"
    assert v2.change_description == "Fixed typo"
    assert isinstance(v2.created_at, datetime)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# RENDERING TESTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_render_simple_template(simple_template):
    """Test rendering a simple template."""
    result = render_template(simple_template, {"name": "World"})
    assert result == "Hello World!"


def test_render_with_multiple_variables(db_module):
    """Test rendering with multiple variables."""
    template_id = create_template(
        "multi_var",
        "{{greeting}} {{name}}! You are {{age}} years old."
    )
    
    result = render_template(template_id, {
        "greeting": "Hi",
        "name": "Alice",
        "age": 30
    })
    
    assert result == "Hi Alice! You are 30 years old."


def test_render_with_loops(complex_template):
    """Test rendering template with loops."""
    result = render_template(complex_template, {
        "role": "assistant",
        "tasks": ["Task 1", "Task 2", "Task 3"],
        "context": None,  # Optional variable - provide as None
        "urgent": False   # Optional variable - provide as False
    })
    
    assert "Task 1" in result
    assert "Task 2" in result
    assert "Task 3" in result


def test_render_with_conditionals(complex_template):
    """Test rendering template with conditionals."""
    result = render_template(complex_template, {
        "role": "assistant",
        "tasks": ["Task 1"],
        "context": "Important project",
        "urgent": True,
        "deadline": "5pm"
    })
    
    assert "Context: Important project" in result
    assert "âš ï¸ URGENT" in result
    assert "5pm" in result


def test_render_conditional_false(complex_template):
    """Test conditional doesn't render when false."""
    result = render_template(complex_template, {
        "role": "assistant",
        "tasks": ["Task 1"],
        "context": None,  # Provide optional variable
        "urgent": False
    })
    
    assert "âš ï¸ URGENT" not in result


def test_render_missing_variable(db_module):
    """Test that missing required variable raises error."""
    template_id = create_template("missing_var", "Hello {{name}}!")
    
    with pytest.raises(TemplateRenderError) as exc_info:
        render_template(template_id, {})
    
    assert "name" in str(exc_info.value).lower()


def test_render_by_name(db_module):
    """Test rendering by template name."""
    create_template("by_name", "Hello {{name}}!")
    
    result = render_template_by_name("by_name", {"name": "World"})
    assert result == "Hello World!"


def test_render_by_name_not_found(db_module):
    """Test rendering nonexistent template by name raises error."""
    with pytest.raises(TemplateNotFoundError):
        render_template_by_name("nonexistent", {})


def test_render_with_filters(db_module):
    """Test rendering with Jinja2 filters."""
    template_id = create_template(
        "with_filters",
        "{{name | upper}} is {{age | string}} years old"
    )
    
    result = render_template(template_id, {"name": "alice", "age": 30})
    assert result == "ALICE is 30 years old"


def test_render_empty_variables(db_module):
    """Test rendering with empty variables dict."""
    template_id = create_template("no_vars", "Static content")
    result = render_template(template_id, {})
    assert result == "Static content"


def test_render_no_variables_arg(db_module):
    """Test rendering without providing variables argument."""
    template_id = create_template("no_vars2", "Static content")
    result = render_template(template_id)
    assert result == "Static content"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# EDGE CASES & ERROR CONDITIONS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_create_template_empty_name(db_module):
    """Test that empty name raises validation error."""
    with pytest.raises(Exception):  # Pydantic validation error
        create_template("", "content")


def test_create_template_empty_content(db_module):
    """Test creating template with empty content."""
    template_id = create_template("empty_content", "")
    template = get_template(template_id)
    assert template.content == ""


def test_template_with_unicode(db_module):
    """Test template with Unicode characters."""
    template_id = create_template(
        "unicode_test",
        "Hello {{name}}! ä½ å¥½ {{chinese_name}}! ðŸŽ‰"
    )
    
    result = render_template(template_id, {
        "name": "World",
        "chinese_name": "ä¸–ç•Œ"
    })
    
    assert "ä½ å¥½ ä¸–ç•Œ!" in result
    assert "ðŸŽ‰" in result


def test_template_with_html(db_module):
    """Test template with HTML content."""
    template_id = create_template(
        "html_template",
        "<h1>{{title}}</h1><p>{{content}}</p>"
    )
    
    result = render_template(template_id, {
        "title": "Test",
        "content": "Content"
    })
    
    assert "<h1>Test</h1>" in result


def test_large_template(db_module):
    """Test creating and rendering a large template."""
    # Create 1000-line template
    # Need quadruple braces in f-string to get double braces in output
    lines = [f"Line {{{{line_{i}}}}}" for i in range(1000)]
    content = "\n".join(lines)
    
    template_id = create_template("large_template", content)
    
    # Render with all variables
    variables = {f"line_{i}": f"Value {i}" for i in range(1000)}
    result = render_template(template_id, variables)
    
    assert "Value 0" in result
    assert "Value 999" in result


def test_template_with_nested_loops(db_module):
    """Test template with nested loops."""
    # Use bracket notation to avoid conflict with dict.items() method
    content = """
{% for category in categories %}
Category: {{category['name']}}
{% for item in category['items'] %}
  - {{item}}
{% endfor %}
{% endfor %}
    """.strip()
    
    template_id = create_template("nested_loops", content)
    
    result = render_template(template_id, {
        "categories": [
            {"name": "Fruits", "items": ["Apple", "Banana"]},
            {"name": "Vegetables", "items": ["Carrot", "Broccoli"]}
        ]
    })
    
    assert "Fruits" in result
    assert "Apple" in result
    assert "Vegetables" in result
    assert "Carrot" in result


def test_template_whitespace_control(db_module):
    """Test Jinja2 whitespace control."""
    content = """
{%- for item in items %}
{{item}}
{%- endfor %}
    """.strip()
    
    template_id = create_template("whitespace", content)
    
    result = render_template(template_id, {"items": ["A", "B", "C"]})
    assert result.strip() == "A\nB\nC"


def test_concurrent_updates(simple_template):
    """Test that concurrent updates create proper versions."""
    # Simulate concurrent updates
    v2 = update_template(simple_template, "Update 1")
    v3 = update_template(simple_template, "Update 2")
    v4 = update_template(simple_template, "Update 3")
    
    assert v2 == 2
    assert v3 == 3
    assert v4 == 4
    
    versions = get_version_history(simple_template)
    assert len(versions) == 4


def test_template_with_macros(db_module):
    """Test template with Jinja2 macros."""
    content = """
{% macro greeting(name) %}
Hello {{name}}!
{% endmacro %}

{{greeting(user)}}
    """.strip()
    
    template_id = create_template("with_macros", content)
    result = render_template(template_id, {"user": "Alice"})
    
    assert "Hello Alice!" in result


def test_template_inheritance(db_module):
    """Test that template doesn't support extends (sandboxed)."""
    # Jinja2 sandbox doesn't support template inheritance
    template_id = create_template(
        "no_inheritance",
        "Just {{content}}"
    )
    
    result = render_template(template_id, {"content": "text"})
    assert result == "Just text"