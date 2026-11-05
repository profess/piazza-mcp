"""Focused helpers for tests that cross fragile boundaries."""

from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Any, TypeVar


_T = TypeVar("_T")

LEAK_SENTINEL = "UNIQUE_LEAK_SENTINEL_7f3a9c"
CALL_LOG_VARIABLE = "PIAZZA_TEST_CALL_LOG"
COURSE_OK = "abc123"
COURSE_CLIENT_ERROR = "client-error"
COURSE_UNEXPECTED_ERROR = "unexpected-error"
COURSE_BAD_OUTPUT_KEY = "bad-output-key"
COURSE_BAD_OUTPUT_FIELD = "bad-output-field"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RESPONSE_TIMEOUT_SECONDS = 30


def find_named_item(items: Iterable[_T], name: str) -> _T:
    """Return the one item whose public ``name`` equals ``name``."""
    matches = [item for item in items if getattr(item, "name", None) == name]
    assert len(matches) == 1, (
        f"Expected exactly one item named {name!r}, found {len(matches)}"
    )
    return matches[0]


def assert_sensitive_value_absent(value: object, sentinel: str) -> None:
    """Assert a sentinel is absent from common outward representations."""
    if not sentinel:
        raise ValueError("sentinel must not be empty")
    representations = [str(value), repr(value)]
    if not isinstance(value, str):
        representations.append(
            json.dumps(
                value,
                default=repr,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    for representation in representations:
        assert sentinel not in representation


def run_python_in_clean_process(
    code: str,
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run local source in a subprocess without inheriting credentials."""
    source_root = Path(__file__).resolve().parents[2] / "src"
    clean_environment = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(source_root),
    }
    if environment is not None:
        clean_environment.update(environment)

    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=clean_environment,
        capture_output=True,
        text=True,
        check=False,
    )


class StdioServerSession:
    """Drive the real server over stdio JSON-RPC, as an MCP client would.

    The process starts without inherited credentials, and its entry point
    never reads the checkout's ``.env``. Every client call it makes is recorded.
    """

    def __init__(self, mode: str, cwd: Path):
        self.call_log = cwd / "client-calls.jsonl"
        self.call_log.touch()
        self.stdout_noise: list[str] = []
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._next_id = 0
        self._process = subprocess.Popen(
            [sys.executable, "-m", "tests.support.stdio_server", mode],
            cwd=cwd,
            env={
                CALL_LOG_VARIABLE: str(self.call_log),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": os.pathsep.join(
                    (str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT))
                ),
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self._readers = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for reader in self._readers:
            reader.start()
        self.initialize_result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "stdio-test", "version": "0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _read_stdout(self) -> None:
        for line in self._process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                message = None
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                self.stdout_noise.append(line)
            elif "id" in message:
                self._responses.put(message)

    def _read_stderr(self) -> None:
        for line in self._process.stderr:
            self._stderr_lines.append(line)

    def _send(self, message: dict[str, Any]) -> None:
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send one request and return its result from the wire."""
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": params,
            }
        )
        try:
            response = self._responses.get(timeout=_RESPONSE_TIMEOUT_SECONDS)
        except queue.Empty:
            raise AssertionError(
                f"No response to {method}; stderr: {self.stderr()}"
            ) from None
        assert response["id"] == self._next_id
        assert "error" not in response, response
        return response["result"]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], list[list[Any]]]:
        """Return a tool's wire result and the client calls it caused."""
        self.call_log.write_text("", encoding="utf-8")
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        lines = self.call_log.read_text(encoding="utf-8").splitlines()
        return result, [json.loads(line) for line in lines]

    def stderr(self) -> str:
        return "".join(self._stderr_lines)

    def close(self) -> str:
        """Stop the server and return everything it wrote to stderr."""
        self._process.stdin.close()
        try:
            self._process.wait(timeout=_RESPONSE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        for reader in self._readers:
            reader.join(timeout=_RESPONSE_TIMEOUT_SECONDS)
        return self.stderr()


def tool_result_text(result: dict[str, Any]) -> str:
    """Return the text of a tool result's single content block."""
    blocks = result["content"]
    assert len(blocks) == 1, blocks
    return blocks[0]["text"]
