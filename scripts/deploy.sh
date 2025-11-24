#!/usr/bin/env bash
set -euo pipefail

MODEL_URL="https://huggingface.co/mradermacher/Dolphin-Mistral-24B-Venice-Edition-GGUF/resolve/main/Dolphin-Mistral-24B-Venice-Edition.Q4_K_M.gguf"

echo "==> PromptDev Cloud VM Deployment"
echo "==> Model: Venice 24B (~14GB)"
echo ""

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "ERROR: Docker Compose not installed"; exit 1; }

echo "==> Starting Docker stack..."
docker compose up -d postgres

echo "==> Waiting for Postgres to be ready..."
timeout 30 bash -c 'until docker exec promptdev-postgres pg_isready -U promptdev_user 2>/dev/null; do sleep 1; done'

echo "==> Downloading Venice 24B (first time only, ~14GB)..."
docker volume create promptdev-models >/dev/null 2>&1 || true

# Download model if not exists
docker run --rm \
    -v promptdev-models:/models \
    alpine:latest \
    sh -c "
        if [ ! -f /models/venice.gguf ]; then
            apk add --no-cache wget
            echo 'Downloading Venice 24B (~14GB)...'
            echo 'This will take 10-15 minutes on cloud internet'
            echo ''
            
            for i in 1 2 3 4 5; do
                echo \"Attempt \$i of 5...\"
                if wget -c -t 3 -T 60 -O /models/venice.gguf '${MODEL_URL}'; then
                    echo 'Download complete!'
                    break
                else
                    if [ \$i -eq 5 ]; then
                        echo 'ERROR: Download failed after 5 attempts'
                        rm -f /models/venice.gguf
                        exit 1
                    fi
                    echo 'Download interrupted, retrying...'
                    sleep 5
                fi
            done
        else
            echo 'Model already exists, skipping download.'
        fi
    "

echo "==> Starting Mistral LLM and Backend with Venice 24B..."
docker compose --profile cloud up -d

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
echo "  LLM Model: Venice 24B"
echo "  Health check: curl http://localhost:8001/health"
echo ""
echo "To view logs:"
echo "  make prod-logs"
echo ""
echo "To stop:"
echo "  make prod-stop"
echo ""
