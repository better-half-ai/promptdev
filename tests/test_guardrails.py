"""
Comprehensive test suite for guardrails.py

Covers:
- CRUD operations for guardrail configs
- Preset configurations
- Apply guardrails logic
- Rule validation
- Error conditions
- Edge cases
- Real database operations (no mocks)
"""

import pytest
import psycopg2
import os
from pathlib import Path

from src.guardrails import (
    # CRUD functions
    create_config,
    get_config,
    get_config_by_id,
    list_configs,
    update_config,
    delete_config,
    # Apply functions
    apply_guardrails,
    get_preset_names,
    validate_rules,
    # Models
    GuardrailConfig,
    # Errors
    GuardrailError,
    GuardrailNotFoundError,
    InvalidRulesError,
)


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def db_connection(db_module):
    """Use db_module from conftest, cleanup test configs after each test."""
    yield db_module
    
    # Cleanup: delete non-preset configs, reset presets
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    try:
        with conn.cursor() as cur:
            # Delete non-preset configs
            cur.execute("DELETE FROM guardrail_configs WHERE created_by IS NULL OR created_by != 'system'")
            # Reset presets to original state
            cur.execute("UPDATE guardrail_configs SET is_active = true WHERE created_by = 'system'")
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# PRESET CONFIGURATION TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_presets_exist(db_connection):
    """Test that preset configurations were created by migration."""
    presets = get_preset_names()
    
    assert "unrestricted" in presets
    assert "research_safe" in presets
    assert "clinical" in presets


def test_get_preset_unrestricted(db_connection):
    """Test getting unrestricted preset."""
    config = get_config("unrestricted")
    
    assert config.name == "unrestricted"
    assert config.is_active is True
    assert len(config.rules) == 0  # unrestricted has no rules


def test_get_preset_research_safe(db_connection):
    """Test getting research_safe preset."""
    config = get_config("research_safe")
    
    assert config.name == "research_safe"
    assert config.is_active is True
    assert len(config.rules) > 0


def test_get_preset_clinical(db_connection):
    """Test getting clinical preset."""
    config = get_config("clinical")
    
    assert config.name == "clinical"
    assert config.is_active is True
    assert len(config.rules) > 0


def test_list_configs_includes_presets(db_connection):
    """Test that list_configs includes preset configurations."""
    configs = list_configs()
    config_names = [c.name for c in configs]
    
    assert "unrestricted" in config_names
    assert "research_safe" in config_names
    assert "clinical" in config_names


# ═══════════════════════════════════════════════════════════════════════
# CREATE CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_create_config_simple(db_connection):
    """Test creating a simple guardrail config."""
    rules = [
        {
            "type": "system_instruction",
            "content": "Test instruction"
        }
    ]
    
    config_id = create_config("test_config", rules, "Test description", "test_user")
    
    assert isinstance(config_id, int)
    assert config_id > 0


def test_create_config_with_priority(db_connection):
    """Test creating config with priority rules."""
    rules = [
        {
            "type": "system_instruction",
            "priority": 1,
            "content": "High priority instruction"
        },
        {
            "type": "system_instruction",
            "priority": 0,
            "content": "Low priority instruction"
        }
    ]
    
    config_id = create_config("priority_config", rules)
    config = get_config_by_id(config_id)
    
    assert len(config.rules) == 2


def test_create_config_empty_rules(db_connection):
    """Test creating config with empty rules list."""
    config_id = create_config("empty_rules", [])
    config = get_config_by_id(config_id)
    
    assert config.rules == []


def test_create_config_invalid_rules_not_list(db_connection):
    """Test that non-list rules raise error."""
    with pytest.raises(InvalidRulesError) as exc_info:
        create_config("bad_config", {"not": "a list"})
    
    assert "must be a list" in str(exc_info.value)


def test_create_config_invalid_rule_not_dict(db_connection):
    """Test that non-dict rule raises error."""
    with pytest.raises(InvalidRulesError):
        create_config("bad_config", ["not a dict"])


def test_create_config_invalid_rule_missing_type(db_connection):
    """Test that rule without type raises error."""
    with pytest.raises(InvalidRulesError) as exc_info:
        create_config("bad_config", [{"content": "missing type"}])
    
    assert "must have a 'type' field" in str(exc_info.value)


def test_create_config_duplicate_name(db_connection):
    """Test that duplicate config name fails."""
    rules = [{"type": "test"}]
    
    create_config("duplicate", rules)
    
    with pytest.raises(GuardrailError):
        create_config("duplicate", rules)


