-- Fix user_activity unique constraint to match ON CONFLICT in telemetry.py
DROP INDEX IF EXISTS idx_user_activity_tenant_user;
ALTER TABLE user_activity DROP CONSTRAINT IF EXISTS user_activity_tenant_user_unique;
ALTER TABLE user_activity ADD CONSTRAINT user_activity_tenant_user_unique UNIQUE (tenant_id, user_id);

-- Fix metric_snapshots unique constraint to match ON CONFLICT in telemetry.py
ALTER TABLE metric_snapshots DROP CONSTRAINT IF EXISTS metric_snapshots_metric_name_time_window_window_start_key;
DROP INDEX IF EXISTS idx_metric_tenant_name_window;
ALTER TABLE metric_snapshots DROP CONSTRAINT IF EXISTS metric_snapshots_tenant_unique;
ALTER TABLE metric_snapshots ADD CONSTRAINT metric_snapshots_tenant_unique UNIQUE (tenant_id, metric_name, time_window, window_start);

-- Record migration
INSERT INTO schema_migrations (version) VALUES ('009') ON CONFLICT DO NOTHING;
