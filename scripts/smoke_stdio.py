#!/usr/bin/env python3
"""Check that an installed server completes an MCP stdio handshake.

Usage: smoke_stdio.py COMMAND [ARG...]. Only lists tools, so it needs no
credentials and makes no Piazza calls. Uses only the standard library so it can
run against a clean environment containing just the built wheel.
"""

import json
import subprocess
import sys


EXPECTED_TOOLS = {
    "get-piazza-post",
    "get-piazza-post-history",
    "list-piazza-courses",
    "list-piazza-filtered-posts",
    "list-piazza-posts",
    "search-piazza-posts",
}


def _request(process, request_id, method, params):
    message = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"Server closed stdout during {method}")
        response = json.loads(line)
        if response.get("id") == request_id:
            return response["result"]


def main(command):
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        initialized = _request(
            process,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        )
        process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
            + "\n"
        )
        process.stdin.flush()
        tools = _request(process, 2, "tools/list", {})["tools"]
    finally:
        process.stdin.close()
        process.terminate()
        process.wait(timeout=10)

    names = {tool["name"] for tool in tools}
    if initialized["serverInfo"]["name"] != "piazza-mcp":
        raise SystemExit(f"Unexpected server: {initialized['serverInfo']}")
    if names != EXPECTED_TOOLS:
        raise SystemExit(f"Unexpected tools: {sorted(names)}")
    print(f"Stdio handshake succeeded; {len(names)} tools listed.")


if __name__ == "__main__":
    main(sys.argv[1:])
