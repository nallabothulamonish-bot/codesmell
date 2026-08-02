.PHONY: install test lint typecheck check cov migrate api worker docker clean

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy

cov:
	python -m pytest --cov=src/codesmell --cov-report=term-missing --cov-report=html

migrate:
	codesmell db upgrade

api:
	codesmell api serve --reload

worker:
	codesmell worker run

docker:
	docker compose up --build

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
