# Local R2 integration test

Install Python dependencies with `uv sync` and Wrangler with `npm install`.
Wrangler requires Node.js >= 22.12. Ensure a compatible `node` is on PATH, or set
`NODE_BINARY` to its executable path.

```sh
uv run pytest -v tests/integration/test_image_service.py
```

The test starts a loopback-only JavaScript Worker with a real Wrangler/Miniflare
R2 binding, a dynamically allocated port and a separate temporary persistence
directory. It never connects to Cloudflare R2 and does not use credentials or the
development bucket. Python's `ImageService` calls that binding through a small
test-only HTTP transport. The storage implementation is not mocked. The test
covers save/load byte equality, overwrite, delete, missing objects and repeated
delete. It does not test Python Workers SDK argument/result conversion.

The fixture runs independently of the application Worker so the test needs no LLM
credentials or Python Worker package bundle. A `finally` block deletes the object
even after assertions fail; fixture teardown stops Wrangler and its child
processes. Logs and all R2 state are kept under pytest's temporary directory.

`make test` includes both unit and integration tests. A sandbox must permit local
loopback sockets and spawning Wrangler's runtime processes.
