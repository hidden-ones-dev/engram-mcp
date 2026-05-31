"""Stdio smoke test for the installed `engram-mcp` console script.

Runs three assertions against a freshly pip-installed package:

  a) Missing ENGRAM_TOKEN exits non-zero with the documented stderr.
  b) Initialize + tools/list returns exactly the documented tool set,
     each tool's inputSchema has the documented `required` fields.
  c) A tool call against an unreachable backend returns an MCP error
     result instead of crashing the server.

No live Engram backend is contacted. Designed to be run inside the
tests/smoke/Dockerfile image so packaging bugs (missing deps, broken
entry point, import errors) are caught before live integration.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


EXPECTED_TOOLS = {"search_knowledge", "fetch_document", "cite"}
# README documents these as the required args for each tool.
EXPECTED_REQUIRED = {
    "search_knowledge": ["query"],
    "fetch_document": ["document_id"],
    "cite": ["query"],
}
# An IANA-reserved discard port; nothing should be listening.
UNREACHABLE_BACKEND = "http://127.0.0.1:9"
OVERALL_TIMEOUT_SEC = 30


def _server_env(token: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ENGRAM_TOKEN", None)
    if token is not None:
        env["ENGRAM_TOKEN"] = token
    env["ENGRAM_BASE_URL"] = UNREACHABLE_BACKEND
    return env


def case_a_missing_token_exits_nonzero() -> None:
    result = subprocess.run(
        ["engram-mcp"],
        env=_server_env(token=None),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        raise AssertionError(
            f"expected non-zero exit when ENGRAM_TOKEN unset, got 0. "
            f"stderr={result.stderr!r}"
        )
    if "ENGRAM_TOKEN is required" not in result.stderr:
        raise AssertionError(
            f"expected 'ENGRAM_TOKEN is required' in stderr, "
            f"got stderr={result.stderr!r}"
        )
    first_line = result.stderr.splitlines()[0] if result.stderr else ""
    print(f"     exit={result.returncode}, stderr[0]={first_line!r}")


async def case_b_handshake_and_tools_list() -> None:
    params = StdioServerParameters(
        command="engram-mcp", env=_server_env(token="fake")
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            if init.serverInfo.name != "engram-mcp":
                raise AssertionError(
                    f"serverInfo.name: expected 'engram-mcp', "
                    f"got {init.serverInfo.name!r}"
                )
            print(f"     serverInfo.name={init.serverInfo.name!r}")

            list_result = await session.list_tools()
            names = {t.name for t in list_result.tools}
            if names != EXPECTED_TOOLS:
                raise AssertionError(
                    f"tools/list: expected {sorted(EXPECTED_TOOLS)}, "
                    f"got {sorted(names)}"
                )
            print(f"     tools={sorted(names)}")

            by_name = {t.name: t for t in list_result.tools}
            for tool_name, expected_required in EXPECTED_REQUIRED.items():
                schema = by_name[tool_name].inputSchema
                required = schema.get("required", [])
                if required != expected_required:
                    raise AssertionError(
                        f"{tool_name}.inputSchema.required: "
                        f"expected {expected_required}, got {required}"
                    )
            print("     all inputSchema.required match README")


async def case_c_tool_call_no_backend_returns_error() -> None:
    params = StdioServerParameters(
        command="engram-mcp", env=_server_env(token="fake")
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_knowledge", {"query": "ping"}
            )
            if not result.isError:
                raise AssertionError(
                    f"expected isError=True for unreachable backend, "
                    f"got isError={result.isError}, content={result.content!r}"
                )
            preview = ""
            for chunk in result.content:
                preview += getattr(chunk, "text", "")
            print(
                f"     isError=True, content preview="
                f"{preview[:120]!r}"
            )


async def amain() -> int:
    cases: list[tuple[str, object, bool]] = [
        (
            "a) missing ENGRAM_TOKEN -> non-zero exit + documented stderr",
            case_a_missing_token_exits_nonzero,
            False,
        ),
        (
            "b) initialize + tools/list match README",
            case_b_handshake_and_tools_list,
            True,
        ),
        (
            "c) tool call with unreachable backend -> error result",
            case_c_tool_call_no_backend_returns_error,
            True,
        ),
    ]

    failures: list[str] = []
    for label, fn, is_async in cases:
        print(f"[run]  {label}")
        try:
            if is_async:
                await asyncio.wait_for(fn(), timeout=OVERALL_TIMEOUT_SEC)
            else:
                fn()
            print(f"[PASS] {label}")
        except Exception as exc:  # noqa: BLE001 - surface everything
            print(f"[FAIL] {label}: {exc!r}")
            failures.append(label)
        print()

    if failures:
        print(f"SMOKE TEST FAILED: {len(failures)}/{len(cases)}")
        for label in failures:
            print(f"  - {label}")
        return 1
    print(f"SMOKE TEST PASSED: {len(cases)}/{len(cases)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
