SHELL := /bin/bash
PY := uv run python

help:
	@echo ""
	@echo "PromptDev Commands:"
	@echo ""
	@echo "  test              Run all tests"
	@echo "  local-start       Start postgres and backend"
	@echo "  local-stop        Stop all services"
	@echo "  db-migrate        Run database migrations"
	@echo "  health            Check backend health"
	@echo ""

test:
	uv run pytest

test-verbose:
	uv run pytest -v

local-start:
	docker compose up -d postgres backend

local-stop:
	docker compose down

db-migrate:
	docker compose exec backend uv run python -m scripts.migrate

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
.PHONY: help test test-verbose local-start local-stop db-migrate db-shell health logs clean
