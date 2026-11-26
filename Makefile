.PHONY: run build lint test test-external test-e2e

run:
	npm run build
	uv run alembic upgrade head
	uv run uvicorn form.app:app --host 0.0.0.0 --port 8000 --reload

build:
	docker build -t form-scanner .

run-docker:
	docker run --rm --name form-scanner --env-file .env -p 8000:8000 -v "$(pwd)/data:/app/data" form-scanner

lint:
	uv run ruff format src tests migrations
	uv run ruff check --fix src tests migrations
	uv run mypy src tests migrations

test:
	uv run pytest -vv tests/unit tests/integration

test-external:
	uv run pytest -vv tests/external

test-e2e:
	npm run test:e2e
