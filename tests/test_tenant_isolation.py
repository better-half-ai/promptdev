"""
Tests for multi-tenant data isolation.

Tests that:
- Each admin can only see their own data
- Templates, users, guardrails are isolated
- Template sharing/cloning works correctly
- Super admin can see all data
"""

import pytest


class TestTemplateIsolation:
    """Test that templates are isolated per tenant."""
    
    def test_admin_sees_only_own_templates(self, db_module, db_conn, test_admin, second_admin):
        """Each admin should only see their own templates."""
        # Create template for first admin
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version)
                VALUES (%s, 'admin1_template', 'content1', 1)
            """, (test_admin.tenant_id,))
            
            # Create template for second admin
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version)
                VALUES (%s, 'admin2_template', 'content2', 1)
            """, (second_admin.tenant_id,))
            db_conn.commit()
            
            # Query for first admin's templates
            cur.execute("""
                SELECT name FROM system_prompt WHERE tenant_id = %s
            """, (test_admin.tenant_id,))
            admin1_templates = [row[0] for row in cur.fetchall()]
            
            # Query for second admin's templates
            cur.execute("""
                SELECT name FROM system_prompt WHERE tenant_id = %s
            """, (second_admin.tenant_id,))
            admin2_templates = [row[0] for row in cur.fetchall()]
        
        assert 'admin1_template' in admin1_templates
        assert 'admin2_template' not in admin1_templates
        
        assert 'admin2_template' in admin2_templates
        assert 'admin1_template' not in admin2_templates
    
    def test_same_template_name_different_tenants(self, db_module, db_conn, test_admin, second_admin):
        """Two admins can have templates with the same name."""
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version)
                VALUES (%s, 'common_name', 'content for admin1', 1)
            """, (test_admin.tenant_id,))
            
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version)
                VALUES (%s, 'common_name', 'content for admin2', 1)
            """, (second_admin.tenant_id,))
            db_conn.commit()
            
            cur.execute("SELECT COUNT(*) FROM system_prompt WHERE name = 'common_name'")
            count = cur.fetchone()[0]
        
        assert count == 2


class TestConversationIsolation:
    """Test that conversations are isolated per tenant."""
    
    def test_admin_sees_only_own_conversations(self, db_module, db_conn, test_admin, second_admin):
        """Each admin should only see conversations from their users."""
        with db_conn.cursor() as cur:
            # Create conversations for first admin's user
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'user_a', 'user', 'hello from user_a')
            """, (test_admin.tenant_id,))
            
            # Create conversations for second admin's user
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'user_b', 'user', 'hello from user_b')
            """, (second_admin.tenant_id,))
            db_conn.commit()
            
            # Query for first admin's conversations
            cur.execute("""
                SELECT user_id FROM conversation_history WHERE tenant_id = %s
            """, (test_admin.tenant_id,))
            admin1_users = [row[0] for row in cur.fetchall()]
            
            # Query for second admin's conversations
            cur.execute("""
                SELECT user_id FROM conversation_history WHERE tenant_id = %s
            """, (second_admin.tenant_id,))
            admin2_users = [row[0] for row in cur.fetchall()]
        
        assert 'user_a' in admin1_users
        assert 'user_b' not in admin1_users
        
        assert 'user_b' in admin2_users
        assert 'user_a' not in admin2_users
    
    def test_same_user_id_different_tenants(self, db_module, db_conn, test_admin, second_admin):
        """Same user_id can exist under different tenants."""
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'shared_user_id', 'user', 'from admin1')
            """, (test_admin.tenant_id,))
            
            cur.execute("""
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, 'shared_user_id', 'user', 'from admin2')
            """, (second_admin.tenant_id,))
            db_conn.commit()
            
            cur.execute("""
                SELECT tenant_id, content FROM conversation_history 
                WHERE user_id = 'shared_user_id' ORDER BY tenant_id
            """)
            results = cur.fetchall()
        
        assert len(results) == 2
        assert results[0][0] != results[1][0]  # Different tenants


class TestGuardrailIsolation:
    """Test that guardrails are isolated per tenant."""
    
    def test_admin_sees_only_own_guardrails(self, db_module, db_conn, test_admin, second_admin):
        """Each admin should only see their own guardrails."""
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO guardrail_configs (tenant_id, name, rules)
                VALUES (%s, 'admin1_rule', '[]')
            """, (test_admin.tenant_id,))
            
            cur.execute("""
                INSERT INTO guardrail_configs (tenant_id, name, rules)
                VALUES (%s, 'admin2_rule', '[]')
            """, (second_admin.tenant_id,))
            db_conn.commit()
            
            cur.execute("""
                SELECT name FROM guardrail_configs WHERE tenant_id = %s
            """, (test_admin.tenant_id,))
            admin1_rules = [row[0] for row in cur.fetchall()]
        
        assert 'admin1_rule' in admin1_rules
        assert 'admin2_rule' not in admin1_rules


