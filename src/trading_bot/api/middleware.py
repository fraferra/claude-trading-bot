"""Basic Auth middleware for protecting the trading bot dashboard and API."""

from __future__ import annotations

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Authentication middleware.

    Protects all routes. If username/password are not configured,
    the middleware is a no-op (pass-through for local dev).
    """

    def __init__(self, app, username: str, password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password
        self._enabled = bool(username and password)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._enabled:
            return await call_next(request)

        # Skip auth for WebSocket upgrade requests (handled separately)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                provided_user, provided_pass = decoded.split(":", 1)
                if (
                    secrets.compare_digest(provided_user, self._username)
                    and secrets.compare_digest(provided_pass, self._password)
                ):
                    return await call_next(request)
            except Exception:
                pass

        # For API requests (XHR/fetch), return 401 WITHOUT WWW-Authenticate
        # to prevent the browser from popping up its native auth dialog.
        # Only send WWW-Authenticate on page loads so the browser prompts once.
        is_api = request.url.path.startswith("/api/")
        is_fetch = "application/json" in request.headers.get("accept", "")
        is_xhr = request.headers.get("x-requested-with", "").lower() == "xmlhttprequest"

        if is_api or is_fetch or is_xhr:
            return Response(status_code=401, content="Unauthorized")

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Trading Bot"'},
            content="Unauthorized",
        )
