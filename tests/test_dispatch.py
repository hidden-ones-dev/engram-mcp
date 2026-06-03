"""Hermetic dispatch + formatting tests.

Ported from `hidden-ones-dev/Engram/backend/tests/test_mcp_plugin.py`
with imports rewritten from `mcp_shared.*` to `engram_mcp.*`. Stubs
the dispatcher (`_StubClient` satisfies the `Dispatcher` Protocol),
drives `_dispatch` directly — no real HTTP, no MCP transport. The
end-to-end stdio path is covered by `tests/smoke/test_stdio_smoke.py`.
"""

from typing import Any

import pytest

from engram_mcp.formatting import (
    format_citations,
    format_document,
    format_search_results,
)
from engram_mcp.server import _dispatch
from engram_mcp.tools import TOOLS


class _StubClient:
    def __init__(
        self,
        *,
        chunks: list[dict[str, Any]] | None = None,
        doc: dict[str, Any] | None = None,
    ) -> None:
        self.chunks = chunks or []
        self.doc = doc or {}
        self.last_search: dict[str, Any] | None = None
        self.last_fetch: str | None = None
        self.last_context_lines: int = 0

    async def search_knowledge(
        self, query: str, top_k: int = 10, source: str | None = None
    ) -> list[dict[str, Any]]:
        self.last_search = {"query": query, "top_k": top_k, "source": source}
        return self.chunks

    async def fetch_document(
        self, document_id: str, context_lines: int = 0
    ) -> dict[str, Any]:
        self.last_fetch = document_id
        self.last_context_lines = context_lines
        return self.doc


def test_tool_surface_matches_scope() -> None:
    names = {t.name for t in TOOLS}
    assert names == {"search_knowledge", "fetch_document", "cite"}


def test_search_tool_schema_requires_query() -> None:
    tool = next(t for t in TOOLS if t.name == "search_knowledge")
    schema = tool.inputSchema
    assert schema["required"] == ["query"]
    top_k = schema["properties"]["top_k"]
    assert top_k["minimum"] == 1
    assert top_k["maximum"] == 50
    assert schema["properties"]["source"]["enum"] == ["github", "notion"]


@pytest.mark.asyncio
async def test_dispatch_search_knowledge_passes_args_and_formats() -> None:
    client = _StubClient(
        chunks=[
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "document_title": "auth module",
                "file_path": "backend/auth.py",
                "source": "github",
                "url": "https://github.com/x/y/blob/main/backend/auth.py",
                "relevance_score": 0.91,
                "content_preview": "def login(...):",
            }
        ]
    )
    out = await _dispatch(
        client,
        "search_knowledge",
        {"query": "login flow", "top_k": 5, "source": "github"},
    )
    assert client.last_search == {
        "query": "login flow",
        "top_k": 5,
        "source": "github",
    }
    assert "auth module" in out
    assert "0.910" in out
    assert "backend/auth.py" in out


@pytest.mark.asyncio
async def test_dispatch_search_knowledge_handles_empty() -> None:
    out = await _dispatch(_StubClient(), "search_knowledge", {"query": "anything"})
    assert "No results" in out


@pytest.mark.asyncio
async def test_dispatch_fetch_document_formats_content() -> None:
    client = _StubClient(
        doc={
            "id": "d1",
            "title": "Architecture",
            "source": "notion",
            "file_path": None,
            "url": "https://notion.so/abc",
            "content": "# Overview\n...",
        }
    )
    out = await _dispatch(client, "fetch_document", {"document_id": "d1"})
    assert client.last_fetch == "d1"
    assert "Architecture" in out
    assert "notion" in out
    assert "notion.so/abc" in out


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_raises() -> None:
    with pytest.raises(ValueError):
        await _dispatch(_StubClient(), "bogus", {})


def test_format_search_includes_all_fields() -> None:
    text = format_search_results(
        [
            {
                "document_title": "T",
                "source": "github",
                "file_path": "a.py",
                "url": "https://x",
                "relevance_score": 0.5,
                "content_preview": "preview",
            }
        ]
    )
    assert "T" in text and "github" in text and "a.py" in text and "preview" in text


