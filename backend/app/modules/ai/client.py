"""The connection to the model. Kept behind a tiny interface so tests run against a scripted fake, never the network.

The coach runs on the operator's own key: Anthropic (``EL_ANTHROPIC_API_KEY``, Claude) or OpenAI
(``EL_OPENAI_API_KEY``) or DeepSeek (``EL_DEEPSEEK_API_KEY``). Without a key the coach reports that it is not configured and nothing is sent anywhere.

The coach speaks the Anthropic Messages format (content blocks: text, tool_use, tool_result). ``OpenAIClient``
translates that request to OpenAI Chat Completions and the reply back, so the tool loop, the evidence check and the
storage are the same for both providers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Protocol

import anthropic
import openai

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
    provider: str
    model: str

    def create(self, **params: Any) -> Any:
        """Sends one Messages API request and returns the message (content blocks, stop_reason, usage, model)."""


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, base_url: str | None, timeout: float, fallbacks: bool,
                 model: str = "claude-opus-5-5"):  # fmt: skip
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)
        self._fallbacks = fallbacks
        self.model = model

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


class OpenAIClient:
    """Runs the coach's Anthropic-format requests on OpenAI Chat Completions and translates the replies back."""

    provider = "openai"
    label = "OpenAI"
    # DeepSeek speaks the same protocol with a narrower feature set: plain JSON mode instead of a JSON schema, no
    # strict tools, no reasoning_effort, and max_tokens instead of max_completion_tokens. Compatible servers are
    # handled by turning ``strict_schema`` off.
    strict_schema = True
    system_role = "developer"

    def __init__(self, api_key: str, base_url: str | None, timeout: float, model: str):
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)
        self.model = model

    def _messages(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": self.system_role, "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            blocks = [b if isinstance(b, dict) else b.model_dump() for b in content]
            if m["role"] == "assistant":
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or None
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                         for b in blocks if b.get("type") == "tool_use"]  # fmt: skip
                msg: dict[str, Any] = {"role": "assistant", "content": text}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            texts = []
            for b in blocks:
                if b.get("type") == "tool_result":
                    body = b.get("content") if isinstance(b.get("content"), str) else json.dumps(b.get("content"))
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                "content": f"Error: {body}" if b.get("is_error") else body})  # fmt: skip
                elif b.get("type") == "text":
                    texts.append(b["text"])
            if texts:
                out.append({"role": "user", "content": "\n\n".join(texts)})
        return out

    def _reply(self, r: Any) -> dict:
        if not getattr(r, "choices", None):
            raise CoachUnavailable(f"{self.label} returned a reply with no answer in it. Try again shortly.")
        choice = r.choices[0]
        msg = choice.message
        content: list[dict] = []
        if msg.content:
            content.append({"type": "text", "text": msg.content})
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {"_invalid_input": "The tool arguments were not valid JSON."}
            content.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": args})
        stop = {"tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}.get(
            choice.finish_reason, "end_turn"
        )
        if getattr(msg, "refusal", None):
            stop = "refusal"
        elif any(b["type"] == "tool_use" for b in content):
            stop = "tool_use"
        u = r.usage
        cached = (u.prompt_tokens_details.cached_tokens or 0) if u and u.prompt_tokens_details else 0
        usage = {"input_tokens": (u.prompt_tokens - cached) if u else 0, "output_tokens": u.completion_tokens if u else 0,
                 "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0}  # fmt: skip
        return {"content": content, "stop_reason": stop, "model": r.model, "usage": usage}

    def create(self, **params: Any) -> Any:
        strict = self.strict_schema
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                   "parameters": t["input_schema"], **({"strict": True} if strict else {})}}
                 for t in params.get("tools", [])]  # fmt: skip
        oc = params.get("output_config") or {}
        system = params["system"]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system, params["messages"]),
            "tools": tools,
        }
        schema = (oc.get("format") or {}).get("schema")
        if strict:
            kwargs["max_completion_tokens"] = params["max_tokens"]
            kwargs["reasoning_effort"] = oc.get("effort", "medium")
            if schema:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "coach_answer", "schema": schema, "strict": True}}  # fmt: skip
        else:
            kwargs["max_tokens"] = params["max_tokens"]
            if schema:
                kwargs["response_format"] = {"type": "json_object"}
                kwargs["messages"][0]["content"] = (
                    f"{system}\n\nYour final reply must be one JSON object (and nothing else) that matches this JSON "
                    f"schema:\n{json.dumps(schema)}"
                )
        try:
            return self._reply(self._client.chat.completions.create(**kwargs))
        except openai.AuthenticationError:
            raise CoachUnavailable(f"The {self.label} API key was rejected. Check {self.provider.upper()}_API_KEY.")
        except openai.PermissionDeniedError:
            raise CoachUnavailable(f"The {self.label} API key isn't allowed to use {self.model}.")
        except openai.RateLimitError:
            raise CoachUnavailable(f"{self.label} is rate-limiting this key, or its quota or balance is used up.")
        except openai.NotFoundError:
            raise CoachUnavailable(f"{self.label} doesn't offer the model {self.model!r} to this key.")
        except openai.BadRequestError as e:
            raise CoachUnavailable(f"{self.label} rejected the request: {e.message}")
        except openai.APIStatusError as e:
            raise CoachUnavailable(f"{self.label} returned an error ({e.status_code}). Try again shortly.")
        except openai.APIConnectionError:
            raise CoachUnavailable(f"Couldn't reach {self.label}. Check the server's internet connection.")


class DeepSeekClient(OpenAIClient):
    """DeepSeek's OpenAI-compatible API. The evidence check, not a schema guarantee, keeps answers honest."""

    provider = "deepseek"
    label = "DeepSeek"
    strict_schema = False
    system_role = "system"


_override: LLMClient | None = None


def set_client_for_tests(client: LLMClient | None) -> None:
    global _override
    _override = client
    _real_client.cache_clear()


def _key(v) -> str | None:
    return v.get_secret_value().strip() or None if v is not None else None


@lru_cache
def _real_client() -> LLMClient | None:
    s = get_settings()
    ak, ok, dk = _key(s.anthropic_api_key), _key(s.openai_api_key), _key(s.deepseek_api_key)
    provider = s.ai_provider
    if provider == "auto":
        provider = "anthropic" if ak else "openai" if ok else "deepseek" if dk else None
    if provider == "anthropic" and ak:
        return AnthropicClient(ak, s.anthropic_base_url, s.ai_timeout_seconds, s.ai_fallbacks, s.ai_model)
    if provider == "openai" and ok:
        return OpenAIClient(ok, s.openai_base_url, s.ai_timeout_seconds, s.openai_model)
    if provider == "deepseek" and dk:
        return DeepSeekClient(dk, s.deepseek_base_url, s.ai_timeout_seconds, s.deepseek_model)
    return None


def get_client() -> LLMClient:
    if _override is not None:
        return _override
    c = _real_client()
    if c is None:
        raise CoachNotConfigured(
            "The AI coach isn't set up. Add your own API key: OPENAI_API_KEY, DEEPSEEK_API_KEY or ANTHROPIC_API_KEY in the .env file "
            "next to docker-compose.yml (see README, AI coach)."
        )
    return c


def active() -> LLMClient | None:
    return _override if _override is not None else _real_client()


def configured() -> bool:
    return active() is not None
