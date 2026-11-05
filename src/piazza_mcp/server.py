from fastmcp import FastMCP

from piazza_mcp.mcp_tools import register_piazza_tools
from piazza_mcp.services.piazza import get_piazza_service


mcp = FastMCP(
    "piazza-mcp",
    version="0.1.0",
    strict_input_validation=True,
    mask_error_details=True,
)
register_piazza_tools(mcp, lambda: get_piazza_service())


async def main():
    """Run the MCP server over standard input and output streams."""
    # Disabling the banner also skips FastMCP's PyPI update check.
    await mcp.run_async(transport="stdio", show_banner=False)
