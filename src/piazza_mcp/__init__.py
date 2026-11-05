import asyncio
import os


# FastMCP loads FASTMCP_* settings from a .env in the working directory when it
# is first imported. That file holds this project's credentials, and a setting
# there such as FASTMCP_LOG_LEVEL=DEBUG would log tool arguments. This runs
# before any piazza_mcp module can import FastMCP.
os.environ["FASTMCP_ENV_FILE"] = os.devnull


def main():
    """Main entry point for the package."""
    from . import server

    asyncio.run(server.main())

__all__ = ["main"]
