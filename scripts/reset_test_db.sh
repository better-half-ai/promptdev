#!/usr/bin/env bash
set -euo pipefail

DB_NAME="promptdev_test"
DB_USER="promptdev_user"

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

echo "==> Resetting test DB ${DB_NAME}..."

run_psql "REVOKE CONNECT ON DATABASE ${DB_NAME} FROM PUBLIC;" || true
run_psql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}';" || true
run_psql "DROP DATABASE IF EXISTS ${DB_NAME};"
run_psql "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

echo "==> Test DB reset COMPLETE."
