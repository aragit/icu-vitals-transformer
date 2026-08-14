"""Correlation-ID + legacy deprecation middleware (REST driving adapter).

Adds ``X-Request-ID`` to every response (generating one when the caller does
not supply it, stored on ``request.state`` for downstream handlers/loggers),
and stamps structured ``Deprecation`` / ``Link`` headers onto the legacy v1
``/vitals/*`` routes so clients can migrate to the v2 episode-aware surface.
"""

from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from src.auth.cimd import parse_optional_bearer
from src.observability.logging import set_correlation_id, set_requested_by

V1_DEPRECATION_HEADER = "true"
V1_ALTERNATE_LINK = '</v2/vitals/ingest>; rel="alternate"'


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Inject/forward a correlation ID and flag deprecated v1 routes.

    Also parses an optional CIMD/JWT bearer token (dev-stub: signature **not**
    verified) and binds the ``requested_by`` principal into logging contextvars
    so audit logs record caller identity alongside the correlation ID.
    Unauthenticated requests pass through with an anonymous principal.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        set_correlation_id(correlation_id)

        principal = parse_optional_bearer(request.headers.get("Authorization"))
        if principal.get("requested_by"):
            set_requested_by(principal["requested_by"])

        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id

        if request.url.path.startswith("/vitals/"):
            response.headers["Deprecation"] = V1_DEPRECATION_HEADER
            response.headers["Link"] = V1_ALTERNATE_LINK

        return response
