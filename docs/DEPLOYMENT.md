# PromptDev Cloud VM Deployment Guide

## Prerequisites

**VM Requirements:**
- Ubuntu 22.04 LTS or newer
- 8 vCPUs, 32GB RAM (minimum: 4 vCPU, 16GB)
- 50GB disk space
- Docker Engine 24.0+
- Docker Compose v2.20+

## Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/your-org/ybh-promptdev.git
cd ybh-promptdev
```

### 2. Deploy
```bash
chmod +x deploy.sh
./deploy.sh
```

That's it! The script will:
- Generate secure passwords (or use your .env)
- Start Postgres
- Download Mistral model (~4GB, first time only)
- Start all services
- Run database migrations

### 3. Verify
```bash
curl http://localhost:8001/health
# Should return: {"status":"ok"}
```

## Manual Deployment

If you prefer manual control:

### 1. Setup Environment
```bash
cp .env.example .env
# Edit .env and set secure passwords:
# - PROMPTDEV_USER_PASS
# - PROMPTDEV_TEST_USER_PASS
```

### 2. Download Model
```bash
docker volume create promptdev-models

docker run --rm -v promptdev-models:/models alpine:latest sh -c '
  apk add --no-cache wget &&
  wget -O /models/mistral.gguf \
    https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf
'
```

### 3. Start Services
```bash
docker compose up -d
```

### 4. Run Migrations
```bash
docker compose exec backend uv run python -m scripts.migrate
```

## Architecture

**Docker Compose Stack:**
```
┌─────────────────────────────────────┐
│  promptdev-postgres                 │
│  - Port: Internal only (5432)       │
│  - Volume: promptdev-pgdata         │
│  - Network: promptdev-net           │
└─────────────────────────────────────┘
           ↑
┌─────────────────────────────────────┐
│  promptdev-mistral                  │
│  - Port: Internal only (8080)       │
│  - Volume: promptdev-models (4GB)   │
│  - Network: promptdev-net           │
└─────────────────────────────────────┘
           ↑
┌─────────────────────────────────────┐
│  promptdev-backend                  │
│  - Port: 8001 (exposed to host)     │
│  - Network: promptdev-net           │
└─────────────────────────────────────┘
```

**Key Security Features:**
- Postgres not exposed to host (internal network only)
- Mistral not exposed to host (internal network only)
- Only backend API exposed on :8001
- Passwords from .env (not hardcoded)
- Named volumes (managed by Docker)

## Operations

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f mistral
docker compose logs -f postgres
```

### Restart Services
```bash
docker compose restart backend
docker compose restart mistral
```

### Stop Everything
```bash
docker compose down
```

### Cleanup (Including Data)
```bash
docker compose down -v  # WARNING: Deletes all data!
```

### Run Tests
```bash
docker compose exec backend make test
```

### Database Access
```bash
# Connect to DB
docker compose exec postgres psql -U promptdev_user -d promptdev_db

# Backup
docker compose exec postgres pg_dump -U promptdev_user promptdev_db > backup.sql

# Restore
cat backup.sql | docker compose exec -T postgres psql -U promptdev_user -d promptdev_db
```

## Troubleshooting

### Model Download Failed
```bash
# Retry download manually
docker run --rm -v promptdev-models:/models alpine:latest sh -c 'rm -f /models/mistral.gguf'
./deploy.sh
```

### Backend Can't Connect to Postgres
```bash
# Check network
docker network inspect promptdev-net

# Verify postgres is healthy
docker compose ps postgres

# Check logs
docker compose logs postgres
```

### Mistral Not Responding
```bash
# Check if model exists
docker run --rm -v promptdev-models:/models alpine:latest ls -lh /models/

# Check logs
docker compose logs mistral

# Restart
docker compose restart mistral
```

## Performance Tuning

### For Production VMs (32GB+ RAM):
Edit `docker-compose.yml`:
```yaml
mistral:
  command: >
    --model /models/mistral.gguf
    --host 0.0.0.0
    --port 8080
    --threads 8          # Increase threads
    --ctx-size 8192      # Larger context window
    --n-gpu-layers 0     # CPU-only
```

### For Smaller VMs (16GB RAM):
```yaml
mistral:
  deploy:
    resources:
      limits:
        memory: 8G       # Reduce memory limit
```

## Next Steps

1. **Implement Core Modules** (see backend implementation guide)
2. **Build UI** (chat, editor, inspector)
3. **Setup Monitoring** (add Prometheus/Grafana if needed)
4. **Configure Firewall** (restrict :8001 access)
5. **Add HTTPS** (nginx reverse proxy + Let's Encrypt)

## Files Updated

Replace these files in your repo:
- `docker-compose.yml` - Complete isolated stack
- `config.toml` - Updated hostnames for Docker network
- `.env.example` - Template for secrets
- `deploy.sh` - Automated deployment script
