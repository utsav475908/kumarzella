from contextvars import ContextVar

current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
current_ip: ContextVar[str | None] = ContextVar("current_ip", default=None)
