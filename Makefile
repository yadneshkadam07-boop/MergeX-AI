# MergeX AI task runner (Linux/macOS/CI).
# Windows: use the equivalent `scripts/dev.ps1 <task>`.
.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---- Setup -----------------------------------------------------------------
.PHONY: setup
setup: setup-backend setup-frontend ## Install everything (venv + node_modules)

.PHONY: setup-backend
setup-backend: ## Create backend venv and install dev dependencies
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip setuptools wheel
	cd backend && ../$(PIP) install -e ".[dev]"

.PHONY: setup-frontend
setup-frontend: ## Install frontend dependencies
	npm --prefix frontend install

.PHONY: hooks
hooks: ## Install git pre-commit hooks
	$(PY) -m pre_commit install

# ---- Run -------------------------------------------------------------------
.PHONY: up
up: ## Start the full stack in Docker (db + backend + frontend)
	docker compose up --build

.PHONY: down
down: ## Stop the stack
	docker compose down

.PHONY: clean-volumes
clean-volumes: ## Stop the stack and delete the database volume
	docker compose down --volumes

.PHONY: api
api: ## Run the backend locally with reload
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

.PHONY: web
web: ## Run the frontend dev server
	npm --prefix frontend run dev

# ---- Quality ---------------------------------------------------------------
.PHONY: check
check: lint typecheck test ## Everything CI runs

.PHONY: lint
lint: ## Lint backend and frontend
	cd backend && ../$(PY) -m ruff check .
	cd backend && ../$(PY) -m black --check .
	npm --prefix frontend run lint
	npm --prefix frontend run format:check

.PHONY: format
format: ## Auto-format backend and frontend
	cd backend && ../$(PY) -m ruff check --fix .
	cd backend && ../$(PY) -m black .
	npm --prefix frontend run format

.PHONY: typecheck
typecheck: ## Type-check backend (mypy) and frontend (tsc)
	cd backend && ../$(PY) -m mypy
	npm --prefix frontend run typecheck

.PHONY: test
test: ## Run backend tests with coverage
	cd backend && ../$(PY) -m pytest --cov=app --cov-report=term-missing

.PHONY: build
build: ## Production build of the frontend
	npm --prefix frontend run build
