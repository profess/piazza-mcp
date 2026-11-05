import asyncio

from fastmcp import Client, FastMCP
import pytest

from piazza_mcp.mcp_tools import register_piazza_tools
from piazza_mcp.services.piazza import PiazzaClientError
from tests.support import LEAK_SENTINEL, assert_sensitive_value_absent


POST = {"course_id": "abc123", "post_number": 7}
TOOL_CALLS = [
    ("list-piazza-courses", {}, "list_courses"),
    ("list-piazza-posts", {"course_id": "abc123"}, "list_posts"),
    (
        "list-piazza-filtered-posts",
        {"course_id": "abc123", "filters": ["updated"]},
        "list_filtered_posts",
    ),
    ("get-piazza-post", POST, "get_post"),
    ("get-piazza-post-history", POST, "get_post_history"),
    (
        "search-piazza-posts",
        {"course_id": "abc123", "query": "exam"},
        "search_posts",
    ),
]


class ScriptedService:
    """Answer every service operation by raising or returning one value."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def __getattr__(self, operation):
        async def call(*arguments):
            self.calls.append(operation)
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

        return call


def call_registered_tool(service, tool_name, arguments):
    mcp = FastMCP("test")
    register_piazza_tools(mcp, lambda: service)

    async def scenario():
        async with Client(mcp) as client:
            return await client.call_tool(
                tool_name,
                arguments,
                raise_on_error=False,
            )

    return asyncio.run(scenario())


def test_service_is_requested_for_every_call_and_never_while_listing():
    service_requests = []

    def get_service():
        service_requests.append("requested")
        raise PiazzaClientError("service unavailable")

    mcp = FastMCP("test")
    register_piazza_tools(mcp, get_service)

    async def scenario():
        async with Client(mcp) as client:
            await client.list_tools()
            requests_after_listing = list(service_requests)
            results = [
                await client.call_tool(
                    "list-piazza-courses",
                    {},
                    raise_on_error=False,
                )
                for _ in range(2)
            ]
        return requests_after_listing, results

    requests_after_listing, results = asyncio.run(scenario())

    assert requests_after_listing == []
    assert service_requests == ["requested", "requested"]
    for result in results:
        assert result.is_error is True
        assert "service unavailable" in result.content[0].text


@pytest.mark.parametrize(("tool_name", "arguments", "operation"), TOOL_CALLS)
def test_every_tool_hides_unexpected_failures_behind_the_boundary(
    tool_name,
    arguments,
    operation,
):
    service = ScriptedService(KeyError(LEAK_SENTINEL))

    result = call_registered_tool(service, tool_name, arguments)

    assert service.calls == [operation]
    assert result.is_error is True
    assert result.content[0].text == "Piazza request failed"
    assert_sensitive_value_absent(result.content[0].text, LEAK_SENTINEL)


@pytest.mark.parametrize(("tool_name", "arguments", "operation"), TOOL_CALLS)
def test_every_tool_blocks_output_that_breaks_its_schema(
    tool_name,
    arguments,
    operation,
):
    service = ScriptedService({"undeclared": LEAK_SENTINEL})

    result = call_registered_tool(service, tool_name, arguments)

    assert service.calls == [operation]
    assert result.is_error is True
    assert result.structured_content is None
    assert (
        result.content[0].text
        == "Piazza returned an unexpected response shape"
    )
