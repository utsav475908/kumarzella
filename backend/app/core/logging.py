"""Structured logging. Financial payloads and secrets must never be passed to log calls."""

import logging
import sys

import structlog

from app.core.config import get_settings

REDACT_KEYS = {"password", "token", "secret", "authorization", "cookie", "access_key", "secret_key"}


def _redact(_, __, event_dict):
    for key in list(event_dict):
        if any(k in key.lower() for k in REDACT_KEYS):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging() -> None:
    s = get_settings()
    level = getattr(logging, s.log_level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
    renderer = structlog.processors.JSONRenderer() if s.log_json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
