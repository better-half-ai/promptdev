-- Drop the test database if it exists (safe: only affects PromptDev test DB)
DROP DATABASE IF EXISTS promptdev_test;

-- Create a fresh test database owned by the PromptDev user
CREATE DATABASE promptdev_test
    OWNER promptdev_user;

-- Ensure privileges are correct
GRANT ALL PRIVILEGES ON DATABASE promptdev_test TO promptdev_user;

-- Optional: verify ownership (harmless)
ALTER DATABASE promptdev_test OWNER TO promptdev_user;
