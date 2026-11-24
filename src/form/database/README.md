# Database adapters

CRUD classes accept `DatabaseConnection`; services accept `DatabasePool` and open
short resource scopes:

```python
from form.database.sqlite import SQLitePool

pool = SQLitePool()  # data/form.sqlite; no I/O until connection() is entered
async with pool.connection() as connection:
    row = await connection.fetch_one("SELECT name FROM records WHERE id = ?", (1,))
```

On Cloudflare Workers, inject the configured D1 binding instead:

```python
from form.database.d1 import D1Pool

pool = D1Pool(request.scope["env"].DB)
```

The caller chooses the backend; no environment mutation or global pool is needed.
The production binding and its database ID must be configured in Wrangler when a
real D1 database is provisioned. The SQLite module is not imported by the D1 path.

Both implementations support scalar parameters (`str`, `int`, `float`, `None`),
`?`/`?1` placeholders, dictionary rows, and SQL `RETURNING` for generated IDs.
Convert structured application values such as dates or JSON before binding.

`execute`, `fetch_one`, and `fetch_all` each autocommit. Leaving a connection scope
does not roll back earlier statements. Use `batch([Statement(...), ...])` for an
atomic group; the statements and their results retain their input order. A batch
cannot depend on results computed between its statements. Do not send transaction
control SQL or hold a connection across an LLM/network call.

SQLite uses aiosqlite to keep filesystem/database work off the event loop. D1 uses
the Worker binding's asynchronous prepared statements, never the REST API. SQL
errors propagate without retries or logging SQL/parameters. A cancelled write may
already have executed, so callers must not blindly retry it.
SQLite batches finish atomically before cancellation is propagated and before the
connection can be reused; cancellation therefore does not imply a rollback.
D1 scalar conversion maps Python `None` to JavaScript `null` explicitly and maps
SQL null results back to Python `None`.
