"""The connection to Claude. Kept behind a tiny interface so tests run against a scripted fake, never the network.

The coach needs the trader's own Anthropic API key (``EL_ANTHROPIC_API_KEY``). Without it the coach reports that it
is not configured and nothing is sent anywhere.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

import anthropic

from app.core.config import get_settings
from app.core.errors import AppError

# Server-side refusal fallback: when the model declines, the API re-runs the request on Anthropic's recommended
# fallback model inside the same call. The scalar "default" form needs this beta header.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class CoachUnavailable(AppError):
    status_code = 503
    code = "ai_unavailable"


class CoachNotConfigured(AppError):
    status_code = 503
    code = "ai_not_configured"


class LLMClient(Protocol):
    def create(self, **params: Any) -> Any:
        """Sends one Messages API request and returns the message (content blocks, stop_reason, usage, model)."""


class AnthropicClient:
    def __init__(self, api_key: str, base_url: str | None, timeout: float, fallbacks: bool):
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)
        self._fallbacks = fallbacks

    def create(self, **params: Any) -> Any:
        extra: dict[str, Any] = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if self._fallbacks else {}
        try:
            return self._client.beta.messages.create(**params, **extra)
        except anthropic.AuthenticationError:
            raise CoachUnavailable("The Anthropic API key was rejected. Check EL_ANTHROPIC_API_KEY.")
        except anthropic.PermissionDeniedError:
            raise CoachUnavailable("The Anthropic API key isn't allowed to use this model.")
        except anthropic.RateLimitError:
            raise CoachUnavailable("The AI service is rate-limiting this key. Try again in a minute.")
        except anthropic.BadRequestError as e:
            raise CoachUnavailable(f"The AI service rejected the request: {e.message}")
        except anthropic.APIStatusError as e:
            raise CoachUnavailable(f"The AI service returned an error ({e.status_code}). Try again shortly.")
        except anthropic.APIConnectionError:
            raise CoachUnavailable("Couldn't reach the AI service. Check the server's internet connection.")


_override: LLMClient | None = None


def set_client_for_tests(client: LLMClient | None) -> None:
    global _override
    _override = client
    _real_client.cache_clear()


@lru_cache
def _real_client() -> AnthropicClient | None:
    s = get_settings()
    if s.anthropic_api_key is None or not s.anthropic_api_key.get_secret_value().strip():
        return None
    return AnthropicClient(s.anthropic_api_key.get_secret_value().strip(), s.anthropic_base_url,
                           s.ai_timeout_seconds, s.ai_fallbacks)  # fmt: skip


def get_client() -> LLMClient:
    if _override is not None:
        return _override
    c = _real_client()
    if c is None:
        raise CoachNotConfigured(
            "The AI coach isn't set up. Add your Anthropic API key as EL_ANTHROPIC_API_KEY (see README, AI coach)."
        )
    return c


def configured() -> bool:
    return _override is not None or _real_client() is not None