# ═══════════════════════════════════════════════════════════════════════
# GET CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_get_config_by_name(db_connection):
    """Test getting config by name."""
    rules = [{"type": "test", "content": "Test"}]
    config_id = create_config("get_test", rules, "Description")
    
    config = get_config("get_test")
    
    assert config.id == config_id
    assert config.name == "get_test"
    assert config.description == "Description"
    assert config.rules == rules
    assert config.is_active is True


def test_get_config_by_id(db_connection):
    """Test getting config by ID."""
    rules = [{"type": "test"}]
    config_id = create_config("id_test", rules)
    
    config = get_config_by_id(config_id)
    
    assert config.id == config_id
    assert config.name == "id_test"


def test_get_config_not_found(db_connection):
    """Test getting nonexistent config raises error."""
    with pytest.raises(GuardrailNotFoundError) as exc_info:
        get_config("nonexistent")
    
    assert "not found" in str(exc_info.value)


def test_get_config_by_id_not_found(db_connection):
    """Test getting nonexistent ID raises error."""
    with pytest.raises(GuardrailNotFoundError):
        get_config_by_id(999999)


def test_get_config_inactive_not_returned(db_connection):
    """Test that inactive configs are not returned by name."""
    rules = [{"type": "test"}]
    config_id = create_config("inactive_test", rules)
    
    # Deactivate
    update_config(config_id, is_active=False)
    
    # Should not be found by name
    with pytest.raises(GuardrailNotFoundError):
        get_config("inactive_test")
    
    # But should be found by ID
    config = get_config_by_id(config_id)
    assert config.is_active is False


# ═══════════════════════════════════════════════════════════════════════
# LIST CONFIGS TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_list_configs_default(db_connection):
    """Test listing configs returns only active."""
    # Create some configs
    create_config("active1", [{"type": "test"}])
    config_id = create_config("active2", [{"type": "test"}])
    
    # Deactivate one
    update_config(config_id, is_active=False)
    
    configs = list_configs()
    config_names = [c.name for c in configs]
    
    assert "active1" in config_names
    assert "active2" not in config_names


def test_list_configs_include_inactive(db_connection):
    """Test listing configs with inactive included."""
    config_id = create_config("inactive", [{"type": "test"}])
    update_config(config_id, is_active=False)
    
    configs = list_configs(include_inactive=True)
    config_names = [c.name for c in configs]
    
    assert "inactive" in config_names


def test_list_configs_sorted_by_name(db_connection):
    """Test that configs are sorted alphabetically."""
    create_config("zebra", [{"type": "test"}])
    create_config("apple", [{"type": "test"}])
    
    configs = list_configs()
    
    # Should be sorted (presets + new ones)
    names = [c.name for c in configs]
    assert names == sorted(names)


def test_list_configs_empty_when_all_inactive(db_connection):
    """Test listing when all non-preset configs are inactive."""
    # Clean up any non-system configs first
    import src.guardrails as gm
    conn = gm.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM guardrail_configs WHERE created_by IS NULL OR created_by != 'system'")
        conn.commit()
    finally:
        gm.put_conn(conn)
    
    # Deactivate all presets
    for name in ["unrestricted", "research_safe", "clinical"]:
        config = get_config(name)
        update_config(config.id, is_active=False)
    
    configs = list_configs()
    
    # Should be empty (all presets deactivated, no custom configs)
    assert len(configs) == 0


# ═══════════════════════════════════════════════════════════════════════
# UPDATE CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_update_config_rules(db_connection):
    """Test updating config rules."""
    rules = [{"type": "test", "content": "Original"}]
    config_id = create_config("update_test", rules)
    
    new_rules = [{"type": "test", "content": "Updated"}]
    update_config(config_id, rules=new_rules)
    
    config = get_config_by_id(config_id)
    assert config.rules == new_rules


def test_update_config_description(db_connection):
    """Test updating config description."""
    config_id = create_config("desc_test", [{"type": "test"}], "Original")
    
    update_config(config_id, description="Updated description")
    
    config = get_config_by_id(config_id)
    assert config.description == "Updated description"


def test_update_config_is_active(db_connection):
    """Test updating config active status."""
    config_id = create_config("active_test", [{"type": "test"}])
    
    update_config(config_id, is_active=False)
    
    config = get_config_by_id(config_id)
    assert config.is_active is False


def test_update_config_multiple_fields(db_connection):
    """Test updating multiple fields at once."""
    config_id = create_config("multi_test", [{"type": "test"}], "Original")
    
    new_rules = [{"type": "updated"}]
    update_config(config_id, rules=new_rules, description="New desc", is_active=False)
    
    config = get_config_by_id(config_id)
    assert config.rules == new_rules
    assert config.description == "New desc"
    assert config.is_active is False


