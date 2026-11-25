"""Run an isolated Wrangler R2 instance without Python app or LLM dependencies."""

import json
import os
import re
import signal
import subprocess
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

import httpx
import pytest


@pytest.fixture(scope="session")
def local_r2_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start a loopback-only Worker with its own temporary R2 state and stop it on exit."""
    root = Path(__file__).resolve().parents[2]
    directory = tmp_path_factory.mktemp("local-r2")
    config = directory / "wrangler.json"
    config.write_text(
        json.dumps(
            {
                "name": "form-r2-integration",
                "main": str(Path(__file__).with_name("fixtures") / "r2_worker.js"),
                "compatibility_date": "2026-11-20",
                "r2_buckets": [
                    {
                        "binding": "FORM_IMAGES",
                        "bucket_name": "form-test-images",
                        "remote": False,
                    }
                ],
            }
        )
    )
    command = [
        os.environ.get("NODE_BINARY", "node"),
        str(root / "node_modules" / "wrangler" / "bin" / "wrangler.js"),
        "dev",
        "--config",
        str(config),
        "--local",
        "--ip",
        "127.0.0.1",
        "--port",
        "0",
        "--inspector-port",
        "0",
        "--persist-to",
        str(directory / "state"),
    ]
    environment = {
        **os.environ,
        "WRANGLER_SEND_METRICS": "false",
        "WRANGLER_LOG_PATH": str(directory / "wrangler-debug.log"),
        "CI": "true",
    }
    log_path = directory / "wrangler.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        stdout = process.stdout
        assert stdout is not None
        ready: Queue[str | None] = Queue()

        def read_output():
            # Keep draining stdout after startup so runtime logs cannot fill the pipe.
            for line in stdout:
                log.write(line)
                log.flush()
                match = re.search(r"Ready on (http://127\.0\.0\.1:\d+)", line)
                if match:
                    ready.put(match.group(1))
            ready.put(None)

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        try:
            try:
                url = ready.get(timeout=45)
            except Empty:
                pytest.fail(
                    f"Local R2 Worker did not become ready:\n{log_path.read_text()}"
                )
            if url is None:
                pytest.fail(
                    f"Local R2 Worker exited during startup:\n{log_path.read_text()}"
                )
            with httpx.Client(trust_env=False, timeout=5) as client:
                response = client.get(f"{url}/health")
            response.raise_for_status()
            yield url
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            reader.join(timeout=10)
            stdout.close()


@dataclass
class LocalR2Object:
    data: bytes

    async def arrayBuffer(self) -> memoryview:
        return memoryview(self.data)


class LocalR2Bucket:
    """Transport binding operations to local R2; do not emulate storage in Python."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def put(self, key: str, data: bytes) -> object:
        response = await self._client.put(f"/{key}", content=data)
        response.raise_for_status()
        return None

    async def get(self, key: str) -> LocalR2Object | None:
        response = await self._client.get(f"/{key}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return LocalR2Object(response.content)

    async def delete(self, key: str):
        response = await self._client.delete(f"/{key}")
        response.raise_for_status()


@pytest.fixture
async def local_r2_bucket(local_r2_url: str) -> AsyncIterator[LocalR2Bucket]:
    """Share real local R2 through a per-test HTTP client with proxy lookup disabled."""
    async with httpx.AsyncClient(
        base_url=local_r2_url, trust_env=False, timeout=10
    ) as client:
        yield LocalR2Bucket(client)
