"""AI shopping assistant endpoints."""
import logging
from typing import Annotated, Awaitable, Callable, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import GeneralLimit, UserDep, hit_limit, raw_token
from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError, ValidationFailed
from app.schemas.common import Envelope, ok
from app.services.assistant import AssistantError, AssistantReply, ChatMessage, run_assistant
from app.services.assistant_clients import AnthropicLLM, open_mcp_backend

logger = logging.getLogger("app.assistant")
router = APIRouter(prefix="/api/assistant", tags=["assistant"], dependencies=[GeneralLimit])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=20)
    product_id: int | None = Field(default=None, ge=1, description="Product the user is viewing, if any")


class StepOut(BaseModel):
    tool: str
    summary: str
    ok: bool


class ChatResponse(BaseModel):
    reply: str
    steps: list[StepOut]
    model: str | None = None
    stop: str


class AssistantStatus(BaseModel):
    enabled: bool
    model: str | None = None


Runner = Callable[[list[ChatMessage], int | None, str | None, Settings], Awaitable[AssistantReply]]


async def default_runner(history: list[ChatMessage], product_id: int | None, token: str | None, settings: Settings) -> AssistantReply:
    """Claude + the MCP server. Replaced in tests."""
    llm = AnthropicLLM(settings)
    result: AssistantReply | None = None
    failure: AssistantError | None = None
    async with open_mcp_backend(settings.mcp_server_url, token) as backend:
        try:
            result = await run_assistant(
                llm, backend, history, product_context=product_id,
                max_iterations=settings.assistant_max_iterations, max_tool_calls=settings.assistant_max_tool_calls,
            )
        except AssistantError as exc:
            failure = exc  # caught here: the MCP transport's task group would otherwise wrap it
    if failure:
        raise failure
    assert result is not None
    return result


def get_runner() -> Runner:
    return default_runner


@router.get("/status", response_model=Envelope[AssistantStatus])
async def status():
    s = get_settings()
    return ok(AssistantStatus(enabled=bool(s.anthropic_api_key), model=s.assistant_model if s.anthropic_api_key else None))


@router.post("/chat", response_model=Envelope[ChatResponse])
async def chat(
    body: ChatRequest, request: Request, user: UserDep,
    token: Annotated[str | None, Depends(raw_token)], runner: Annotated[Runner, Depends(get_runner)],
):
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ServiceUnavailableError("The AI assistant isn't set up yet. An administrator needs to add an Anthropic API key.")
    if body.messages[0].role != "user" or body.messages[-1].role != "user":
        raise ValidationFailed("The conversation must start and end with a message from you")

    # Each request can cost real money, so limit per signed-in user (not just per IP).
    await hit_limit(request, "assistant-user", str(user.id), settings.assistant_rate_limit_per_hour, 3600)

    history = [ChatMessage(t.role, t.content) for t in body.messages]
    try:
        reply = await runner(history, body.product_id, token, settings)
    except AssistantError as exc:
        raise ServiceUnavailableError(str(exc)) from None
    logger.info("assistant answered", extra={"user_id": user.id, "tools": [s.tool for s in reply.steps], "stop": reply.stop,
                                             "iterations": reply.iterations, "usage": reply.usage})
    return ok(ChatResponse(reply=reply.reply, steps=[StepOut(tool=s.tool, summary=s.summary, ok=s.ok) for s in reply.steps],
                           model=reply.model, stop=reply.stop))
