.PHONY: run build lint test test-external

run:
	uv run alembic upgrade head
	uv run uvicorn form.app:app --host 0.0.0.0 --port 8000 --reload

build:
	docker build -t form-scanner .

lint:
	uv run ruff format src tests migrations
	uv run ruff check --fix src tests migrations
	uv run mypy src tests migrations

test:
	uv run pytest -vv tests/unit tests/integration

test-external:
	uv run pytest -vv tests/external