def test_format_document_handles_missing_url_and_path() -> None:
    text = format_document({"title": "X", "source": "github", "content": "body"})
    assert "X" in text and "body" in text


@pytest.mark.parametrize(
    "file_path, expected_lang",
    [
        ("backend/auth.py", "python"),
        ("frontend/src/app.ts", "typescript"),
        ("frontend/src/component.tsx", "typescript"),
        ("scripts/build.js", "javascript"),
        ("ui/widget.jsx", "javascript"),
        ("cmd/main.go", "go"),
        ("src/lib.rs", "rust"),
    ],
)
def test_format_search_fences_github_previews_with_language(
    file_path: str, expected_lang: str
) -> None:
    text = format_search_results(
        [
            {
                "document_title": "T",
                "source": "github",
                "file_path": file_path,
                "content_preview": "code",
            }
        ]
    )
    assert f"```{expected_lang}\ncode\n```" in text


def test_format_search_fences_unknown_extension_with_empty_lang() -> None:
    text = format_search_results(
        [
            {
                "document_title": "T",
                "source": "github",
                "file_path": "Makefile",
                "content_preview": "all:",
            }
        ]
    )
    assert "```\nall:\n```" in text


def _mixed_chunks() -> list[dict[str, Any]]:
    return [
        {
            "document_id": "g1",
            "document_title": "code-A",
            "source": "github",
            "file_path": "a.py",
            "content_preview": "def a(): pass",
            "relevance_score": 0.9,
        },
        {
            "document_id": "n1",
            "document_title": "doc-A",
            "source": "notion",
            "content_preview": "How to deploy.",
            "relevance_score": 0.8,
        },
        {
            "document_id": "g2",
            "document_title": "code-B",
            "source": "github",
            "file_path": "b.py",
            "content_preview": "def b(): pass",
            "relevance_score": 0.7,
        },
    ]


def test_format_search_default_keeps_relevance_order() -> None:
    text = format_search_results(_mixed_chunks())
    assert text.index("code-A") < text.index("doc-A") < text.index("code-B")
    assert "intent:" not in text


def test_format_search_intent_generate_floats_github_above_notion() -> None:
    text = format_search_results(_mixed_chunks(), intent="generate")
    assert text.index("code-A") < text.index("code-B") < text.index("doc-A")
    assert "intent: generate" in text


def test_format_search_intent_question_floats_notion_above_github() -> None:
    text = format_search_results(_mixed_chunks(), intent="question")
    assert text.index("doc-A") < text.index("code-A") < text.index("code-B")
    assert "intent: question" in text


def test_format_search_intent_explain_preserves_default_order() -> None:
    text = format_search_results(_mixed_chunks(), intent="explain")
    assert text.index("code-A") < text.index("doc-A") < text.index("code-B")
    assert "intent: explain" in text


def test_format_search_unknown_intent_is_ignored() -> None:
    text = format_search_results(_mixed_chunks(), intent="bogus")
    assert "intent:" not in text


@pytest.mark.asyncio
async def test_dispatch_search_passes_intent_through() -> None:
    client = _StubClient(chunks=_mixed_chunks())
    out = await _dispatch(
        client, "search_knowledge", {"query": "deploy", "intent": "question"}
    )
    assert "intent: question" in out


def test_search_tool_schema_advertises_intent() -> None:
    tool = next(t for t in TOOLS if t.name == "search_knowledge")
    intent = tool.inputSchema["properties"].get("intent")
    assert intent is not None
    assert set(intent["enum"]) == {"explain", "generate", "question"}
    assert "intent" not in tool.inputSchema["required"]


def test_fetch_tool_schema_advertises_context_lines() -> None:
    tool = next(t for t in TOOLS if t.name == "fetch_document")
    cl = tool.inputSchema["properties"].get("context_lines")
    assert cl is not None
    assert cl["minimum"] == 0
    assert cl["maximum"] == 50
    assert "context_lines" not in tool.inputSchema["required"]


