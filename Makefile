.PHONY: dev deploy lint

dev:
	uv run pywrangler dev

deploy:
	uv run pywrangler deploy

lint:
	uv run ruff check --fix src
	uv run ruff format src
	uv run mypy src

test:
	uv run pytest tests/unit tests/integration

