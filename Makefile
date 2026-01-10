SHELL := /bin/bash

.DEFAULT_GOAL := help

# Validate db= is set
check-db:
ifndef db
	$(error db= is required. Use db=local or db=remote)
endif

help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║                    PromptDev Commands                      ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🚀 RUN (requires db=local|remote)"
	@echo "  make run              Run with local Mistral backend"
	@echo "  make run-venice       Run with Venice.ai API backend"
	@echo "  make stop             Stop all services"
	@echo ""
	@echo "🔌 LLM"
	@echo "  make llm              Start local LLM server"
	@echo ""
	@echo "🐳 DOCKER"
	@echo "  make db-up            Start local PostgreSQL container"
	@echo "  make db-reset         Nuke local volumes and start fresh"
	@echo ""
	@echo "🗄️  DATABASE (requires db=local|remote)"
	@echo "  make db-migrate       Run migrations"
	@echo "  make db-inspect       Show tables"
	@echo "  make db-shell         Open psql shell"
	@echo "  make db-drop-remote   Drop remote schema (destructive!)"
	@echo ""
	@echo "🔌 CONNECTION TESTS"
	@echo "  make test-db-local    Test local PostgreSQL connection"
	@echo "  make test-db-remote   Test remote Supabase connection"
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

run: check-db
ifeq ($(db),local)
	@docker compose --profile local up -d
	@sleep 3
	@$(MAKE) db-migrate db=$(db)
	@echo "✅ Backend running at http://localhost:8001 (db=$(db))"
else ifeq ($(db),remote)
	DB_TARGET=remote uv run uvicorn src.main:app --host 0.0.0.0 --port 8001
endif

run-venice: check-db
ifeq ($(db),local)
	@LLM_BACKEND=venice docker compose --profile local up -d --force-recreate
	@sleep 3
	@$(MAKE) db-migrate db=$(db)
	@echo "✅ Backend running with Venice API (db=$(db))"
else ifeq ($(db),remote)
	DB_TARGET=remote LLM_BACKEND=venice uv run uvicorn src.main:app --host 0.0.0.0 --port 8001
endif

stop:
	@docker compose --profile local down
	@echo "✅ Stopped"

# ============================================================================
# DOCKER
# ============================================================================

db-up:
	@docker compose --profile local up -d postgres

db-reset:
	@echo "🗑️  Nuking local database..."
	@docker compose --profile local down -v --remove-orphans
	@echo "🚀 Starting fresh..."
	@docker compose --profile local up -d postgres
	@sleep 3
	@echo "✅ Local database reset complete"

db-drop-remote:
	@echo "🗑️  Dropping remote schema..."
	@source .env && psql "postgresql://postgres.hykoamfsyttvteipvsbw:$$SUPABASE_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	@echo "✅ Remote database schema dropped"

# ============================================================================
# DATABASE
# ============================================================================

db-migrate: check-db
ifeq ($(db),local)
	@docker compose --profile local exec backend uv run python -m scripts.migrate
else ifeq ($(db),remote)
	@DB_TARGET=$(db) uv run python -m scripts.migrate
endif

db-inspect: check-db
ifeq ($(db),local)
	@docker compose --profile local exec backend uv run python -c "from scripts.inspect_db import list_tables; print(list_tables())"
else ifeq ($(db),remote)
	@DB_TARGET=$(db) uv run python -c "from scripts.inspect_db import list_tables; print(list_tables())"
endif

db-shell: check-db
ifeq ($(db),local)
	@docker compose --profile local exec postgres psql -U promptdev_user -d promptdev_db
else ifeq ($(db),remote)
	@source .env && psql "postgresql://postgres.hykoamfsyttvteipvsbw:$$SUPABASE_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
else
	$(error Invalid db= value. Use db=local or db=remote)
endif

# ============================================================================
# CONNECTION TESTS
# ============================================================================

test-db-local:
	@docker compose --profile local exec postgres psql -U promptdev_user -d promptdev_db -c "SELECT 1;" && echo "✅ Local connection OK" || echo "❌ Local connection failed"

test-db-remote:
	@source .env && psql "postgresql://postgres.hykoamfsyttvteipvsbw:$$SUPABASE_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres" -c "SELECT 1;" && echo "✅ Remote connection OK" || echo "❌ Remote connection failed"

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

.PHONY: help llm run run-venice stop db-up db-reset db-drop-remote db-migrate db-inspect db-shell test-db-local test-db-remote test test-local test-venice test-verbose health clean check-db
