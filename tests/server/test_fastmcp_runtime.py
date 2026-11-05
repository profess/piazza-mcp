"""Guard FastMCP defaults that would weaken this server if they took effect."""

import pytest

from tests.support import (
    COURSE_OK,
    COURSE_UNEXPECTED_ERROR,
    LEAK_SENTINEL,
    StdioServerSession,
    assert_sensitive_value_absent,
    run_python_in_clean_process,
    tool_result_text,
)


BANNER_TEXT = "gofastmcp.com"


def test_handler_that_skips_the_boundary_still_has_client_errors_masked(tmp_path):
    code = f"""
import asyncio
from fastmcp import Client
import piazza_mcp.server as server

@server.mcp.tool(name="skips-boundary")
async def skips_boundary() -> dict:
    raise RuntimeError("{LEAK_SENTINEL}")

async def scenario():
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "skips-boundary",
            {{}},
            raise_on_error=False,
        )
    print(result.is_error, result.content[0].text)

asyncio.run(scenario())
"""
    result = run_python_in_clean_process(code, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "True Error calling tool 'skips-boundary'" in result.stdout
    assert_sensitive_value_absent(result.stdout, LEAK_SENTINEL)


def test_startup_prints_no_banner(tmp_path):
    server = StdioServerSession("scripted", tmp_path)

    assert BANNER_TEXT not in server.close()


def test_fastmcp_dotenv_settings_cannot_relax_server_safety(tmp_path):
    # FastMCP would read these from a .env in the working directory, which is
    # the checkout for the documented `uv --directory` launch.
    (tmp_path / ".env").write_text(
        "FASTMCP_STRICT_INPUT_VALIDATION=false\n"
        "FASTMCP_MASK_ERROR_DETAILS=false\n"
        "FASTMCP_SHOW_SERVER_BANNER=true\n"
        "FASTMCP_LOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )
    server = StdioServerSession("scripted", tmp_path)
    coerced, coerced_calls = server.call_tool(
        "list-piazza-posts",
        {"course_id": COURSE_OK, "limit": "10"},
    )
    failure, _ = server.call_tool(
        "list-piazza-posts",
        {"course_id": COURSE_UNEXPECTED_ERROR},
    )
    search, _ = server.call_tool(
        "search-piazza-posts",
        {"course_id": COURSE_OK, "query": LEAK_SENTINEL},
    )
    stderr = server.close()

    assert coerced["isError"] is True
    assert coerced_calls == []
    assert failure["isError"] is True
    assert_sensitive_value_absent(failure, LEAK_SENTINEL)
    assert search["isError"] is False
    assert_sensitive_value_absent(stderr, LEAK_SENTINEL)
    assert BANNER_TEXT not in stderr


def test_invalid_fastmcp_dotenv_setting_does_not_stop_the_server(tmp_path):
    (tmp_path / ".env").write_text(
        "FASTMCP_LOG_LEVEL=NOT_A_LEVEL\n",
        encoding="utf-8",
    )
    server = StdioServerSession("scripted", tmp_path)
    tools = server.request("tools/list", {})["tools"]
    server.close()

    assert any(tool["name"] == "list-piazza-posts" for tool in tools)


def test_rejected_arguments_do_not_leak_to_logs(tmp_path):
    server = StdioServerSession("scripted", tmp_path)
    result, calls = server.call_tool(
        "search-piazza-posts",
        {"course_id": COURSE_OK, "query": LEAK_SENTINEL * 20},
    )
    stderr = server.close()

    assert result["isError"] is True
    assert calls == []
    assert_sensitive_value_absent(stderr, LEAK_SENTINEL)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "named_in_message"),
    [
        ("list-piazza-posts", {}, "course_id"),
        ("list-piazza-posts", {"course_id": COURSE_OK, "evil": 1}, "evil"),
        ("list-piazza-posts", {"course_id": COURSE_OK, "limit": 26}, "limit"),
        (
            "list-piazza-filtered-posts",
            {"course_id": COURSE_OK},
            "filters",
        ),
        ("get-piazza-post", {"course_id": COURSE_OK}, "post_number"),
        ("search-piazza-posts", {"course_id": COURSE_OK}, "query"),
        ("get-upcoming-work", {}, "get-upcoming-work"),
    ],
)
def test_rejected_call_tells_the_client_what_to_fix(
    tmp_path,
    tool_name,
    arguments,
    named_in_message,
):
    server = StdioServerSession("scripted", tmp_path)
    result, _ = server.call_tool(tool_name, arguments)
    server.close()

    assert result["isError"] is True
    assert named_in_message in tool_result_text(result)
