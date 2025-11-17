#!/usr/bin/env bash
set -euo pipefail

echo "==> PromptDev Cloud VM Deployment"
echo ""

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "ERROR: Docker Compose not installed"; exit 1; }
command -v make >/dev/null 2>&1 || { echo "ERROR: make not installed"; exit 1; }

# Setup .env via Makefile
make .env

echo "==> Starting Docker stack..."
docker compose up -d postgres

echo "==> Waiting for Postgres to be ready..."
timeout 30 bash -c 'until docker exec promptdev-postgres pg_isready -U promptdev_user 2>/dev/null; do sleep 1; done'

echo "==> Downloading Mistral model (first time only, ~4GB)..."
docker volume create promptdev-models >/dev/null 2>&1 || true

# Download model if not exists
docker run --rm \
    -v promptdev-models:/models \
    alpine:latest \
    sh -c '
        if [ ! -f /models/mistral.gguf ]; then
            apk add --no-cache wget
            echo "Downloading Mistral-7B-Instruct GGUF..."
            wget -O /models/mistral.gguf \
                https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf
            echo "Download complete!"
        else
            echo "Model already exists, skipping download."
        fi
    '

echo "==> Starting Mistral and Backend..."
docker compose up -d

echo "==> Waiting for backend to be ready..."
sleep 5

echo "==> Running database migrations..."
docker compose exec backend uv run python -m scripts.migrate || {
    echo "WARNING: Migrations failed. Backend may not be ready yet."
    echo "You can run migrations manually with: make db-migrate"
}

echo ""
echo "==> Deployment complete!"
echo ""
echo "Services:"
echo "  Backend API: http://localhost:8001"
echo "  Health check: curl http://localhost:8001/health"
echo ""
echo "To view logs:"
echo "  make dc-logs"
echo ""
echo "To stop:"
echo "  make dc-down"
echo ""
