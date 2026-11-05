"""Black-box contract tests over real stdio JSON-RPC.

These observe only what an MCP client and an operator would: wire messages and
the process's stderr. They use the real service with a fake network client, so
they hold across changes to the MCP framework underneath.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from tests.support import (
    COURSE_BAD_OUTPUT_FIELD,
    COURSE_BAD_OUTPUT_KEY,
    COURSE_CLIENT_ERROR,
    COURSE_OK,
    COURSE_UNEXPECTED_ERROR,
    LEAK_SENTINEL,
    StdioServerSession,
    assert_sensitive_value_absent,
    tool_result_text,
)


CATALOG = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "mcp_tool_catalog.json"
    ).read_text(encoding="utf-8")
)
POST = {"course_id": COURSE_OK, "post_number": 7}


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    server = StdioServerSession("scripted", tmp_path_factory.mktemp("stdio"))
    yield server
    server.close()


@pytest.fixture
def own_session(tmp_path):
    server = StdioServerSession("scripted", tmp_path)
    yield server
    server.close()


def test_initialize_reports_server_identity_and_tools_capability(session):
    result = session.initialize_result

    assert result["serverInfo"]["name"] == "piazza-mcp"
    assert result["serverInfo"]["version"] == "0.1.0"
    assert "tools" in result["capabilities"]


def test_server_exposes_exactly_the_cataloged_tools(session):
    tools = session.request("tools/list", {})["tools"]

    assert {tool["name"] for tool in tools} == set(CATALOG)


@pytest.mark.parametrize(
    "field",
    ["description", "inputSchema", "outputSchema", "annotations"],
)
@pytest.mark.parametrize("tool_name", sorted(CATALOG))
def test_tool_contract_matches_catalog(session, tool_name, field):
    tools = session.request("tools/list", {})["tools"]
    wire = next(tool for tool in tools if tool["name"] == tool_name)

    assert wire[field] == CATALOG[tool_name][field]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_calls", "expected_fields"),
    [
        (
            "list-piazza-courses",
            {},
            [["courses"]],
            {"returned_count": 1},
        ),
        (
            "list-piazza-posts",
            {"course_id": COURSE_OK},
            [["posts", COURSE_OK, 10, 0]],
            {"course_id": COURSE_OK},
        ),
        (
            "list-piazza-posts",
            {"course_id": COURSE_OK, "limit": 5, "offset": 2},
            [["posts", COURSE_OK, 5, 2]],
            {"course_id": COURSE_OK},
        ),
        (
            "list-piazza-filtered-posts",
            {
                "course_id": COURSE_OK,
                "filters": ["folder", "updated"],
                "folder_name": "exam",
            },
            [
                ["filtered", COURSE_OK, "updated", None],
                ["filtered", COURSE_OK, "folder", "exam"],
            ],
            {"folder_name": "exam", "returned_count": 2, "truncated": False},
        ),
        (
            "list-piazza-filtered-posts",
            {"course_id": COURSE_OK, "filters": ["updated"], "max_results": 1},
            [["filtered", COURSE_OK, "updated", None]],
            {"folder_name": None, "returned_count": 1, "truncated": True},
        ),
        (
            "get-piazza-post",
            POST,
            [["post", COURSE_OK, 7]],
            {},
        ),
        (
            "get-piazza-post-history",
            POST,
            [["post", COURSE_OK, 7]],
            {"returned_count": 2, "truncated": False},
        ),
        (
            "get-piazza-post-history",
            {**POST, "max_revisions": 1},
            [["post", COURSE_OK, 7]],
            {"returned_count": 1, "truncated": True},
        ),
        (
            "search-piazza-posts",
            {"course_id": COURSE_OK, "query": "exam"},
            [["search", COURSE_OK, "exam"]],
            {"query": "exam", "returned_count": 2, "truncated": False},
        ),
        (
            "search-piazza-posts",
            {"course_id": COURSE_OK, "query": "exam", "max_results": 1},
            [["search", COURSE_OK, "exam"]],
            {"query": "exam", "returned_count": 1, "truncated": True},
        ),
    ],
)
def test_tool_call_reaches_service_and_returns_structured_content(
    session,
    tool_name,
    arguments,
    expected_calls,
    expected_fields,
):
    result, calls = session.call_tool(tool_name, arguments)

    assert result["isError"] is False, result
    assert calls == expected_calls
    structured = result["structuredContent"]
    assert json.loads(tool_result_text(result)) == structured
    jsonschema.validate(structured, CATALOG[tool_name]["outputSchema"])
    assert {key: structured[key] for key in expected_fields} == expected_fields


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("list-piazza-posts", {}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "evil": 1}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "limit": 26}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "limit": 0}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "limit": "10"}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "limit": True}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "limit": 5.0}),
        ("list-piazza-posts", {"course_id": COURSE_OK, "offset": 501}),
        ("list-piazza-posts", {"course_id": ""}),
        ("list-piazza-posts", {"course_id": "not-allowlisted"}),
        ("list-piazza-filtered-posts", {"course_id": COURSE_OK}),
        ("list-piazza-filtered-posts", {"course_id": COURSE_OK, "filters": []}),
        (
            "list-piazza-filtered-posts",
            {"course_id": COURSE_OK, "filters": ["nope"]},
        ),
        (
            "list-piazza-filtered-posts",
            {"course_id": COURSE_OK, "filters": ["updated", "updated"]},
        ),
        (
            "list-piazza-filtered-posts",
            {"course_id": COURSE_OK, "filters": ["folder"]},
        ),
        (
            "list-piazza-filtered-posts",
            {
                "course_id": COURSE_OK,
                "filters": ["updated"],
                "folder_name": "exam",
            },
        ),
        ("get-piazza-post", {"course_id": COURSE_OK}),
        ("get-piazza-post", {"course_id": COURSE_OK, "post_number": 0}),
        ("get-piazza-post-history", {"course_id": COURSE_OK}),
        ("get-piazza-post-history", {**POST, "max_revisions": 21}),
        ("search-piazza-posts", {"course_id": COURSE_OK}),
        ("search-piazza-posts", {"course_id": COURSE_OK, "query": ""}),
        ("search-piazza-posts", {"course_id": COURSE_OK, "query": "   "}),
        ("search-piazza-posts", {"course_id": COURSE_OK, "query": "x" * 201}),
        ("get-upcoming-work", {}),
    ],
)
def test_invalid_call_is_rejected_before_reaching_piazza(
    session,
    tool_name,
    arguments,
):
    result, calls = session.call_tool(tool_name, arguments)

    assert result["isError"] is True, result
    assert calls == []
    assert "structuredContent" not in result


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"course_id": "not-allowlisted"},
            "course_id is not a configured Piazza course",
        ),
        ({"course_id": COURSE_CLIENT_ERROR}, "Unable to reach Piazza"),
    ],
)
def test_expected_failures_tell_the_client_what_went_wrong(
    session,
    arguments,
    message,
):
    result, _ = session.call_tool("list-piazza-posts", arguments)

    assert result["isError"] is True
    assert message in tool_result_text(result)


def test_missing_configuration_is_reported_to_the_client(tmp_path):
    server = StdioServerSession("unconfigured", tmp_path)
    try:
        result, _ = server.call_tool("list-piazza-courses", {})
    finally:
        server.close()

    assert result["isError"] is True
    assert "Missing PIAZZA_EMAIL" in tool_result_text(result)


def test_unexpected_failure_does_not_leak_to_client_or_logs(own_session):
    result, calls = own_session.call_tool(
        "list-piazza-posts",
        {"course_id": COURSE_UNEXPECTED_ERROR},
    )
    stderr = own_session.close()

    assert calls == [["posts", COURSE_UNEXPECTED_ERROR, 10, 0]]
    assert result["isError"] is True
    assert tool_result_text(result) == "Piazza request failed"
    assert_sensitive_value_absent(result, LEAK_SENTINEL)
    assert_sensitive_value_absent(stderr, LEAK_SENTINEL)
    assert "Traceback" not in stderr
    assert "list-piazza-posts failed: LeakyUpstreamError" in stderr


@pytest.mark.parametrize(
    "course_id",
    [COURSE_BAD_OUTPUT_KEY, COURSE_BAD_OUTPUT_FIELD],
)
def test_invalid_output_is_blocked_and_does_not_leak(own_session, course_id):
    result, _ = own_session.call_tool(
        "list-piazza-posts",
        {"course_id": course_id},
    )
    stderr = own_session.close()

    assert result["isError"] is True
    assert "structuredContent" not in result
    assert (
        tool_result_text(result)
        == "Piazza returned an unexpected response shape"
    )
    assert_sensitive_value_absent(result, LEAK_SENTINEL)
    assert_sensitive_value_absent(stderr, LEAK_SENTINEL)
    assert "list-piazza-posts produced invalid output" in stderr


def test_stdout_carries_only_json_rpc_messages(own_session):
    own_session.call_tool("list-piazza-posts", {"course_id": COURSE_OK})
    own_session.call_tool(
        "list-piazza-posts",
        {"course_id": COURSE_UNEXPECTED_ERROR},
    )
    own_session.close()

    assert own_session.stdout_noise == []
