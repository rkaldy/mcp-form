"""FastAPI dependencies backed by Wrangler's configured D1 binding."""

from fastapi import Request

from form.database.d1 import D1Pool


def get_database_pool(request: Request) -> D1Pool:
    """Use the same binding for local SQLite-backed D1 and hosted Cloudflare D1."""
    env = request.scope.get("env")
    if env is None:
        raise RuntimeError("D1 requires the Workers runtime; start with pywrangler dev")
    return D1Pool(env.DB)
