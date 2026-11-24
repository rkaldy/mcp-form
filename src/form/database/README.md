# D1 database adapter

The application uses the official Cloudflare Workers D1 binding in both local
and production environments. Wrangler/Miniflare provides SQLite-backed D1 locally;
Cloudflare provides the hosted database in production. The Python adapter does
not implement another SQLite driver, REST transport, or JavaScript conversion.
The installed `workers-runtime-sdk` handles binding arguments and Python result
dictionaries, including SQL NULL values.

## Configuration

`wrangler.jsonc` defines a `DB` binding with `database_name: "form"` and
`remote: false`. Run `make dev` to use its local database. Data is persisted under
`.wrangler/state/` by Wrangler, rather than in a separately managed
`data/form.sqlite` file.

For local development against Cloudflare, add the real `database_id` of your D1
database and change the binding's `remote` to `true`. This selects the remote
resource while the application still runs locally. To force local resources for
one run, use `uv run pywrangler dev --local`.

The `remote` option only controls development. A deployed Worker always uses the
hosted D1 binding. Set the real database ID before deploying to select an existing
database; no Cloudflare resources are created by this adapter.

Inspect the local database with:

```sh
npx wrangler d1 execute form --local --command "SELECT 1;"
```

## FastAPI and CRUD usage

Use `get_database_pool` as a FastAPI dependency:

```python
from typing import Annotated
from fastapi import Depends
from form.database.d1 import D1Pool
from form.database.dependencies import get_database_pool


async def endpoint(pool: Annotated[D1Pool, Depends(get_database_pool)]):
    async with pool.connection() as connection:
        return await connection.fetch_one("SELECT name FROM records WHERE id = ?", (1,))
```

The dependency reads `request.scope["env"].DB`, supplied by the Workers ASGI
integration. It requires `pywrangler`/Workers, not a plain Uvicorn process. Services
receive `DatabasePool`; CRUDs receive the `DatabaseConnection` from a short scope.
No connection should be held across an LLM/network call.

`execute`, `fetch_one`, and `fetch_all` autocommit individually. Use
`batch([Statement(...), ...])` for an atomic sequence. A batch cannot depend on
intermediate application results. There is no public commit/rollback API.

Parameters support `str`, `int`, `float`, `None`, and positional `?`/`?1` bindings.
Rows are dictionaries. Convert dates and structured values before binding;
`RETURNING` can return generated IDs. SQL/provider failures propagate without
retries or logging SQL/parameters. A cancelled write may already have executed;
callers must not blindly retry it.

References: [Cloudflare local D1](https://developers.cloudflare.com/d1/best-practices/local-development/)
and [remote bindings](https://developers.cloudflare.com/workers/local-development/#remote-bindings).
