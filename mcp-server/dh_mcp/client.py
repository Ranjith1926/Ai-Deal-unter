"""HTTP client for the Deal Hunter REST API.

The MCP server holds no business logic and never touches the database: every tool calls the
same API the website uses, so scoring, validation and access rules live in one place.
"""
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.fastmcp.exceptions import ToolError

BASE_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
TIMEOUT = float(os.getenv("DEAL_HUNTER_TIMEOUT", "15"))

# Tests point the client at an in-process ASGI app instead of the network.
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


@dataclass
class ApiResponse:
    data: Any
    meta: dict | None
    message: str | None


class TokenProvider:
    """Finds the bearer token for user-scoped tools.

    Order: the ``Authorization`` header of the MCP HTTP request (so a web app can pass its
    user's token through), then a static ``DEAL_HUNTER_TOKEN``, then a login with
    ``DEAL_HUNTER_EMAIL`` / ``DEAL_HUNTER_PASSWORD`` (stdio use, renewed automatically).
    """

    def __init__(self) -> None:
        self._cached: tuple[str, float] | None = None

    async def token(self, header_token: str | None, *, force_login: bool = False) -> str | None:
        if header_token:
            return header_token
        if os.getenv("DEAL_HUNTER_TOKEN"):
            return os.environ["DEAL_HUNTER_TOKEN"]
        email, password = os.getenv("DEAL_HUNTER_EMAIL"), os.getenv("DEAL_HUNTER_PASSWORD")
        if not (email and password):
            return None
        if self._cached and not force_login and self._cached[1] > time.monotonic() + 30:
            return self._cached[0]
        res = await request("POST", "/api/auth/login", json={"email": email, "password": password})
        self._cached = (res.data["access_token"], time.monotonic() + float(res.data.get("expires_in", 900)))
        return self._cached[0]


tokens = TokenProvider()


def _error_for(status: int, body: dict | None, headers: httpx.Headers, authed: bool) -> ToolError:
    message = (body or {}).get("message") or f"Request failed ({status})"
    errors = (body or {}).get("errors") or []
    detail = f" ({'; '.join(errors)})" if errors else ""
    if status == 401:
        return ToolError(
            "Not signed in. This tool acts on a user's account; connect it with a user access token "
            "(Authorization header), or set DEAL_HUNTER_EMAIL and DEAL_HUNTER_PASSWORD." if not authed
            else f"Authentication failed: {message}"
        )
    if status == 404:
        return ToolError(message)
    if status == 422:
        return ToolError(f"Invalid request: {message}{detail}")
    if status == 429:
        return ToolError(f"Rate limited by the Deal Hunter API. Retry in {headers.get('retry-after', 'a few')} seconds.")
    if status >= 500:
        return ToolError("The Deal Hunter service had an internal error. Try again shortly.")
    return ToolError(f"{message}{detail}")


async def request(
    method: str, path: str, *, params: dict | None = None, json: Any = None, token: str | None = None
) -> ApiResponse:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT, transport=_transport) as client:
            res = await client.request(method, path, params=clean, json=json, headers=headers)
    except httpx.HTTPError:
        raise ToolError("The Deal Hunter service is unreachable right now. Try again shortly.") from None
    try:
        body = res.json()
    except ValueError:
        body = None
    if res.status_code >= 400 or not (body or {}).get("success", False):
        raise _error_for(res.status_code, body, res.headers, authed=token is not None)
    return ApiResponse(body.get("data"), body.get("meta"), body.get("message"))
