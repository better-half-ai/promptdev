SHELL := /bin/bash

.DEFAULT_GOAL := help

help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║                    PromptDev Commands                      ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🚀 RUN"
	@echo "  make llm              Start local LLM server"
	@echo "  make run              Run with local Mistral backend"
	@echo "  make run-venice       Run with Venice.ai API backend"
	@echo "  make stop             Stop all services"
	@echo ""
	@echo "🗄️  DATABASE"
	@echo "  make db-up            Start PostgreSQL"
	@echo "  make db-migrate       Run migrations"
	@echo "  make db-reset         Nuke volumes and start fresh"
	@echo "  make db-inspect       Show database tables"
	@echo "  make db-shell         Open PostgreSQL shell"
	@echo ""
	@echo "🧪 TESTING"
	@echo "  make test             Run tests (LLM tests skipped)"
	@echo "  make test-local       Run tests with local LLM"
	@echo "  make test-venice      Run tests with Venice.ai API"
	@echo "  make test-verbose     Run tests verbose"
	@echo ""
	@echo "🔧 UTILITIES"
	@echo "  make health           Check backend health"
	@echo "  make clean            Clean Python cache files"
	@echo ""

# ============================================================================
# RUN
# ============================================================================

llm:
	@./scripts/run_mistral_local.sh

run:
	@docker compose up -d postgres backend
	@sleep 3
	@$(MAKE) db-migrate
	@echo "✅ Backend running at http://localhost:8001"

run-venice:
	@LLM_BACKEND=venice docker compose up -d postgres backend
	@sleep 3
	@$(MAKE) db-migrate
	@echo "✅ Backend running with Venice API"

stop:
	@docker compose down
	@echo "✅ Stopped"

# ============================================================================
# DATABASE
# ============================================================================

db-up:
	@docker compose up -d postgres backend

db-migrate:
	@docker compose exec backend uv run python -m scripts.migrate

db-reset:
	@echo "🗑️  Nuking database..."
	@docker compose down -v --remove-orphans
	@echo "🚀 Starting fresh..."
	@docker compose up -d postgres backend
	@sleep 3
	@$(MAKE) db-migrate
	@echo "✅ Database reset complete"

db-inspect:
	@docker compose exec backend uv run python -c "from scripts.inspect_db import list_tables; list_tables()"

db-shell:
	@docker compose exec postgres psql -U promptdev_user -d promptdev_db

# ============================================================================
# TESTING
# ============================================================================

test:
	@uv run pytest

test-local:
	@uv run pytest --llm=local

test-venice:
	@uv run pytest --llm=venice

test-verbose:
	@uv run pytest -v

# ============================================================================
# UTILITIES
# ============================================================================

health:
	@curl -sf http://localhost:8001/health && echo "✅ Backend healthy" || echo "❌ Backend not responding"

clean:
	@find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleaned"

.PHONY: help llm run run-venice stop db-up db-migrate db-reset db-inspect db-shell test test-local test-venice test-verbose health clean
