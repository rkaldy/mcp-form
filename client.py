import asyncio
from fastmcp import Client


async def main():
    async with Client("http://127.0.0.1:8000/mcp") as client:
        for tool in await client.list_tools():
            print(tool.model_dump_json(indent=2, exclude_none=True))

asyncio.run(main())