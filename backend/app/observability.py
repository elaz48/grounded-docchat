"""Structured JSON logs + request IDs. Kept boring on purpose."""
from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request


def configure_logging() -> None:
    structlog.configure(
        processors=[
            # First in the chain: every log line, from any module, picks up
            # whatever the middleware bound for this request. Without it,
            # request_id would only appear on lines logged through the bound
            # logger the middleware holds - which is exactly the lines that
            # need it least.
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    # Bound before call_next so the downstream task inherits the context;
    # cleared first so nothing from a previous request can leak in.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    log = structlog.get_logger()
    started = time.perf_counter()
    response = await call_next(request)
    log.info(
        "request",
        status=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    response.headers["x-request-id"] = request_id
    return response