@pytest.mark.asyncio
async def test_dispatch_fetch_passes_context_lines() -> None:
    client = _StubClient(doc={"title": "X", "source": "github", "content": "body"})
    await _dispatch(
        client,
        "fetch_document",
        {"document_id": "abc", "context_lines": 10},
    )
    assert client.last_fetch == "abc"
    assert client.last_context_lines == 10


@pytest.mark.asyncio
async def test_dispatch_fetch_default_context_lines_is_zero() -> None:
    client = _StubClient(doc={"title": "X", "source": "github", "content": "body"})
    await _dispatch(client, "fetch_document", {"document_id": "abc"})
    assert client.last_context_lines == 0


def test_format_document_renders_chunks_when_no_top_level_content() -> None:
    text = format_document(
        {
            "title": "auth",
            "source": "github",
            "file_path": "backend/auth.py",
            "chunks": [
                {
                    "content": "def login():\n    pass",
                    "start_line": 10,
                    "end_line": 11,
                }
            ],
        }
    )
    assert "```python" in text
    assert "def login():" in text
    assert "L10-11" in text


def test_format_document_uses_padded_fields_when_present() -> None:
    text = format_document(
        {
            "title": "auth",
            "source": "github",
            "file_path": "backend/auth.py",
            "chunks": [
                {
                    "content": "def login():\n    pass",
                    "start_line": 10,
                    "end_line": 11,
                    "padded_content": "# import os\n\ndef login():\n    pass\n\n# trailer",
                    "padded_start_line": 8,
                    "padded_end_line": 13,
                }
            ],
        }
    )
    assert "# import os" in text
    assert "L8-13" in text


def test_format_document_does_not_fence_notion_chunks() -> None:
    text = format_document(
        {
            "title": "Architecture",
            "source": "notion",
            "chunks": [{"content": "Some prose."}],
        }
    )
    assert "```" not in text
    assert "Some prose." in text


def test_cite_tool_schema_requires_query() -> None:
    tool = next(t for t in TOOLS if t.name == "cite")
    schema = tool.inputSchema
    assert schema["required"] == ["query"]
    assert schema["properties"]["top_k"]["maximum"] == 20


def test_format_citations_returns_locators_only() -> None:
    text = format_citations(
        [
            {
                "document_id": "g1",
                "source": "github",
                "file_path": "backend/auth.py",
                "url": "https://github.com/x/y/blob/main/backend/auth.py#L10-L20",
                "content_preview": "this should not appear",
                "relevance_score": 0.9,
            }
        ]
    )
    assert "backend/auth.py" in text
    assert "L10-20" in text
    assert "https://github.com/x/y" in text
    assert "this should not appear" not in text
    assert "0.9" not in text
    assert "```" not in text


def test_format_citations_handles_empty() -> None:
    assert "No results" in format_citations([])


def test_format_citations_dedupes_by_document() -> None:
    text = format_citations(
        [
            {
                "document_id": "d1",
                "source": "github",
                "file_path": "a.py",
                "url": "https://x#L1",
            },
            {
                "document_id": "d1",
                "source": "github",
                "file_path": "a.py",
                "url": "https://x#L5",
            },
            {"document_id": "d2", "source": "notion", "url": "https://n"},
        ]
    )
    assert text.count("a.py") == 1
    assert "notion" in text


@pytest.mark.asyncio
async def test_dispatch_cite_passes_args_and_skips_previews() -> None:
    client = _StubClient(
        chunks=[
            {
                "document_id": "g1",
                "source": "github",
                "file_path": "x.py",
                "url": "https://x#L1",
                "content_preview": "secret preview",
            }
        ]
    )
    out = await _dispatch(client, "cite", {"query": "deploy", "top_k": 3})
    assert client.last_search == {"query": "deploy", "top_k": 3, "source": None}
    assert "x.py" in out
    assert "secret preview" not in out


def test_format_search_does_not_fence_notion_previews() -> None:
    text = format_search_results(
        [
            {
                "document_title": "Architecture",
                "source": "notion",
                "file_path": None,
                "content_preview": "Some prose about the system.",
            }
        ]
    )
    assert "```" not in text
    assert "Some prose about the system." in text
