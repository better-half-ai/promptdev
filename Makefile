SHELL := /bin/bash
PY := uv run python

help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║                    PromptDev Commands                      ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🖥️  DEVELOPMENT"
	@echo "  make dev              Start backend + local Mistral"
	@echo "  make dev-stop         Stop all dev services"
	@echo ""
	@echo "🗄️  DATABASE"
	@echo "  make db-migrate       Run migrations"
	@echo "  make db-inspect       Show database tables"
	@echo "  make db-shell         Open PostgreSQL shell"
	@echo ""
	@echo "🧪 TESTING"
	@echo "  make test-local       Run tests with local Mistral"
	@echo "  make test-venice      Run tests with Venice.ai API"
	@echo "  make test-verbose     Run tests verbose (default: local)"
	@echo ""
	@echo "🔧 UTILITIES"
	@echo "  make health           Check backend health"
	@echo "  make clean            Clean Python cache files"
	@echo ""

# ============================================================================
# DEVELOPMENT
# ============================================================================

dev:
	@echo "🖥️  Starting development..."
	@docker compose up -d postgres backend
	@echo "Waiting for backend..."
	@sleep 3
	@$(MAKE) db-migrate
	@echo ""
	@echo "Starting local Mistral..."
	@bash scripts/run_mistral_local.sh &
	@echo ""
	@echo "✅ Dev Ready:"
	@echo "  Backend: http://localhost:8001"
	@echo "  LLM: http://localhost:8080"

dev-stop:
	@echo "Stopping dev services..."
	@docker compose down
	@pkill -f llama-server || true
	@echo "✅ Stopped"

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

LLM ?= local

test:
	@uv run pytest --llm=$(LLM)

test-verbose:
	@uv run pytest -v --llm=$(LLM)

test-local:
	@uv run pytest --llm=local

test-venice:
	@uv run pytest --llm=venice

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
.PHONY: help dev dev-stop db-migrate db-inspect db-shell test test-verbose test-local test-venice health clean rebuild
