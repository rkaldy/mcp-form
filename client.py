import argparse
import asyncio
import sys
import traceback
from typing import Any

import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError

DEFAULT_URL = "http://intranet.all2cover.com/mcp/"


async def report_http_error(response: httpx2.Response) -> None:
    if response.status_code < 400:
        return
    url = response.request.url.copy_with(userinfo=b"", query=None, fragment=None)
    print(
        f"HTTP {response.status_code} {response.reason_phrase}: "
        f"{response.request.method} {url}",
        file=sys.stderr,
    )
    print(
        f"Content-Type: {response.headers.get('content-type', '(missing)')}",
        file=sys.stderr,
    )
    # Read only failed responses; successful SSE streams must remain streaming.
    await response.aread()
    print(f"Response body: {response.text[:4096] or '(empty)'}", file=sys.stderr)
    if len(response.text) > 4096:
        print("[response body truncated]", file=sys.stderr)


def diagnostic_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
    **kwargs: Any,
) -> httpx2.AsyncClient:
    # The MCP SDK handles redirects itself and supplies the transport timeouts.
    kwargs.pop("follow_redirects", None)
    client = create_mcp_http_client(
        headers=headers, timeout=timeout, auth=auth, **kwargs
    )
    client.event_hooks.setdefault("response", []).append(report_http_error)
    return client


def report_error(error: BaseException) -> None:
    if isinstance(error, BaseExceptionGroup):
        for child in error.exceptions:
            report_error(child)
    elif isinstance(error, MCPError):
        print(
            f"MCP error: {error.error.model_dump_json(exclude_none=True)}",
            file=sys.stderr,
        )
    else:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)


def parse_header(value: str) -> tuple[str, str]:
    name, separator, content = value.partition(":")
    name = name.strip()
    if not separator or not name or "\r" in value or "\n" in value:
        raise argparse.ArgumentTypeError("expected a header in 'Name: value' format")
    return name, content.strip()


async def main(headers: dict[str, str] | None = None, url: str = DEFAULT_URL):
    transport = StreamableHttpTransport(
        url, headers=headers, httpx_client_factory=diagnostic_http_client
    )
    async with Client(transport) as client:
        for tool in await client.list_tools():
            print(tool.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List available MCP tools.")
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP endpoint URL.")
    parser.add_argument(
        "--debug", action="store_true", help="Also print the full traceback."
    )
    parser.add_argument(
        "-H",
        "--header",
        action="append",
        type=parse_header,
        default=[],
        metavar="NAME:VALUE",
        help="Additional HTTP header (can be repeated).",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(headers=dict(args.header), url=args.url))
    except Exception as error:  # noqa: BLE001 - CLI boundary: report and exit nonzero.
        report_error(error)
        if args.debug:
            traceback.print_exc()
        sys.exit(1)
