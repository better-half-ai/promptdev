#!/usr/bin/env bash
set -euo pipefail

DB_NAME="promptdev_test"
DB_USER="promptdev_user"
DB_PASS="promptdev_pass"

echo "==> Locating running Postgres container..."
CONTAINER=$(docker ps --format "{{.ID}} {{.Image}}" | grep -i postgres | awk '{print $1}')

if [ -z "$CONTAINER" ]; then
    echo "ERROR: No running Postgres container found. Start docker-compose first:"
    echo "  docker compose up -d"
    exit 1
fi

echo "==> Using Postgres container: $CONTAINER"

run_psql() {
    docker exec -i "$CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 -c "$1"
}

echo "==> Creating user ${DB_USER} if missing..."
run_psql "DO \$\$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}') THEN
        CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
    END IF;
END \$\$;"

echo "==> Creating database ${DB_NAME} if missing..."
run_psql "DO \$\$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='${DB_NAME}') THEN
        CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};
    END IF;
END \$\$;"

echo "==> Granting privileges..."
run_psql "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

echo "==> Test database setup COMPLETE (no password prompt, docker-only)."
