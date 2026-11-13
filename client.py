import asyncio
from pprint import pprint

from fastmcp import Client


async def main():
    async with Client("http://127.0.0.1:8000/mcp") as client:
        tools = await client.list_tools()
        for tool in tools:
            pprint(tool)

asyncio.run(main())