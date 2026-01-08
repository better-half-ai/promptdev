SHELL := /bin/bash

help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║                    PromptDev Commands                      ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🚀 RUN"
	@echo "  make run              Run with local Mistral backend"
	@echo "  make run-venice       Run with Venice.ai API backend"
	@echo "  make stop             Stop all services"
	@echo ""
	@echo "🗄️  DATABASE"
	@echo "  make db-up            Start PostgreSQL"
	@echo "  make db-migrate       Run migrations"
	@echo "  make db-inspect       Show database tables"
	@echo "  make db-shell         Open PostgreSQL shell"
	@echo ""
	@echo "🧪 TESTING"
	@echo "  make test             Run tests with local backend"
	@echo "  make test-venice      Run tests with Venice.ai API"
	@echo "  make test-verbose     Run tests verbose (local)"
	@echo ""
	@echo "🔧 UTILITIES"
	@echo "  make health           Check backend health"
	@echo "  make clean            Clean Python cache files"
	@echo ""

# ============================================================================
# RUN
# ============================================================================

run:
	@docker compose up -d postgres
	@sleep 2
	@$(MAKE) db-migrate
	@echo "Starting with local Mistral backend..."
	@LLM_BACKEND=local uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

run-venice:
	@docker compose up -d postgres
	@sleep 2
	@$(MAKE) db-migrate
	@echo "Starting with Venice.ai API backend..."
	@LLM_BACKEND=venice uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

stop:
	@docker compose down
	@pkill -f "uvicorn src.main:app" || true
	@echo "✅ Stopped"

# ============================================================================
# DATABASE
# ============================================================================

db-up:
	@docker compose up -d postgres

db-migrate:
	@uv run python -m scripts.migrate

db-inspect:
	@uv run python -c "from scripts.inspect_db import list_tables; tables = list_tables(); print('\n'.join(tables))"

db-shell:
	@docker compose exec postgres psql -U promptdev_user -d promptdev_db

# ============================================================================
# TESTING
# ============================================================================

test:
	@uv run pytest --llm=local

test-venice:
	@uv run pytest --llm=venice

test-verbose:
	@uv run pytest --llm=local -v

# ============================================================================
# UTILITIES
# ============================================================================

health:
	@curl -sf http://localhost:8000/health && echo "✅ Backend healthy" || echo "❌ Backend not responding"

clean:
	@find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleaned"

.DEFAULT_GOAL := help
.PHONY: help run run-venice stop db-up db-migrate db-inspect db-shell test test-venice test-verbose health clean
