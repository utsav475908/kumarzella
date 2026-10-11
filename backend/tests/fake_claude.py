"""A scripted stand-in for the Claude Messages API (and OpenAI Chat Completions), for tests and offline development.

It is not a model. It follows one fixed script so the real Anthropic SDK code path (HTTP, headers, parsing) can be
tested without a network or an API key:

1. First call of a conversation: ask for ``performance_summary`` with no filters.
2. Once a tool result is in the conversation: answer with the net P&L, closed-trade count and win rate copied from
   that result, citing its evidence ref.

Every answer says it came from this test server, so it can't be mistaken for real coaching.

Run: ``python -m tests.fake_claude --port 8765`` and start the API with ``EL_ANTHROPIC_BASE_URL=http://127.0.0.1:8765``
and any ``EL_ANTHROPIC_API_KEY`` (or ``EL_OPENAI_BASE_URL=http://127.0.0.1:8765/v1`` and any ``EL_OPENAI_API_KEY``). ``GET /last`` returns the last request's headers and body.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count

_ids = count(1)
LAST: dict = {}
NO_FILTERS = {"date_from": None, "date_to": None, "symbols": [], "direction": None, "playbook": None, "tag": None,
              "outcome": None}  # fmt: skip


def _message(content: list[dict], stop: str, model: str) -> dict:
    return {"id": f"msg_fake_{next(_ids)}", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 1500, "output_tokens": 200, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}}  # fmt: skip


def respond(body: dict) -> dict:
    model = body.get("model", "fake")
    results = [b for m in body.get("messages", []) if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result" and not b.get("is_error")]  # fmt: skip
    if not results:
        use = {"type": "tool_use", "id": f"toolu_fake_{next(_ids)}", "name": "performance_summary",
               "input": {"filters": NO_FILTERS, "currency": None}}  # fmt: skip
        return _message([use], "tool_use", model)
    r = json.loads(results[-1]["content"])
    s, ref = r["data"]["summary"], r["evidence_ref"]
    if s["closed_trades"]:
        rate = f"{(Decimal(s['win_rate']) * 100).quantize(Decimal('0.1'))}%" if s["win_rate"] else "not defined"
        answer = (f"(Scripted test server, not a real model.) Net P&L is ${s['net_pnl']} over {s['closed_trades']} "
                  f"closed trades [{ref}].\n- Win rate: {rate} [{ref}].")  # fmt: skip
    else:
        answer = "(Scripted test server, not a real model.) There are no closed trades yet."
    text = json.dumps({"answer": answer, "limitations": [], "suggested_tags": []})
    return _message([{"type": "text", "text": text}], "end_turn", model)


def respond_openai(body: dict) -> dict:
    """The same script in OpenAI Chat Completions shape."""
    model = body.get("model", "fake")
    results = [m for m in body.get("messages", []) if m["role"] == "tool" and not m["content"].startswith("Error:")]
    if not results:
        msg = {"role": "assistant", "content": None, "refusal": None, "tool_calls": [{
            "id": f"call_fake_{next(_ids)}", "type": "function",
            "function": {"name": "performance_summary", "arguments": json.dumps({"filters": NO_FILTERS, "currency": None})}}]}  # fmt: skip
        finish = "tool_calls"
    else:
        fake_anthropic = {
            "messages": [{"role": "user", "content": [{"type": "tool_result", "content": results[-1]["content"]}]}]
        }
        text = respond(fake_anthropic)["content"][0]["text"]
        msg, finish = {"role": "assistant", "content": text, "refusal": None}, "stop"
    return {"id": f"chatcmpl-fake{next(_ids)}", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish, "logprobs": None}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 200, "total_tokens": 1700,
                      "prompt_tokens_details": {"cached_tokens": 0}}}  # fmt: skip


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        LAST.clear()
        LAST.update({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        out = json.dumps(respond_openai(body) if self.path.endswith("/chat/completions") else respond(body)).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("request-id", f"req_fake_{next(_ids)}")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):  # noqa: N802
        out = json.dumps(LAST).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):  # keep test output quiet
        pass


def serve(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    serve(ap.parse_args().port).serve_forever()