def test_update_config_not_found(db_connection):
    """Test updating nonexistent config raises error."""
    with pytest.raises(GuardrailNotFoundError):
        update_config(999999, rules=[{"type": "test"}])


def test_update_config_invalid_rules(db_connection):
    """Test updating with invalid rules raises error."""
    config_id = create_config("invalid_update", [{"type": "test"}])
    
    with pytest.raises(InvalidRulesError):
        update_config(config_id, rules="not a list")


def test_update_config_no_changes(db_connection):
    """Test update with no changes succeeds."""
    config_id = create_config("no_change", [{"type": "test"}])
    
    # Should not raise error
    update_config(config_id)


# ═══════════════════════════════════════════════════════════════════════
# DELETE CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_delete_config_soft(db_connection):
    """Test soft delete (mark inactive)."""
    config_id = create_config("soft_delete", [{"type": "test"}])
    
    delete_config(config_id, soft=True)
    
    # Should still exist but inactive
    config = get_config_by_id(config_id)
    assert config.is_active is False


def test_delete_config_hard(db_connection):
    """Test hard delete (remove from DB)."""
    config_id = create_config("hard_delete", [{"type": "test"}])
    
    delete_config(config_id, soft=False)
    
    # Should not exist
    with pytest.raises(GuardrailNotFoundError):
        get_config_by_id(config_id)


def test_delete_config_not_found(db_connection):
    """Test deleting nonexistent config raises error."""
    with pytest.raises(GuardrailNotFoundError):
        delete_config(999999)


def test_delete_config_default_soft(db_connection):
    """Test that delete defaults to soft."""
    config_id = create_config("default_delete", [{"type": "test"}])
    
    delete_config(config_id)  # No soft parameter
    
    # Should still exist but inactive
    config = get_config_by_id(config_id)
    assert config.is_active is False


# ═══════════════════════════════════════════════════════════════════════
# APPLY GUARDRAILS TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_apply_guardrails_basic(db_connection):
    """Test applying guardrails to prompt."""
    rules = [
        {
            "type": "system_instruction",
            "content": "Guardrail instruction"
        }
    ]
    create_config("apply_test", rules)
    
    base_prompt = "You are a helpful assistant."
    result = apply_guardrails(base_prompt, "apply_test")
    
    assert "Guardrail instruction" in result
    assert "You are a helpful assistant." in result
    assert result.startswith("Guardrail instruction")


def test_apply_guardrails_multiple_rules(db_connection):
    """Test applying multiple guardrail rules."""
    rules = [
        {
            "type": "system_instruction",
            "priority": 2,
            "content": "First instruction"
        },
        {
            "type": "system_instruction",
            "priority": 1,
            "content": "Second instruction"
        }
    ]
    create_config("multi_apply", rules)
    
    base_prompt = "Original prompt"
    result = apply_guardrails(base_prompt, "multi_apply")
    
    # Should have both instructions
    assert "First instruction" in result
    assert "Second instruction" in result
    assert "Original prompt" in result
    
    # Higher priority should come first
    first_pos = result.index("First instruction")
    second_pos = result.index("Second instruction")
    assert first_pos < second_pos


def test_apply_guardrails_empty_rules(db_connection):
    """Test applying config with no rules."""
    create_config("empty_apply", [])
    
    base_prompt = "Original prompt"
    result = apply_guardrails(base_prompt, "empty_apply")
    
    # Should return unchanged
    assert result == base_prompt


def test_apply_guardrails_preset_unrestricted(db_connection):
    """Test applying unrestricted preset."""
    base_prompt = "You are helpful."
    result = apply_guardrails(base_prompt, "unrestricted")
    
    # unrestricted has no rules, so prompt unchanged
    assert result == base_prompt


def test_apply_guardrails_preset_research_safe(db_connection):
    """Test applying research_safe preset."""
    base_prompt = "You are helpful."
    result = apply_guardrails(base_prompt, "research_safe")
    
    assert "You are helpful." in result


def test_apply_guardrails_preset_clinical(db_connection):
    """Test applying clinical preset."""
    base_prompt = "You are helpful."
    result = apply_guardrails(base_prompt, "clinical")
    
    assert "You are helpful." in result


def test_apply_guardrails_config_not_found(db_connection):
    """Test applying nonexistent config raises error."""
    with pytest.raises(GuardrailNotFoundError):
        apply_guardrails("Test prompt", "nonexistent")


