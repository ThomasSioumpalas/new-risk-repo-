.PHONY: install lint format typecheck test test-fast cov audit check examples serve migrate docker-build docker-up

install: ## Install project and dev dependencies from the lockfile
	uv sync --locked

lint: ## Static analysis (ruff)
	uv run ruff check .

format: ## Check formatting (ruff format)
	uv run ruff format --check .

typecheck: ## Static type-checking (mypy, strict)
	uv run mypy src

test: ## Run the full test suite
	uv run pytest

test-fast: ## Run tests, skipping slow statistical validation tests
	uv run pytest -m "not slow"

cov: ## Run tests with coverage report
	uv run pytest --cov=sextant --cov-report=term --cov-report=xml

audit: ## Audit locked dependencies for known vulnerabilities
	uv export --frozen --no-dev --no-hashes --format requirements-txt > /tmp/req.txt
	uv run pip-audit -r /tmp/req.txt --strict

check: lint typecheck test ## Everything CI checks, run locally

examples: ## Regenerate the committed example reports
	uv run sextant report examples/halcyon --out examples/reports

serve: ## Run the API locally with auto-reload
	uv run uvicorn sextant.api.app:app --reload

migrate: ## Apply database migrations
	uv run alembic upgrade head

docker-build: ## Build the container image
	docker build -t sextant:local .

docker-up: ## Start the full stack (API + Postgres) via docker compose
	docker compose up --build
