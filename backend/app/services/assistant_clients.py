"""Real adapters for the assistant: Claude (Anthropic SDK) and the MCP server (streamable HTTP)."""
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import anthropic
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.core.config import Settings
from app.services.assistant import AssistantError, ToolOutcome, parse_tool_text

logger = logging.getLogger(__name__)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM:
    """One Messages API call per loop turn."""

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._s = settings
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.assistant_timeout_seconds)

    async def create(self, *, system: list[dict], tools: list[dict], messages: list[dict]) -> Any:
        s = self._s
        kwargs: dict[str, Any] = dict(
            model=s.assistant_model, max_tokens=s.assistant_max_tokens, system=system, tools=tools, messages=messages,
            # Thinking is always on for this model family; effort is the cost/quality control.
            output_config={"effort": s.assistant_effort},
        )
        if s.assistant_use_fallbacks:
            # If a safety classifier declines, the API re-runs the request on Anthropic's recommended fallback.
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            response = await self._client.beta.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise AssistantError("The assistant is busy right now. Please try again in a minute.") from exc
        except anthropic.AuthenticationError as exc:
            logger.error("Anthropic credentials were rejected")
            raise AssistantError("The assistant is not configured correctly.") from exc
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            logger.warning("Anthropic API error", extra={"error": type(exc).__name__, "request_id": getattr(exc, "request_id", None)})
            raise AssistantError("The assistant is temporarily unavailable. Please try again shortly.") from exc
        logger.info("assistant llm call", extra={"request_id": getattr(response, "_request_id", None), "stop_reason": response.stop_reason})
        return response


class McpToolBackend:
    """Tools served by the MCP server over an open client session."""

    _cache: tuple[float, list[dict]] | None = None  # tool definitions are identical for every user

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def tool_definitions(self) -> list[dict]:
        cached = McpToolBackend._cache
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        result = await self._session.list_tools()
        # Sorted by name so the tools block is byte-identical between requests (prompt-cache friendly).
        defs = [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in sorted(result.tools, key=lambda t: t.name)
        ]
        McpToolBackend._cache = (time.monotonic(), defs)
        return defs

    async def call(self, name: str, arguments: dict) -> ToolOutcome:
        result = await self._session.call_tool(name, arguments)
        return ToolOutcome(parse_tool_text(result), bool(result.isError))


@asynccontextmanager
async def open_mcp_backend(url: str, user_token: str | None) -> AsyncIterator[McpToolBackend]:
    """Connect to the MCP server, forwarding the signed-in user's token so user-scoped tools act as them."""
    headers = {"Authorization": f"Bearer {user_token}"} if user_token else None
    try:
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield McpToolBackend(session)
    except* (OSError, httpx.TransportError) as group:
        logger.warning("MCP server unreachable", extra={"url": url, "error": str(group.exceptions[0])[:200]})
        raise AssistantError("The assistant's tools are unavailable right now. Please try again shortly.") from None
