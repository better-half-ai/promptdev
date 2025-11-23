SHELL := /bin/bash
PY := uv run python

help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║           PromptDev - Deployment Commands                 ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🖥️  MAC DEVELOPMENT (Native - Fastest)"
	@echo "  make dev              Quick start with Venice 24B (14GB)"
	@echo "  make dev-venice       Venice 24B - most uncensored (DEFAULT)"
	@echo "  make dev-dolphin      Dolphin 7B - fast alternative (4.4GB)"
	@echo "  make dev-mistral      Mistral 7B - baseline"
	@echo "  make dev-stop         Stop all Mac dev services"
	@echo ""
	@echo "☁️  CLOUD PRODUCTION (Docker - Ubuntu VM)"
	@echo "  make prod             Deploy with Venice 24B (14GB, DEFAULT)"
	@echo "  make prod-mistral     Deploy with Mistral 7B (4GB)"
	@echo "  make prod-stop        Stop all cloud services"
	@echo "  make prod-logs        View production logs"
	@echo ""
	@echo "🗄️  DATABASE"
	@echo "  make db-migrate       Run migrations"
	@echo "  make db-inspect       Show database tables"
	@echo "  make db-shell         Open PostgreSQL shell"
	@echo ""
	@echo "🧪 TESTING"
	@echo "  make test             Run all tests"
	@echo "  make test-verbose     Run tests with verbose output"
	@echo ""
	@echo "🔧 UTILITIES"
	@echo "  make health           Check backend health"
	@echo "  make clean            Clean Python cache files"
	@echo ""
	@echo "💡 DEFAULT SETUP:"
	@echo "  Mac Dev:  Venice 24B (14GB) - Most uncensored"
	@echo "  Cloud:    Venice 24B (14GB) - Most uncensored"
	@echo ""

# ============================================================================
# MAC DEVELOPMENT (Native llama.cpp - Apple Silicon optimized)
# ============================================================================

dev: dev-venice
	@echo "✅ Mac development environment ready!"

dev-venice:
	@echo "🖥️  Starting Mac Development with Venice 24B..."
	@echo ""
	@docker compose up -d postgres backend
	@echo "Waiting for backend..."
	@sleep 3
	@$(MAKE) db-migrate
	@echo ""
	@echo "Starting Venice 24B (native)..."
	@bash scripts/run_mistral_local.sh venice &
	@echo ""
	@echo "✅ Mac Dev Ready:"
	@echo "  Backend: http://localhost:8001"
	@echo "  LLM: http://localhost:8080"
	@echo "  Model: Venice 24B (14GB, most uncensored)"

dev-dolphin:
	@echo "🖥️  Starting Mac Development with Dolphin 7B..."
	@docker compose up -d postgres backend
	@sleep 3
	@$(MAKE) db-migrate
	@echo ""
	@echo "Starting Dolphin 7B (native, fast)..."
	@bash scripts/run_mistral_local.sh dolphin &
	@echo ""
	@echo "✅ Mac Dev Ready:"
	@echo "  Backend: http://localhost:8001"
	@echo "  LLM: http://localhost:8080"
	@echo "  Model: Dolphin 7B (4.4GB, fast alternative)"

dev-mistral:
	@echo "🖥️  Starting Mac Development with Mistral 7B..."
	@docker compose up -d postgres backend
	@sleep 3
	@$(MAKE) db-migrate
	@bash scripts/run_mistral_local.sh mistral &
	@echo "✅ Mac Dev Ready:"
	@echo "  Backend: http://localhost:8001"
	@echo "  LLM: http://localhost:8080"
	@echo "  Model: Dolphin 7B (uncensored, 4.4GB)"

dev-stop:
	@echo "Stopping Mac development services..."
	@docker compose down
	@pkill -f llama-server || true
	@echo "✅ Stopped"

# ============================================================================
# CLOUD PRODUCTION (Full Docker Stack - Ubuntu VM)
# ============================================================================

prod:
	@echo "☁️  Deploying to PRODUCTION with Venice 24B..."
	@bash deploy.sh venice

prod-mistral:
	@echo "☁️  Deploying to PRODUCTION with Mistral 7B..."
	@bash deploy.sh mistral

prod-stop:
	@echo "Stopping production services..."
	@docker compose --profile cloud down
	@echo "✅ Stopped"

prod-logs:
	@docker compose --profile cloud logs -f

prod-restart:
	@docker compose --profile cloud restart

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

db-migrate:
	@docker compose exec backend uv run python -m scripts.migrate

db-inspect:
	@echo "=== Database Tables ==="
	@docker compose exec backend uv run python -c "from scripts.inspect_db import list_tables; tables = list_tables(); print('\n'.join(tables))"

db-shell:
	@docker compose exec postgres psql -U promptdev -d promptdev

# ============================================================================
# TESTING
# ============================================================================

test:
	@uv run pytest

test-verbose:
	@uv run pytest -v

# ============================================================================
# UTILITIES
# ============================================================================

health:
	@curl -s http://localhost:8001/health || echo "❌ Backend not responding"

clean:
	@find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleaned Python cache files"

rebuild:
	@docker compose build backend
	@uv sync

.DEFAULT_GOAL := help
.PHONY: help dev dev-venice dev-mistral dev-dolphin dev-stop prod prod-mistral prod-stop prod-logs prod-restart db-migrate db-inspect db-shell test test-verbose health clean rebuild
