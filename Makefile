.PHONY: dev deploy lint

dev:
	uv run pywrangler dev

deploy:
	uv run pywrangler deploy

lint:
	uv run ruff check src
	uv run ruff format --check src
	uv run mypy src
