SHELL := /bin/bash
PY := uv run python

help:
	@echo ""
	@echo "PromptDev Commands:"
	@echo ""
	@echo "  deploy            Full deployment (build, start, migrate)"
	@echo "  rebuild           Rebuild containers with new dependencies"
	@echo "  test              Run all tests"
	@echo "  local-start       Start postgres and backend"
	@echo "  local-mistral     Start Mistral locally (Mac)"
	@echo "  local-stop        Stop all services"
	@echo "  db-migrate        Run database migrations"
	@echo "  db-inspect        Show database tables"
	@echo "  health            Check backend health"
	@echo ""

deploy: rebuild local-start db-migrate
	@echo "✓ Deployment complete"

rebuild:
	docker compose build backend
	uv sync

test:
	uv run pytest

test-verbose:
	uv run pytest -v

local-start:
	docker compose up -d postgres backend

local-mistral:
	bash scripts/run_mistral_local.sh

local-stop:
	docker compose down

db-migrate:
	docker compose exec backend uv run python scripts/migrate.py

db-inspect:
	@echo "=== Database Tables ==="
	@docker compose exec backend uv run python -c "from scripts.inspect_db import list_tables; tables = list_tables(); print('\n'.join(tables))"

db-shell:
	docker compose exec postgres psql -U promptdev_user -d promptdev_db

health:
	@curl -s http://localhost:8001/health || echo "Backend not responding"

logs:
	docker compose logs -f

clean:
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

.DEFAULT_GOAL := help
.PHONY: help deploy rebuild test test-verbose local-start local-mistral local-stop db-migrate db-inspect db-shell health logs clean
