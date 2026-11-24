.PHONY: dev deploy lint

dev:
	uv run pywrangler dev

deploy:
	uv run pywrangler deploy

lint:
	uv run ruff format src tests migrations
	uv run ruff check --fix src tests migrations
	uv run mypy src tests migrations

test:
	uv run pytest -vv tests/unit tests/integration

test-external:
	uv run pytest -vv tests/external

