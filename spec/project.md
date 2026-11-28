# Projektové konvence

## Závazný technologický stack

| Oblast               | Technologie                         | Účel                                                                                                                             |
|----------------------|-------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| Runtime              | Python 3.14                         | Cílová verze převzatá z hlavní specifikace; ověřit kompatibilitu instalovaných balíčků.                                          |
| Závislosti a lock    | uv, pyproject.toml, uv.lock         | Reprodukovatelné prostředí.                                                                                                      |
| Datové kontrakty     | Pydantic v2                         | Typované vstupy, JSON serializace, výstupní schéma a finální validace.                                                           |
| Webový/API framework | FastAPI                             |                                                                                                                                  |
| Frontend             | Vue.js                              |                                                                                                                                  |
| Databáze             | sqlite3, D1                         | D1 kvůli přístupu na sqlite na produkčních serverech na Cloudflare |
| Migrace databáze     | alembic                             |                                                                                                                                  |
| LLM                  | LiteLLM                             | Volání AI                                                                                                                        |
| Unit testy           | pytest, pytest-asyncio, pytest-mock | Asynchronní testy, fake provider a mockování SDK.                                                                                |
| Kvalita kódu         | ruff, mypy                          | Formátování, lint a statická typová kontrola.                                                                                    |

Pro oblasti zde neuvedené použij technologii podle svého uvážení.

## Minimální struktura projektu

```text
salesman/
├── pyproject.toml
├── uv.lock
├── .python-version
├── src
│   └── form
│       ├── crud
│       ├── model
│       └── service
└── tests
    ├── unit
    ├── integration
    ├── e2e
    ├── external
    └── smoke
```

- Aplikace používá Pydantic modely definované v balíčku `model`. 
- Pro čtení a zápis v databázi používá CRUDy v balíčku `crud`.
- V balíčku `service` jsou třídy s business logikou.
- Pro konfiguraci použij třídu `class Settings(BaseSettings)`, `.env` a `.env.example`

## Tooling

- Runtime webové aplikace: Cloudflare Python Workers přes `pywrangler` (balíček `workers-py`). Vyžaduje `uv >= 0.13.4`.
- Instalace závislostí: `uv sync`
- Lokální server: `make run` (http://localhost:8000).
- Endpointy: `/`, `/health`, `/docs` a `/openapi.json`. Webová aplikace nevystavuje MCP.
- Lint: `make lint`
- Testy: `make test`