def test_apply_guardrails_non_instruction_rules_ignored(db_connection):
    """Test that non-system_instruction rules are ignored."""
    rules = [
        {
            "type": "other_type",
            "content": "Should be ignored"
        },
        {
            "type": "system_instruction",
            "content": "Should be included"
        }
    ]
    create_config("mixed_types", rules)
    
    result = apply_guardrails("Base", "mixed_types")
    
    assert "Should be included" in result
    assert "Should be ignored" not in result


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_validate_rules_valid(db_connection):
    """Test validating valid rules."""
    rules = [
        {"type": "test", "content": "Valid"},
        {"type": "another", "priority": 1}
    ]
    
    assert validate_rules(rules) is True


def test_validate_rules_invalid_not_list(db_connection):
    """Test validating non-list rules."""
    with pytest.raises(InvalidRulesError):
        validate_rules({"not": "a list"})


def test_validate_rules_invalid_not_dict(db_connection):
    """Test validating rules with non-dict items."""
    with pytest.raises(InvalidRulesError):
        validate_rules(["not a dict"])


def test_validate_rules_missing_type(db_connection):
    """Test validating rules without type."""
    with pytest.raises(InvalidRulesError):
        validate_rules([{"content": "no type"}])


def test_validate_rules_empty_list(db_connection):
    """Test validating empty rules list."""
    assert validate_rules([]) is True


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASES & ERROR CONDITIONS
# ═══════════════════════════════════════════════════════════════════════

def test_config_with_unicode(db_connection):
    """Test config with Unicode characters."""
    rules = [
        {
            "type": "system_instruction",
            "content": "世界你好 🎉 Привет مرحبا"
        }
    ]
    
    config_id = create_config("unicode_test", rules, "Unicode 描述")
    config = get_config_by_id(config_id)
    
    assert config.rules[0]["content"] == "世界你好 🎉 Привет مرحبا"
    assert config.description == "Unicode 描述"


def test_config_with_large_rules(db_connection):
    """Test config with many rules."""
    rules = [
        {"type": "system_instruction", "content": f"Rule {i}"}
        for i in range(50)
    ]
    
    config_id = create_config("large_rules", rules)
    config = get_config_by_id(config_id)
    
    assert len(config.rules) == 50


def test_config_with_nested_rule_data(db_connection):
    """Test rules with nested data structures."""
    rules = [
        {
            "type": "system_instruction",
            "content": "Test",
            "metadata": {
                "author": "test",
                "tags": ["tag1", "tag2"],
                "nested": {"deep": "value"}
            }
        }
    ]
    
    config_id = create_config("nested_test", rules)
    config = get_config_by_id(config_id)
    
    assert config.rules[0]["metadata"]["nested"]["deep"] == "value"


def test_guardrail_model_attributes(db_connection):
    """Test GuardrailConfig model has all expected attributes."""
    rules = [{"type": "test"}]
    config_id = create_config("model_test", rules, "Description", "creator")
    
    config = get_config_by_id(config_id)
    
    assert isinstance(config, GuardrailConfig)
    assert hasattr(config, "id")
    assert hasattr(config, "name")
    assert hasattr(config, "description")
    assert hasattr(config, "rules")
    assert hasattr(config, "created_at")
    assert hasattr(config, "updated_at")
    assert hasattr(config, "created_by")
    assert hasattr(config, "is_active")


def test_apply_with_empty_base_prompt(db_connection):
    """Test applying guardrails to empty prompt."""
    rules = [{"type": "system_instruction", "content": "Instruction"}]
    create_config("empty_base", rules)
    
    result = apply_guardrails("", "empty_base")
    
    assert "Instruction" in result


def test_multiple_configs_isolation(db_connection):
    """Test that multiple configs don't interfere."""
    rules1 = [{"type": "system_instruction", "content": "Config 1"}]
    rules2 = [{"type": "system_instruction", "content": "Config 2"}]
    
    create_config("config1", rules1)
    create_config("config2", rules2)
    
    result1 = apply_guardrails("Base", "config1")
    result2 = apply_guardrails("Base", "config2")
    
    assert "Config 1" in result1
    assert "Config 1" not in result2
    assert "Config 2" in result2
    assert "Config 2" not in result1


def test_verify_real_database(db_connection):
    """Verification test: Prove we're using real database."""
    import psycopg2, os
    
    # Create config via our function
    rules = [{"type": "verify", "content": "Real data"}]
    config_id = create_config("verify_db", rules, "Verification")
    
    # Connect DIRECTLY to database
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    cur = conn.cursor()
    
    # Query database directly
    cur.execute(
        "SELECT name, description, rules FROM guardrail_configs WHERE id = %s",
        (config_id,)
    )
    row = cur.fetchone()
    
    # Verify data persisted to REAL database
    assert row[0] == "verify_db"
    assert row[1] == "Verification"
    assert row[2][0]["content"] == "Real data"
    
    cur.close()
    conn.close()
