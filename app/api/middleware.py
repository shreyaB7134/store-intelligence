from __future__ import annotations
import time
import uuid
import logging
import json
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Emit structured JSON log for every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = str(uuid.uuid4())
        start_time = time.monotonic()

        request.state.trace_id = trace_id

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = round((time.monotonic() - start_time) * 1000, 2)
            event_count = getattr(request.state, "event_count", 0)
            logger.error(
                json.dumps({
                    "trace_id": trace_id,
                    "endpoint": str(request.url.path),
                    "method": request.method,
                    "latency_ms": latency_ms,
                    "event_count": event_count,
                    "status_code": 500,
                    "error": type(exc).__name__,
                })
            )
            raise

        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        store_id = request.path_params.get("store_id", "-")
        event_count = getattr(request.state, "event_count", 0)

        logger.info(
            json.dumps({
                "trace_id": trace_id,
                "store_id": store_id,
                "endpoint": str(request.url.path),
                "method": request.method,
                "latency_ms": latency_ms,
                "event_count": event_count,
                "status_code": response.status_code,
            })
        )
        response.headers["X-Trace-ID"] = trace_id
        return response
