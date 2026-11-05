"""Launch the real entry point with a fake network client, for stdio tests.

Runs the real ``PiazzaService`` and normalizer, so only Piazza itself is
replaced. It never reads the checkout's ``.env`` and makes no network calls.
Run as ``python -m tests.support.stdio_server {scripted|unconfigured}``.
"""

import itertools
import json
import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any

import piazza_mcp
from piazza_mcp.config import PiazzaConfig
import piazza_mcp.config.env as config_env
import piazza_mcp.server as server_module
from piazza_mcp.services.piazza import (
    PiazzaClientError,
    PiazzaNormalizer,
    PiazzaService,
)
from tests.support import (
    CALL_LOG_VARIABLE,
    COURSE_BAD_OUTPUT_FIELD,
    COURSE_BAD_OUTPUT_KEY,
    COURSE_CLIENT_ERROR,
    COURSE_OK,
    COURSE_UNEXPECTED_ERROR,
    LEAK_SENTINEL,
)


CLIENT_ERROR_MESSAGE = "Unable to reach Piazza"


class LeakyUpstreamError(Exception):
    """An unanticipated failure whose message carries private content."""


def _summary(post_number: int) -> dict[str, Any]:
    return {
        "id": post_number,
        "type": "question",
        "subject": f"Exam {post_number}",
        "content_snip": "When is it?",
        "folders": ["exam"],
    }


class RecordingClient:
    """Fake Piazza client that logs every call for assertions in the test."""

    def __init__(self, call_log: Path):
        self.call_log = call_log

    def _record(self, *call: object) -> None:
        with self.call_log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(call) + "\n")

    async def list_courses(self) -> list[dict[str, Any]]:
        self._record("courses")
        return [{"nid": COURSE_OK, "num": "CMSC 132", "term": "Fall 2026"}]

    async def list_posts(self, course_id, limit, offset):
        self._record("posts", course_id, limit, offset)
        if course_id == COURSE_CLIENT_ERROR:
            raise PiazzaClientError(CLIENT_ERROR_MESSAGE)
        if course_id == COURSE_UNEXPECTED_ERROR:
            raise LeakyUpstreamError(f"post body {LEAK_SENTINEL}")
        return [_summary(1)]

    async def get_post(self, course_id, post_number):
        self._record("post", course_id, post_number)
        return {
            "nr": post_number,
            "type": "question",
            "subject": "Exam",
            "content": "When is it?",
            "history": [
                {
                    "subject": "Exam",
                    "content": "First draft",
                    "created": "2026-08-19T10:00:00Z",
                },
                {
                    "subject": "Exam",
                    "content": "Second draft",
                    "created": "2026-08-19T11:00:00Z",
                },
            ],
        }

    async def search_posts(self, course_id, query):
        self._record("search", course_id, query)
        return [_summary(1), _summary(2)]

    async def list_filtered_posts(self, course_id, filter_name, folder_name):
        self._record("filtered", course_id, filter_name, folder_name)
        return [_summary(1), _summary(2)]


class ScriptedService(PiazzaService):
    """Real service, except scripted courses return schema-breaking output."""

    async def list_posts(self, course_id, limit=10, offset=0):
        result = await super().list_posts(course_id, limit, offset)
        if course_id == COURSE_BAD_OUTPUT_KEY:
            result["undeclared"] = LEAK_SENTINEL
        if course_id == COURSE_BAD_OUTPUT_FIELD:
            result["returned_count"] = LEAK_SENTINEL
        return result


def _scripted_service(call_log: Path) -> PiazzaService:
    courses = (
        COURSE_OK,
        COURSE_CLIENT_ERROR,
        COURSE_UNEXPECTED_ERROR,
        COURSE_BAD_OUTPUT_KEY,
        COURSE_BAD_OUTPUT_FIELD,
    )
    ticks = itertools.count(step=1_000)
    return ScriptedService(
        PiazzaConfig(
            email="student@example.edu",
            password="not-a-real-password",
            courses=MappingProxyType({course: course for course in courses}),
        ),
        RecordingClient(call_log),
        PiazzaNormalizer(),
        # Each call lands past the cache window so every call reaches the client.
        monotonic_provider=lambda: float(next(ticks)),
    )


def main() -> None:
    config_env.PROJECT_ENV_PATH = Path.cwd() / "absent.env"
    if sys.argv[1] == "scripted":
        service = _scripted_service(Path(os.environ[CALL_LOG_VARIABLE]))
        server_module.get_piazza_service = lambda: service
    piazza_mcp.main()


if __name__ == "__main__":
    main()
