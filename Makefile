.DEFAULT_GOAL := help
UV := uv
RUN := $(UV) run

.PHONY: help install run test lint format typecheck check bench up down logs

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install: ## Install runtime and dev dependencies from uv.lock
	$(UV) sync --locked

run: ## Start the development server on :8000
	DJANGO_DEBUG=true $(RUN) python manage.py runserver

test: ## Run the test suite with coverage
	$(RUN) coverage run -m pytest -q
	$(RUN) coverage report

lint: ## Check formatting and lint rules
	$(RUN) ruff format --check .
	$(RUN) ruff check .

format: ## Apply formatting and safe lint fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## Run mypy
	$(RUN) mypy routefuel spotter

check: lint typecheck test ## Run every CI quality gate

bench: ## Time each planning stage on a recorded cross-country route
	$(RUN) python -m scripts.benchmark

up: ## Build and start the API and Redis with Docker Compose
	docker compose up --build --detach --wait

down: ## Stop the Compose stack
	docker compose down

logs: ## Follow API logs
	docker compose logs --follow api