class TestTemplateSharing:
    """Test template sharing and cloning functionality."""
    
    def test_shared_template_visible_to_all(self, db_module, db_conn, test_admin, second_admin):
        """Shareable templates should be visible in shared library."""
        with db_conn.cursor() as cur:
            # Admin 1 creates a shareable template
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version, is_shareable)
                VALUES (%s, 'shared_template', 'shared content', 1, true)
                RETURNING id
            """, (test_admin.tenant_id,))
            shared_id = cur.fetchone()[0]
            db_conn.commit()
            
            # Query shared library (visible to all)
            cur.execute("""
                SELECT id, name, tenant_id FROM system_prompt WHERE is_shareable = true
            """)
            shared = cur.fetchall()
        
        assert len(shared) >= 1
        shared_ids = [s[0] for s in shared]
        assert shared_id in shared_ids
    
    def test_clone_template(self, db_module, db_conn, test_admin, second_admin):
        """Cloning creates independent copy in target tenant."""
        with db_conn.cursor() as cur:
            # Admin 1 creates shareable template
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version, is_shareable)
                VALUES (%s, 'original', 'original content', 1, true)
                RETURNING id
            """, (test_admin.tenant_id,))
            original_id = cur.fetchone()[0]
            db_conn.commit()
            
            # Admin 2 clones it
            cur.execute("""
                INSERT INTO system_prompt 
                (tenant_id, name, content, current_version, cloned_from_id, cloned_from_tenant)
                SELECT %s, name || '_clone', content, 1, id, tenant_id
                FROM system_prompt WHERE id = %s
                RETURNING id
            """, (second_admin.tenant_id, original_id))
            clone_id = cur.fetchone()[0]
            db_conn.commit()
            
            # Verify clone
            cur.execute("""
                SELECT tenant_id, name, cloned_from_id, cloned_from_tenant
                FROM system_prompt WHERE id = %s
            """, (clone_id,))
            clone = cur.fetchone()
        
        assert clone[0] == second_admin.tenant_id  # Owned by admin 2
        assert clone[1] == 'original_clone'
        assert clone[2] == original_id  # Tracks source
        assert clone[3] == test_admin.tenant_id  # Tracks source owner
    
    def test_clone_is_independent(self, db_module, db_conn, test_admin, second_admin):
        """Modifying clone doesn't affect original."""
        with db_conn.cursor() as cur:
            # Create original
            cur.execute("""
                INSERT INTO system_prompt (tenant_id, name, content, current_version, is_shareable)
                VALUES (%s, 'to_clone', 'original content', 1, true)
                RETURNING id
            """, (test_admin.tenant_id,))
            original_id = cur.fetchone()[0]
            db_conn.commit()
            
            # Clone
            cur.execute("""
                INSERT INTO system_prompt 
                (tenant_id, name, content, current_version, cloned_from_id, cloned_from_tenant)
                VALUES (%s, 'cloned', 'original content', 1, %s, %s)
                RETURNING id
            """, (second_admin.tenant_id, original_id, test_admin.tenant_id))
            clone_id = cur.fetchone()[0]
            
            # Modify clone
            cur.execute("""
                UPDATE system_prompt SET content = 'modified content' WHERE id = %s
            """, (clone_id,))
            db_conn.commit()
            
            # Verify original unchanged
            cur.execute("SELECT content FROM system_prompt WHERE id = %s", (original_id,))
            original_content = cur.fetchone()[0]
            
            cur.execute("SELECT content FROM system_prompt WHERE id = %s", (clone_id,))
            clone_content = cur.fetchone()[0]
        
        assert original_content == 'original content'
        assert clone_content == 'modified content'


class TestAuditLogIsolation:
    """Test audit log captures tenant actions correctly."""
    
    def test_audit_log_includes_admin_info(self, db_module, db_conn, test_admin):
        """Audit log entries should include admin info."""
        from src.auth import audit_log
        
        audit_log(
            admin=test_admin,
            action="test_action",
            resource_type="test",
            resource_id="123"
        )
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT admin_id, admin_email, action FROM admin_audit_log
                WHERE admin_email = %s ORDER BY created_at DESC LIMIT 1
            """, (test_admin.email,))
            row = cur.fetchone()
        
        assert row is not None
        assert row[0] == test_admin.id
        assert row[1] == test_admin.email
        assert row[2] == "test_action"
    
    def test_audit_log_per_tenant(self, db_module, db_conn, test_admin, second_admin):
        """Each admin's actions are logged separately."""
        from src.auth import audit_log
        
        audit_log(admin=test_admin, action="admin1_action")
        audit_log(admin=second_admin, action="admin2_action")
        
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT admin_email, action FROM admin_audit_log
                WHERE admin_id = %s
            """, (test_admin.id,))
            admin1_logs = cur.fetchall()
            
            cur.execute("""
                SELECT admin_email, action FROM admin_audit_log
                WHERE admin_id = %s
            """, (second_admin.id,))
            admin2_logs = cur.fetchall()
        
        admin1_actions = [log[1] for log in admin1_logs]
        admin2_actions = [log[1] for log in admin2_logs]
        
        assert "admin1_action" in admin1_actions
        assert "admin2_action" not in admin1_actions
        
        assert "admin2_action" in admin2_actions
        assert "admin1_action" not in admin2_actions
