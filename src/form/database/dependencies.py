from fastapi import Request

from form.database.d1 import D1Binding


def get_database_binding(request: Request) -> D1Binding:
    """Use the same binding for local SQLite-backed D1 and hosted Cloudflare D1."""
    env = request.scope.get("env")
    if env is None:
        raise RuntimeError("D1 requires the Workers runtime; start with pywrangler dev")
    return env.DB
