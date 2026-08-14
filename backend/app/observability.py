"""Structured JSON logs + request IDs. Kept boring on purpose."""
from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = structlog.get_logger().bind(request_id=request_id, path=request.url.path)
    started = time.perf_counter()
    response = await call_next(request)
    log.info(
        "request",
        status=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    response.headers["x-request-id"] = request_id
    return response
