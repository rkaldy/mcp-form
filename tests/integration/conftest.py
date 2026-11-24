"""Run an isolated Wrangler R2 instance without Python app or LLM dependencies."""

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

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
    with (directory / "wrangler.log").open("w+") as log:
        process = subprocess.Popen(
            command,
            cwd=directory,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 45
            output = ""
            while time.monotonic() < deadline:
                log.seek(0)
                output = log.read()
                if process.poll() is not None:
                    pytest.fail(f"Local R2 Worker exited during startup:\n{output}")
                match = re.search(r"Ready on (http://127\.0\.0\.1:\d+)", output)
                if match:
                    url = match.group(1)
                    try:
                        with httpx.Client(trust_env=False, timeout=1) as client:
                            response = client.get(f"{url}/health")
                        if response.status_code == 200:
                            yield url
                            return
                    except httpx.TransportError:
                        pass
                # Bounded polling of process readiness, not a delay in test behavior.
                time.sleep(0.1)
            pytest.fail(f"Local R2 Worker did not become ready:\n{output}")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)


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
